"""Persist public streaming output and tool lifecycles; never serialize model inputs/reasoning."""

import json

from langchain_core.callbacks import BaseCallbackHandler

from .storage import Store


def public_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
            and part.get("type") in {"text", "output_text"}
            and isinstance(part.get("text"), str)
        )
    return ""


TOOL_LABELS = {
    "lookup_instrument": "查询资产身份",
    "load_skill": "加载研究方法",
    "source_directory": "查询公开来源目录",
    "search_public": "检索公开来源",
    "read_public_source": "读取原始证据",
    "inspect_evidence": "核验原文证据",
    "compare_numbers": "核验数值单位",
    "record_question_progress": "记录问题调查进展",
}


class SafeTrace(BaseCallbackHandler):
    run_inline = True  # Preserve callback order, including concurrent tool call IDs.

    def __init__(self, store: Store, run_id: str, role: str):
        self.store, self.run_id, self.role = store, run_id, role
        self.tools: dict[str, str] = {}

    def emit(self, kind, label, call_id, **payload):
        self.store.emit(self.run_id, kind, label, role=self.role, call_id=str(call_id), **payload)

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        # Do not log messages, tool schemas, API options or provider-specific reasoning fields.
        self.emit("model_start", f"{self.role}正在处理", run_id)

    def on_llm_new_token(self, token, *, run_id, chunk=None, **kwargs):
        # Operational callbacks stream, but research/reviewer drafts must stay private.
        # Verified prose is released by the publication gate after review.
        return

    def on_llm_end(self, response, *, run_id, **kwargs):
        key = str(run_id)
        message = next((getattr(g[0], "message", None) for g in response.generations if g), None)
        metadata = getattr(message, "response_metadata", {}) or {}
        self.emit(
            "model",
            f"{self.role}完成一次模型调用",
            key,
            usage=getattr(message, "usage_metadata", None) or {},
            model=metadata.get("model_name", ""),
        )

    def on_llm_error(self, error, *, run_id, **kwargs):
        key = str(run_id)
        self.emit("model_error", "本次模型调用中断", key, error_type=type(error).__name__)

    def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, **kwargs):
        name = (serialized or {}).get("name", "")
        if name not in TOOL_LABELS:
            return
        key = str(run_id)
        self.tools[key] = name
        # Explicit, bounded public arguments only. Raw tool inputs/results can contain large
        # source documents and internal instructions and must not be copied into the UI.
        details = {
            k: str(v)[:500]
            for k, v in (inputs or {}).items()
            if k in {"query", "url", "provider", "source_id", "name"}
        }
        self.emit("tool_start", TOOL_LABELS[name], key, tool=name, **details)

    def on_tool_end(self, output, *, run_id, **kwargs):
        key = str(run_id)
        name = self.tools.pop(key, None)
        if not name:
            return
        content = getattr(output, "content", output)
        failed = getattr(output, "status", "") == "error"
        if isinstance(content, str):
            try:
                data = json.loads(content)
                failed |= isinstance(data, dict) and data.get("status") in {"unavailable", "failed"}
            except (ValueError, TypeError):
                failed |= content.startswith(("检索失败", "资产查询暂不可用", "引用不可用", "检索区间超出"))
                failed |= "预算已用完" in content[:80]
        self.emit("tool_error" if failed else "tool_end", TOOL_LABELS[name], key, tool=name)

    def on_tool_error(self, error, *, run_id, **kwargs):
        key = str(run_id)
        name = self.tools.pop(key, None)
        if name:
            self.emit("tool_error", TOOL_LABELS[name], key, tool=name, error_type=type(error).__name__)
