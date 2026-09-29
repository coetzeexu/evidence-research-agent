import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain.agents.middleware.types import ModelResponse
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from research_app.tool_protocol import (
    StructuredJSONMiddleware,
    ToolProtocolMiddleware,
    repair_invalid_tool_results,
)


def invalid_message(valid=False):
    return AIMessage(
        content="",
        tool_calls=[{"name": "lookup", "id": "valid", "args": {"query": "NVDA"}}] if valid else [],
        invalid_tool_calls=[{"name": "lookup", "id": "bad", "args": '{"query":', "error": "JSON"}],
    )


def test_repairs_mixed_checkpoint_block_in_place_without_fabricating_valid_results():
    ai = invalid_message(valid=True)
    valid = ToolMessage(content="real evidence", tool_call_id="valid")
    followup = HumanMessage(content="Summarize")
    repaired = repair_invalid_tool_results([ai, valid, followup])
    assert repaired[1] is valid
    assert repaired[2].tool_call_id == "bad"
    assert repaired[2].status == "error"
    assert "not executed" in repaired[2].content
    assert repaired[3] is followup
    assert repair_invalid_tool_results(repaired) == repaired
    # Do not manufacture responses to otherwise valid pending tool calls.
    assert [m.tool_call_id for m in repair_invalid_tool_results([ai]) if isinstance(m, ToolMessage)] == [
        "bad"
    ]


class ProtocolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        pending = set()
        for message in messages:
            if isinstance(message, AIMessage):
                assert not pending, "Previous tool block was incomplete"
                pending = {c["id"] for c in message.tool_calls + message.invalid_tool_calls}
            elif isinstance(message, ToolMessage):
                pending.remove(message.tool_call_id)
        assert not pending, "Provider received an incomplete tool block"
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


async def test_invalid_only_call_retries_without_executing_and_can_recover():
    executed = []

    @tool
    def lookup(query: str) -> str:
        """Look up a public instrument."""
        executed.append(query)
        return "NVDA"

    model = ProtocolModel(
        responses=[
            invalid_message(),
            AIMessage(
                content="", tool_calls=[{"name": "lookup", "id": "corrected", "args": {"query": "NVDA"}}]
            ),
            AIMessage(content="Research can continue"),
        ]
    )
    agent = create_agent(
        model,
        tools=[lookup],
        middleware=[ToolProtocolMiddleware(), ModelCallLimitMiddleware(run_limit=4, exit_behavior="error")],
    )
    result = await agent.ainvoke({"messages": [HumanMessage(content="Research NVDA")]})
    assert result["messages"][-1].content == "Research can continue"
    assert executed == ["NVDA"]


def test_mixed_parallel_calls_receive_all_responses_before_the_next_model_request():
    @tool
    def lookup(query: str) -> str:
        """Look up a public instrument."""
        return query

    agent = create_agent(
        ProtocolModel(responses=[invalid_message(valid=True), AIMessage(content="done")]),
        tools=[lookup],
        middleware=[ToolProtocolMiddleware()],
    )
    result = agent.invoke({"messages": [HumanMessage(content="Research NVDA")]})
    assert result["messages"][-1].content == "done"


def test_named_output_function_preserves_regular_tool_policy():
    from research_app.agents import ReviewResult, StructuredChatOpenAI

    model = StructuredChatOpenAI(model="fixture", api_key="test-token")
    assert model.bind_tools([ReviewResult], tool_choice="any").kwargs["tool_choice"] == "required"
    structured = model.model_copy(update={"output_tool_name": "ReviewResult"})
    assert structured.bind_tools([ReviewResult], tool_choice="any").kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "ReviewResult"},
    }


@pytest.mark.parametrize(
    "body",
    [
        '{"passed":true,"passed":false,"summary":"duplicate"}',
        'Explanation {"passed":true,"summary":"substring"}',
        '{"passed":true,"summary":"extra","allow_secret":true}',
        '{"passed":true}',
    ],
)
def test_json_transport_rejects_ambiguous_or_invalid_output(body):
    from research_app.agents import ReviewResult

    response = ModelResponse(result=[AIMessage(content=body)])
    assert StructuredJSONMiddleware(ReviewResult).adapt(response).structured_response is None


async def test_json_transport_converges_in_sdk_without_discarding_critical():
    from research_app.agents import ReviewResult

    body = '{"passed":false,"summary":"failed","findings":[{"object_id":"e","severity":"critical","issue":"wrong date","repair":"check original"}]}'
    agent = create_agent(
        ProtocolModel(responses=[AIMessage(content=body)]),
        tools=[],
        response_format=ToolStrategy(ReviewResult),
        middleware=[
            StructuredJSONMiddleware(ReviewResult),
            ModelCallLimitMiddleware(run_limit=1, exit_behavior="error"),
        ],
    )
    result = await agent.ainvoke({"messages": [HumanMessage(content="Review")]})
    assert not result["structured_response"].passed
    assert result["structured_response"].findings[0].severity == "critical"
