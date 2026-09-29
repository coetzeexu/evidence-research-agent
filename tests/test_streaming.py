import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import tool
from research_app.config import Settings
from research_app.progress import SafeTrace, public_text
from research_app.storage import Store


def test_public_trace_never_copies_reasoning_or_structured_tool_arguments(tmp_path):
    store = Store(tmp_path)
    rid = store.create("test")
    callback = SafeTrace(store, rid, "研究子 Agent")
    model_id = uuid4()
    callback.on_chat_model_start({}, [[{"content": "private prompt"}]], run_id=model_id)
    hidden = AIMessageChunk(
        content=[{"type": "reasoning", "reasoning": "private reasoning"}],
        additional_kwargs={"reasoning_content": "hidden"},
    )
    callback.on_llm_new_token("private reasoning", chunk=ChatGenerationChunk(message=hidden), run_id=model_id)
    for text in ["公开", "文本"]:
        callback.on_llm_new_token(
            text, chunk=ChatGenerationChunk(message=AIMessageChunk(content=text)), run_id=model_id
        )
    callback.on_llm_end(SimpleNamespace(generations=[]), run_id=model_id)
    events = store.events(rid)
    assert "".join(e["payload"].get("text", "") for e in events) == ""
    assert events[0]["kind"] == "model_start" and events[-1]["kind"] == "model"
    assert "private" not in json.dumps(events) and "hidden" not in json.dumps(events)
    assert (
        public_text([{"type": "text", "text": "hello"}, {"type": "reasoning", "text": "secret"}]) == "hello"
    )


async def test_real_langchain_stream_and_parallel_tool_callbacks_are_paired(tmp_path):
    store = Store(tmp_path)
    rid = store.create("test")
    callback = SafeTrace(store, rid, "研究子 Agent")
    model = FakeListChatModel(responses=["已经读取原文"])
    async for _ in model.astream("a", config={"callbacks": [callback]}):
        pass
    assert "".join(e["payload"].get("text", "") for e in store.events(rid)) == ""

    @tool
    async def read_public_source(url: str) -> str:
        """Read the test source."""
        return '{"status":"unavailable"}'

    await read_public_source.ainvoke({"url": "https://example.com"}, config={"callbacks": [callback]})
    events = store.events(rid)
    started = next(e for e in events if e["kind"] == "tool_start")
    ended = next(e for e in events if e["kind"] == "tool_error")
    assert started["payload"]["call_id"] == ended["payload"]["call_id"]
    assert started["payload"]["url"] == "https://example.com"


@pytest.mark.parametrize("failure", [False, True])
def test_chat_sse_streams_deltas_and_persists_success_or_partial_failure(
    monkeypatch, tmp_path, bundle, failure
):
    from research_app import agents, api

    store = Store(tmp_path)
    rid = store.create("chat")
    path = store.run_dir(rid) / "bundle.json"
    store.save_json(path, bundle.model_dump(mode="json"))
    store.update(rid, status="complete", bundle_path=str(path))
    monkeypatch.setattr(api, "store", store)
    monkeypatch.setattr(api, "config", Settings(tmp_path, "model", "private-key", "https://example.com"))

    class Runtime:
        def __init__(self, *args):
            pass

        async def explain(self, saved, question, selected, history=None, on_chunk=None):
            assert history == []
            await on_chunk("已经读取")
            if failure:
                raise RuntimeError("private-key")
            await on_chunk("来源 [source-1]。")
            return "已经读取来源 [source-1]。"

    monkeypatch.setattr(agents, "AgentRuntime", Runtime)
    response = TestClient(api.app).post(f"/api/runs/{rid}/chat", json={"message": "测试", "stream": True})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert response.text.startswith("event: accepted")
    history = store.chat_history(rid)
    assert history[0] == {"role": "user", "text": "测试"}
    assert rid not in api.active_chats
    if failure:
        assert "event: error" in response.text and "event: done" not in response.text
        assert "private-key" not in response.text
        assert len(history) == 1
        assert "event: delta" not in response.text
        assert "已经读取" not in response.text
    else:
        assert response.text.count("event: delta") == 1
        assert "event: done" in response.text
        assert history[1]["text"] == "已经读取来源 [source-1]。"
