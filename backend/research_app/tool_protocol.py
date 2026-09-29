"""Validate structured responses and preserve complete provider tool-message blocks."""

import json
import re

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, ToolMessage


class StructuredJSONMiddleware(AgentMiddleware):
    """Accept a whole schema-valid JSON response when a gateway ignores tool_choice.

    This is transport adaptation, not a verdict. No Markdown interpretation, JSON
    substring extraction, generated fields, or relaxation of schema validation.
    """

    def __init__(self, schema):
        self.schema = schema

    @staticmethod
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def adapt(self, response):
        if response.structured_response is not None or not response.result:
            return response
        message = response.result[-1]
        if (
            not isinstance(message, AIMessage)
            or message.tool_calls
            or message.invalid_tool_calls
            or not isinstance(message.content, str)
        ):
            return response
        body = message.content.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*\n(.*)\n```", body, re.S)
        if fenced:
            body = fenced[1].strip()
        try:
            value = json.loads(body, object_pairs_hook=self.unique_object)
            response.structured_response = self.schema.model_validate(value)
        except (ValueError, TypeError):
            pass
        return response

    async def awrap_model_call(self, request, handler):
        return self.adapt(await handler(request))

    def wrap_model_call(self, request, handler):
        return self.adapt(handler(request))


def repair_invalid_tool_results(messages):
    """Reply with an explicit error for every unexecuted, invalid JSON tool call.

    LangChain preserves invalid_tool_calls on the assistant message sent back to
    OpenAI-compatible providers, but ToolNode only executes parsed tool_calls.
    Responses must be inserted in the same assistant/tool block, including when
    that block came from an earlier checkpoint. Valid calls are never synthesized.
    """
    repaired = []
    index = 0
    while index < len(messages):
        message = messages[index]
        repaired.append(message)
        index += 1
        if not isinstance(message, AIMessage) or not message.invalid_tool_calls:
            continue
        answered = set()
        while index < len(messages) and isinstance(messages[index], ToolMessage):
            answered.add(messages[index].tool_call_id)
            repaired.append(messages[index])
            index += 1
        for call in message.invalid_tool_calls:
            if call.get("id") and call["id"] not in answered:
                repaired.append(
                    ToolMessage(
                        content="Tool not executed: arguments were not valid JSON. "
                        "Retry this call with a valid JSON object matching the tool schema.",
                        tool_call_id=call["id"],
                        name=call.get("name"),
                        status="error",
                    )
                )
                answered.add(call["id"])
    return repaired


class ToolProtocolMiddleware(AgentMiddleware):
    def wrap_model_call(self, request, handler):
        return handler(request.override(messages=repair_invalid_tool_results(request.messages)))

    async def awrap_model_call(self, request, handler):
        return await handler(request.override(messages=repair_invalid_tool_results(request.messages)))

    @hook_config(can_jump_to=["model"])
    def after_model(self, state, runtime):
        message = state["messages"][-1]
        if isinstance(message, AIMessage) and message.invalid_tool_calls and not message.tool_calls:
            # With no parsed calls, the default agent edge would silently end.
            # Retry through the normal model-call budget instead.
            return {"jump_to": "model"}
        return None

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime):
        return self.after_model(state, runtime)
