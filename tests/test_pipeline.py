import pytest
from research_app.agents import ParsedRequest
from research_app.config import Settings
from research_app.pipeline import Pipeline
from research_app.research_contract import ResearchAssessment
from research_app.storage import Store


@pytest.mark.parametrize(
    "refresh,private_snapshot,expected", [(False, True, True), (True, True, False), (False, False, False)]
)
async def test_parent_reuse_keeps_only_final_events_and_review(
    monkeypatch, tmp_path, bundle, refresh, private_snapshot, expected
):
    from research_app import pipeline as module

    class Runtime:
        def __init__(self, *args):
            self.sources = {s.id: s for s in bundle.sources}
            self.coverage = []

    monkeypatch.setattr(module, "AgentRuntime", Runtime)
    store = Store(tmp_path)
    cfg = Settings(tmp_path, "model", "test-token", "https://example.com")
    parent = store.create("parent", spec=bundle.spec.model_dump(mode="json"))
    root = store.run_dir(parent)
    bundle.review = {
        "passed": True,
        "summary": "source warning",
        "findings": [
            {
                "object_id": bundle.events[0].id,
                "severity": "warning",
                "issue": "date only",
                "repair": "preserve uncertainty",
            }
        ],
    }
    store.save_json(root / "bundle.json", bundle.model_dump(mode="json"))
    store.update(parent, bundle_path=str(root / "bundle.json"))
    if private_snapshot:
        for name, value in {
            "collection.json": {},
            "events.json": {"events": []},
            "research-evidence.json": {},
        }.items():
            store.save_json(root / name, value)
    child = store.create(
        "change weights", parent_id=parent, spec=bundle.spec.model_dump(mode="json"), refresh=refresh
    )
    job = Pipeline(cfg, store, child, export=False)
    state = await job.plan({})
    assert state["reuse"] is expected
    if expected:
        assert job.read("events.json")["events"][0]["id"] == bundle.events[0].id
        job.write("bundle.json", bundle.model_dump(mode="json"))
        result = await job.review(state)
        assert result["review"]["findings"][0]["issue"] == "date only"
        assert result["review"]["inherited_from"] == bundle.id


async def test_clarification_preserves_original_request_and_question(monkeypatch, tmp_path, spec):
    from research_app import pipeline as module

    calls = []

    class Runtime:
        def __init__(self, *args):
            pass

        async def parse(self, request, previous=None, clarification=None):
            calls.append((request, previous, clarification))
            return ParsedRequest(spec=spec)

    monkeypatch.setattr(module, "AgentRuntime", Runtime)
    store = Store(tmp_path)
    parent = store.create("比较黄金和苹果近三年，成本 25 bps")
    store.update(parent, status="needs_input", error="苹果指 AAPL 股票吗？")
    child = store.create("是的", parent_id=parent)
    job = Pipeline(Settings(tmp_path, "model", "token", "https://example.com"), store, child, export=False)
    await job.plan({})
    assert calls[0][0] == "是的"
    assert calls[0][2] == [
        {"request": "比较黄金和苹果近三年，成本 25 bps", "question": "苹果指 AAPL 股票吗？"}
    ]


async def test_missing_requirements_trigger_bounded_repair(monkeypatch, tmp_path, bundle):
    from research_app import pipeline as module
    from research_app.agents import ReviewResult

    class Runtime:
        def __init__(self, *args):
            pass

        async def review(self, candidate):
            return ReviewResult(passed=True, findings=[], summary="Facts verified")

    monkeypatch.setattr(module, "AgentRuntime", Runtime)
    store = Store(tmp_path)
    rid = store.create("required event")
    job = Pipeline(Settings(tmp_path, "model", "token", "https://example.com"), store, rid, export=False)
    bundle.spec.required_events = ["missing model launch"]
    job.write("bundle.json", bundle.model_dump(mode="json"))
    first = await job.review({"repair_round": 0})
    assert "required_event" in first["repair"]
    assert first["repair_round"] == 1
    last = await job.review({"repair_round": 2})
    assert last["repair"] == ""
    assert job.read("bundle.json")["quality"]["passed"] is False


async def test_extractor_call_limit_preserves_existing_facts_and_discloses_gap(
    monkeypatch, tmp_path, bundle, datasets
):
    from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
    from research_app import pipeline as module
    from research_app.agents import ResearchResult

    calls = []

    class Runtime:
        def __init__(self, *args):
            self.sources = {source.id: source for source in bundle.sources}
            self.coverage = []

        async def research(self, spec, changes, repair, *, data_inventory):
            calls.append((repair, data_inventory))
            raise ModelCallLimitExceededError(4, 4, None, 4)

    monkeypatch.setattr(module, "AgentRuntime", Runtime)
    store = Store(tmp_path)
    rid = store.create("核实既有事件并补查新产品发布时间")
    job = Pipeline(Settings(tmp_path, "model", "token", "https://example.com"), store, rid, export=False)
    saved = ResearchResult(events=bundle.events, gaps=["尚缺新产品发布时间的原始来源"])
    job.write("events.json", saved.model_dump(mode="json"))
    evidence = {
        "sources": [source.model_dump(mode="json") for source in bundle.sources],
        "texts": {bundle.sources[0].id: "The policy event was announced on June 15, 2022."},
    }
    job.write("research-evidence.json", evidence)
    job.write(
        "collection.json",
        {
            "datasets": {symbol: dataset.model_dump(mode="json") for symbol, dataset in datasets.items()},
            "sources": [],
            "macro": {},
            "warnings": [],
        },
    )
    state = {"spec": bundle.spec.model_dump(mode="json"), "repair": "补查新产品发布时间原文"}

    assert await job.research(state) == {}
    result = ResearchResult.model_validate(job.read("events.json"))
    failure_gap = "本轮事件提取格式未收敛，保留已提取事件和原文，进入正文核验"
    assert result.events == saved.events
    assert result.gaps == [*saved.gaps, failure_gap]
    assert job.read("research-evidence.json") == evidence
    assert len(calls) == 1
    assert calls[0][0] == state["repair"]
    assert set(calls[0][1]["datasets"]) == set(datasets)
    notices = [event for event in store.events(rid) if event["kind"] == "budget"]
    assert [(event["label"], event["payload"]["phase"]) for event in notices] == [(failure_gap, "research")]

    await job.analyze(state)
    continued = module.ResearchBundle.model_validate(job.read("bundle.json"))
    assert continued.events == saved.events
    assert all(gap in continued.warnings for gap in result.gaps)
    assert continued.research is None
    assert store.get(rid)["status"] != "complete"


async def test_cancelled_run_is_never_restarted(monkeypatch, tmp_path):
    from research_app import pipeline as module

    class Runtime:
        def __init__(self, *args):
            pass

        async def parse(self, *args):
            pytest.fail("A cancelled task must not call the model")

    monkeypatch.setattr(module, "AgentRuntime", Runtime)
    store = Store(tmp_path)
    rid = store.create("cancel before startup")
    store.update(rid, status="cancelled")
    await Pipeline(Settings(tmp_path, "m", "t", "https://example.com"), store, rid, export=False).run()
    assert store.get(rid)["status"] == "cancelled"


async def test_checkpoint_retry_resumes_collection_without_replanning(monkeypatch, tmp_path, bundle):
    from research_app import pipeline as module

    calls = {"parse": 0, "collect": 0, "research": 0}

    class Runtime:
        def __init__(self, *args):
            pass

        async def parse(self, *args, **kwargs):
            calls["parse"] += 1
            return ParsedRequest(spec=bundle.spec)

    class Job(Pipeline):
        async def collect(self, state):
            calls["collect"] += 1
            if calls["collect"] == 1:
                raise ConnectionError("synthetic provider outage")
            self.write("collection.json", {"macro": {}})
            return {}

        async def research(self, state):
            calls["research"] += 1
            return {}

        async def analyze(self, state):
            self.write("bundle.json", bundle.model_dump(mode="json"))
            return {}

        async def review(self, state):
            return {"repair": ""}

        async def synthesize(self, state):
            saved = module.ResearchBundle.model_validate(self.read("bundle.json"))
            saved.research = ResearchAssessment(status="partial", text="Reviewed fixture")
            self.write("bundle.json", saved.model_dump(mode="json"))
            return {"repair": ""}

    monkeypatch.setattr(module, "AgentRuntime", Runtime)
    store = Store(tmp_path)
    cfg = Settings(tmp_path, "model", "token", "https://example.com")
    rid = store.create("compare")
    with pytest.raises(ConnectionError):
        await Job(cfg, store, rid, export=False).run()
    assert store.get(rid)["status"] == "failed"
    store.update(rid, status="queued")
    await Job(cfg, store, rid, export=False).run()
    assert calls == {"parse": 1, "collect": 2, "research": 1}
    assert store.get(rid)["status"] == "researched"


async def test_worker_survives_runtime_initialization_failure(monkeypatch, tmp_path):
    import asyncio

    from research_app import api
    from research_app import pipeline as module

    store = Store(tmp_path)
    first = store.create("constructor fails")
    second = store.create("next job")
    finished = asyncio.Event()

    class Job:
        def __init__(self, config, store, rid):
            if rid == first:
                raise ValueError("invalid saved evidence")
            self.rid = rid

        async def run(self):
            store.update(self.rid, status="complete")
            finished.set()

    monkeypatch.setattr(api, "store", store)
    monkeypatch.setattr(module, "Pipeline", Job)
    task = asyncio.create_task(api.worker())
    try:
        await asyncio.wait_for(finished.wait(), 2)
        assert store.get(first)["status"] == "failed"
        assert store.get(second)["status"] == "complete"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_cancel_during_execution_keeps_worker_available(monkeypatch, tmp_path):
    import asyncio

    from research_app import api
    from research_app import pipeline as module

    store = Store(tmp_path)
    first, second = store.create("slow job"), store.create("next job")
    started, finished = asyncio.Event(), asyncio.Event()

    class Job:
        def __init__(self, config, store, rid):
            self.rid = rid

        async def run(self):
            if self.rid == first:
                started.set()
                await asyncio.Event().wait()
            store.update(self.rid, status="complete")
            finished.set()

    monkeypatch.setattr(api, "store", store)
    monkeypatch.setattr(module, "Pipeline", Job)
    task = asyncio.create_task(api.worker())
    try:
        await asyncio.wait_for(started.wait(), 2)
        await api.cancel(first)
        await asyncio.wait_for(finished.wait(), 2)
        assert store.get(first)["status"] == "cancelled"
        assert store.get(second)["status"] == "complete"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_cancellation_during_export_cannot_publish_complete(monkeypatch, tmp_path, bundle):
    from research_app import exporters
    from research_app import pipeline as module

    class Runtime:
        def __init__(self, *args):
            pass

    monkeypatch.setattr(module, "AgentRuntime", Runtime)
    store = Store(tmp_path)
    bundle.research = ResearchAssessment(status="partial", text="Reviewed fixture")
    rid = store.create("export")
    store.update(rid, status="running")
    job = Pipeline(Settings(tmp_path, "model", "token", "https://example.com"), store, rid)
    job.write("bundle.json", bundle.model_dump(mode="json"))
    monkeypatch.setattr(exporters, "export_all", lambda *args: store.update(rid, status="cancelled"))
    with pytest.raises(module.CancelledRun):
        await job.render({})
    assert store.get(rid)["status"] == "cancelled"
    assert store.get(rid)["bundle_path"] is None
