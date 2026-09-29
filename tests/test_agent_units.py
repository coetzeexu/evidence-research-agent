import pytest
from research_app.agents import compare_units, same_instant


@pytest.mark.parametrize(
    "left,left_unit,right,right_unit,equal",
    [
        (53.95, "billion", 539.5, "亿", True),
        (53.95, "billion", 53.95, "亿", False),
        (0.025, "number", 2.5, "percent", True),
        (10, "bps", 0.1, "percent", True),
    ],
)
def test_review_numeric_conversion(left, left_unit, right, right_unit, equal):
    assert compare_units(left, left_unit, right, right_unit)["equal"] is equal


@pytest.mark.parametrize(
    "timestamp", ["2023-05-24T20:28:58Z", "2023-05-24T20:28:58+0000", "2023-05-24T16:28:58-04:00"]
)
def test_equivalent_source_timestamps_are_not_downgraded(timestamp):
    assert same_instant(timestamp, "2023-05-24T20:28:58+00:00")
    assert not same_instant(timestamp, "2023-05-24")
    assert not same_instant(timestamp, None)


async def test_repair_preserves_event_context_and_stops_failed_search_provider(monkeypatch, tmp_path, bundle):
    bundle.spec.intent = "event_study"
    import json

    from research_app import agents as module
    from research_app.config import Settings
    from research_app.storage import Store

    seen = []
    read_attempts = []
    from types import SimpleNamespace

    model = SimpleNamespace()
    model.model_copy = lambda **kwargs: model
    monkeypatch.setattr(module, "llm", lambda config: model)

    async def unavailable(url):
        read_attempts.append(url)
        raise ConnectionError("provider unavailable")

    from research_app import providers as public_providers

    monkeypatch.setattr(public_providers, "read_source", unavailable)

    class FakeAgent:
        def __init__(self, tools):
            self.tools = tools

        async def ainvoke(self, payload, config):
            seen.append(json.loads(payload["messages"][0]["content"]))
            if self.tools:
                search = next(t for t in self.tools if t.name == "search_public")
                response = await search.ainvoke(
                    {"query": "third request", "start": "2023-01-01", "end": "2023-01-10", "provider": "web"}
                )
                assert "不扣预算" in response
                read = next(t for t in self.tools if t.name == "read_public_source")
                url = "https://openai.com/index/chatgpt/"
                for _ in range(3):
                    response = json.loads(await read.ainvoke({"url": url}))
                    assert response["status"] == "unavailable"
                    assert response["alternative_locators"]
                assert len(read_attempts) == 2
                return {}
            return {"structured_response": module.ResearchResult()}

    def create(model, tools, **kwargs):
        assert kwargs["checkpointer"] is False
        return FakeAgent(tools)

    monkeypatch.setattr(module, "create_agent", create)
    store = Store(tmp_path)
    rid = store.create("repair")
    previous = module.ResearchResult(events=bundle.events)
    store.save_json(store.run_dir(rid) / "events.json", previous.model_dump(mode="json"))
    runtime = module.AgentRuntime(Settings(tmp_path, "model", "token", "https://example.com"), store, rid)
    runtime.coverage = [{"provider": "web", "status": "failed"}] * 2
    runtime.search_count = 2
    repair = json.dumps({"critical": [{"object_id": bundle.events[0].id, "issue": "missing date evidence"}]})
    await runtime.research(bundle.spec, [], repair)
    assert runtime.search_count == 2
    assert runtime.read_count == 2
    restored = module.AgentRuntime(Settings(tmp_path, "model", "token", "https://example.com"), store, rid)
    assert restored.failed_reads["https://openai.com/index/chatgpt/"] == 2
    assert len(seen) == 2
    assert all(x["previous_events"]["events"][0]["id"] == bundle.events[0].id for x in seen)
    assert all(x["repair_request"] == repair for x in seen)


@pytest.mark.parametrize(
    "final_severity,expected", [("warning", True), ("critical", False), ("timeout", False)]
)
async def test_critical_review_adjudication_retains_audit_and_real_failures(
    monkeypatch, tmp_path, bundle, final_severity, expected
):
    import json
    from types import SimpleNamespace

    from research_app import agents as module
    from research_app.config import Settings
    from research_app.storage import Store

    model = SimpleNamespace()
    model.model_copy = lambda **kwargs: model
    monkeypatch.setattr(module, "llm", lambda config: model)
    finding = module.Finding(
        object_id=bundle.events[0].id, severity="critical", issue="Disputed fact", repair="Verify source"
    )
    original = module.ReviewResult(passed=False, findings=[finding], summary="Initial decision")
    revised = module.ReviewResult(
        passed=expected,
        findings=[
            finding.model_copy(
                update={"severity": "critical" if final_severity == "timeout" else final_severity}
            )
        ],
        summary="Evidence adjudicated",
    )
    responses = [
        {"messages": []},
        {"structured_response": original},
        {"messages": []},
        {"structured_response": revised},
    ]

    class Agent:
        async def ainvoke(self, payload, config):
            if final_severity == "timeout" and len(responses) == 2:
                raise TimeoutError("Dispute review interrupted")
            return responses.pop(0)

    monkeypatch.setattr(module, "create_agent", lambda *args, **kwargs: Agent())
    store = Store(tmp_path)
    rid = store.create("review")
    runtime = module.AgentRuntime(Settings(tmp_path, "model", "token", "https://example.com"), store, rid)
    runtime.sources = {s.id: s for s in bundle.sources}
    runtime.texts = {s.id: "Saved evidence" for s in bundle.sources}
    result = await runtime.review(bundle)
    assert result.passed is expected
    audit = json.loads((store.run_dir(rid) / "review-adjudications.json").read_text())
    assert audit[0]["initial"]["findings"][0]["severity"] == "critical"
    if final_severity == "timeout":
        assert audit[0]["status"] == "incomplete"
        assert result.findings == original.findings
    else:
        assert audit[0]["adjudicated"]["findings"][0]["severity"] == final_severity


@pytest.mark.parametrize("platform", ["", "maas"])
def test_optional_gateway_platform_header(monkeypatch, tmp_path, platform):
    from research_app import agents as module
    from research_app.config import Settings

    monkeypatch.setattr(module, "StructuredChatOpenAI", lambda **kwargs: kwargs)
    options = module.llm(
        Settings(tmp_path, "deployment-alias", "test-token", "https://gateway.example/v1", platform=platform)
    )
    assert options["streaming"] is True
    assert options["model"] == "deployment-alias"
    assert options.get("default_headers") == ({"X-PLATFORM": "maas"} if platform else None)


def test_vllm_can_disable_hidden_reasoning_without_changing_token_limit(monkeypatch, tmp_path):
    from research_app import agents as module
    from research_app.config import Settings

    monkeypatch.setattr(module, "StructuredChatOpenAI", lambda **kwargs: kwargs)
    options = module.llm(
        Settings(
            tmp_path,
            "deployment-alias",
            "test-token",
            "https://gateway.example/v1",
            platform="maas",
            vllm_thinking=False,
        )
    )
    assert options["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert options["max_tokens"] == 6000


def test_missing_structured_response_never_becomes_a_passing_review():
    from research_app.agents import ReviewResult, require_structured

    with pytest.raises(ValueError, match="不能视为核验通过"):
        require_structured({"structured_response": None}, ReviewResult, "核验")
    result = require_structured(
        {"structured_response": {"passed": False, "findings": [], "summary": "Incomplete"}},
        ReviewResult,
        "核验",
    )
    assert result.passed is False
