import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import cached_property
from typing import Literal

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .budget import BudgetMiddleware, ExecutionBudget
from .config import PROJECT_ROOT, Settings
from .data_providers import load_providers
from .domain import EventRecord, ResearchBundle, ResearchSpec, SourceRecord, digest
from .progress import SafeTrace, public_text
from .research_contract import ResearchQuestion
from .storage import Store
from .tool_protocol import StructuredJSONMiddleware, ToolProtocolMiddleware


class ParsedRequest(BaseModel):
    needs_clarification: bool = False
    question: str = ""
    spec: ResearchSpec | None = None
    questions: list[ResearchQuestion] = Field(
        default_factory=list,
        max_length=4,
        description="用户特有的额外研究问题；标准行情/归因/避险/通胀/配置问题由方法契约建立，避免重复",
    )


class ResearchResult(BaseModel):
    events: list[EventRecord] = Field(default_factory=list, max_length=18)
    gaps: list[str] = Field(
        default_factory=list, description="仅事件、资讯事实与原文来源的缺口；不是行情或宏观采集状态"
    )


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_id: str
    severity: Literal["critical", "warning"]
    issue: str
    repair: str


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passed: bool
    findings: list[Finding] = Field(default_factory=list)
    summary: str


class StructuredChatOpenAI(ChatOpenAI):
    """Use a named output function for tool-free stages on compatible providers.

    Some endpoints ignore tool_choice=required and emit a Markdown table instead.
    A named function keeps validation in the SDK, without parsing or approving prose.
    Normal investigation tools retain the SDK's original tool-choice policy.
    """

    output_tool_name: str = ""

    def bind_tools(self, tools, **kwargs):
        if self.output_tool_name:
            kwargs["tool_choice"] = {
                "type": "function",
                "function": {"name": self.output_tool_name},
            }
        return super().bind_tools(tools, **kwargs)


def llm(config: Settings):
    if not config.model_ready:
        raise ValueError("请在服务端 .env 配置 LLM_MODEL、LLM_BASE_URL、LLM_API_KEY")
    options = {}
    if config.platform:
        options["default_headers"] = {"X-PLATFORM": config.platform}
    if "deepseek.com" in config.base_url:
        options["extra_body"] = {"thinking": {"type": "disabled"}}
    if config.vllm_thinking is not None:
        options["extra_body"] = {"chat_template_kwargs": {"enable_thinking": config.vllm_thinking}}
    return StructuredChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=0,
        streaming=True,
        max_tokens=6000,
        timeout=90,
        max_retries=1,
        **options,
    )


def prompt(name: str) -> str:
    return (PROJECT_ROOT / "prompts" / f"{name}.md").read_text()


def require_structured(result: dict, schema: type[BaseModel], stage: str):
    value = result.get("structured_response")
    if value is None:
        raise ValueError(f"{stage}未返回结构化结果，可能达到模型输出限制；保留检查点，不能视为核验通过")
    return schema.model_validate(value)


def review_notes(messages):
    """A tool-free phase receives data, never historical callable tool messages."""
    return [
        {"role": message.type, "text": public_text(message.content)}
        for message in messages
        if getattr(message, "type", "") in {"ai", "tool"} and public_text(message.content)
    ]


NumericUnit = Literal["number", "percent", "bps", "million", "billion", "万", "亿"]


def compare_units(left: float, left_unit: NumericUnit, right: float, right_unit: NumericUnit) -> dict:
    scales = {
        "number": "1",
        "percent": ".01",
        "bps": ".0001",
        "million": "1000000",
        "billion": "1000000000",
        "万": "10000",
        "亿": "100000000",
    }
    a = Decimal(str(left)) * Decimal(scales[left_unit])
    b = Decimal(str(right)) * Decimal(scales[right_unit])
    # Distinguish display precision from exact equality without hiding material differences.
    quantum_a = Decimal(1).scaleb(Decimal(str(left)).as_tuple().exponent) * Decimal(scales[left_unit])
    quantum_b = Decimal(1).scaleb(Decimal(str(right)).as_tuple().exponent) * Decimal(scales[right_unit])
    return {
        "left_base_units": str(a),
        "right_base_units": str(b),
        "equal": a == b,
        "display_compatible": abs(a - b) <= max(quantum_a, quantum_b) / 2,
        "note": "display_compatible 仅表示按所给数字精度舍入相容，不表示严格相等",
    }


def same_instant(left: str | None, right: str | None) -> bool:
    try:
        a = datetime.fromisoformat((left or "").replace("Z", "+00:00"))
        b = datetime.fromisoformat((right or "").replace("Z", "+00:00"))
        return a.tzinfo is not None and b.tzinfo is not None and a == b
    except ValueError:
        return False


def normalize_event_timestamp(event: EventRecord):
    """A retrospective article's metadata is not the original event's release time."""
    event.reported_at = event.reported_at or event.published_at
    if event.public_disclosure_at:
        try:
            stamp = datetime.fromisoformat(event.public_disclosure_at.replace("Z", "+00:00"))
            event.date = stamp.date()
            event.published_at = event.public_disclosure_at if stamp.tzinfo else None
            event.time_precision = "timestamp" if stamp.tzinfo else "date"
            # Historical sources can establish an original public announcement, if explicit.
            event.timing_basis = "announcement"
            return
        except ValueError:
            event.public_disclosure_at = None
    if event.timing_basis == "retrospective":
        event.published_at = None
        event.time_precision = "date"
        event.uncertainty += " 事后报道按原文支持的事件日期展示，不代表当时已公开或可交易的信号。"
        return
    if not event.published_at:
        return
    try:
        published = datetime.fromisoformat(event.published_at.replace("Z", "+00:00"))
        if abs((published.date() - event.date).days) > 1:
            event.published_at = None
            event.time_precision = "date"
            event.uncertainty += " 来源为事后报道，其发布时间不能替代事件公开时刻；按已核实事件日期近似对齐。"
    except ValueError:
        event.published_at = None
        event.time_precision = "date"


def research_targets(spec: ResearchSpec, previous: ResearchResult) -> list[dict]:
    targets = [
        {"kind": "required_event", "query": r}
        for r in spec.required_events
        if not any(r in e.satisfies for e in previous.events)
    ]
    if spec.event_scope == "broad" and spec.intent in {"event_study", "combined"}:
        # Put the latest unrepresented year first rather than spending the entire
        # budget repeatedly collecting well-known historical announcements.
        for year in range(spec.end.year, spec.start.year - 1, -1):
            start, end = max(spec.start, date(year, 1, 1)), min(spec.end, date(year, 12, 31))
            if (end - start).days >= 180 and not any(start <= e.date <= end for e in previous.events):
                targets.append({"kind": "period_gap", "start": str(start), "end": str(end)})
    return targets


def has_date_evidence(event: EventRecord, sources: dict[str, SourceRecord], texts: dict[str, str]) -> bool:
    """Reject missing/invented date evidence before asking the reviewer to judge its meaning."""
    source = sources.get(event.date_source_id)
    if source is None or source.id not in event.source_ids or source.status != "retrieved":
        return False
    same_publication = (source.published_at or "")[:10] == str(event.date)
    if event.date_quote:
        quote = " ".join(event.date_quote.split())
        body = " ".join(texts.get(source.id, "").split())
        if len(quote) < 8 or quote not in body:
            return False
        y, m, d = event.date.year, event.date.month, event.date.day
        month = f"(?:{event.date.strftime('%B')}|{event.date.strftime('%b')}\\.?)"
        patterns = [
            rf"(?<!\d){y}[-/.年]\s*0?{m}[-/.月]\s*0?{d}(?:日|\b)",
            rf"\b{month}\s+0?{d}(?:st|nd|rd|th)?[,\s]+{y}\b",
            rf"\b0?{d}(?:st|nd|rd|th)?\s+{month}[,\s]+{y}\b",
            rf"\b0?{m}/0?{d}/{y}\b",
        ]
        return same_publication or any(re.search(pattern, quote, re.I) for pattern in patterns)
    return same_publication


class AgentRuntime:
    @cached_property
    def providers(self):
        return load_providers(self.config)

    def __init__(self, config: Settings, store: Store, run_id: str):
        self.config, self.store, self.run_id = config, store, run_id
        self.model = llm(config)
        self.budget = ExecutionBudget(store, run_id)
        self.prompts = {
            name: prompt(name)
            for name in [
                "planner",
                "researcher",
                "extractor",
                "reviewer",
                "review-format",
                "synthesis",
                "text-reviewer",
                "question-review",
                "numeric-review",
                "meaning-review",
                "text-repair",
            ]
        }
        self.store.emit(
            self.run_id,
            "configuration",
            "固定本次 Prompt 版本",
            prompt_hashes={k: digest(v) for k, v in self.prompts.items()},
            requested_model=config.model,
            platform=config.platform,
        )
        self.sources: dict[str, SourceRecord] = {}
        self.texts: dict[str, str] = {}
        self.coverage: list[dict] = []
        self.search_count = 0
        self.read_count = 0
        self.failed_reads: dict[str, int] = {}
        self.root = store.run_dir(run_id)
        saved = self.root / "research-evidence.json"
        if saved.exists():
            data = json.loads(saved.read_text())
            self.sources = {k: SourceRecord.model_validate(v) for k, v in data["sources"].items()}
            self.texts = data["texts"]
            self.coverage = data["coverage"]
            self.search_count = data.get("search_count", len(self.coverage))
            self.read_count = data.get("read_count", len(self.sources))
            self.failed_reads = data.get("failed_reads", {})

    async def structured(self, name, schema, content, *, budget=None, limit=3):
        active_budget = budget or self.budget
        runtime = self

        class Diagnostics(SafeTrace):
            def on_llm_end(self, response, *, run_id, **kwargs):
                super().on_llm_end(response, run_id=run_id, **kwargs)
                message = next((getattr(g[0], "message", None) for g in response.generations if g), None)
                errors = []
                for call in getattr(message, "tool_calls", []):
                    if call["name"] == schema.__name__:
                        try:
                            schema.model_validate(call["args"])
                        except ValidationError as exc:
                            errors.extend(exc.errors(include_input=False, include_url=False))
                runtime.store.save_json(
                    runtime.root / f"structure-{run_id}.json",
                    {
                        "stage": name,
                        "schema": schema.__name__,
                        "validation_errors": errors,
                        "invalid_arguments": [
                            call["args"]
                            for call in getattr(message, "tool_calls", [])
                            if errors and call["name"] == schema.__name__
                        ],
                        "invalid_json_calls": len(getattr(message, "invalid_tool_calls", [])),
                        "tool_names": [c["name"] for c in getattr(message, "tool_calls", [])],
                        "public_response": public_text(getattr(message, "content", ""))[:2000],
                        "finish_reason": (getattr(message, "response_metadata", {}) or {}).get(
                            "finish_reason"
                        ),
                    },
                )

        agent = create_agent(
            self.model.model_copy(update={"max_tokens": 12000, "output_tool_name": schema.__name__}),
            checkpointer=False,
            tools=[],
            system_prompt=self.prompts[name]
            + f"\n输出协议：调用 {schema.__name__} 函数提交。不要输出 Markdown 表格或说明。"
            "若服务只能返回文本，则整个响应必须是一个符合该函数模式的 JSON 对象，不能带其他文字。",
            response_format=ToolStrategy(schema),
            middleware=[
                BudgetMiddleware(active_budget),
                StructuredJSONMiddleware(schema),
                ToolProtocolMiddleware(),
                ModelCallLimitMiddleware(run_limit=limit, exit_behavior="error"),
            ],
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": json.dumps(content, ensure_ascii=False)}]},
            {"recursion_limit": 20, "callbacks": [Diagnostics(self.store, self.run_id, name)]},
        )
        return require_structured(result, schema, name)

    def persist(self):
        self.store.save_json(
            self.root / "research-evidence.json",
            {
                "sources": {k: v.model_dump() for k, v in self.sources.items()},
                "texts": self.texts,
                "coverage": self.coverage,
                "search_count": self.search_count,
                "read_count": self.read_count,
                "failed_reads": self.failed_reads,
            },
        )

    def skill_tool(self):
        @tool
        def load_skill(
            name: Literal["event-study", "asset-comparison", "evidence-review", "report-authoring"],
        ) -> str:
            """Load the versioned research method required for this task."""
            text = (PROJECT_ROOT / "skills" / name / "SKILL.md").read_text()
            self.store.emit(
                self.run_id, "skill", f"加载方法 · {name}", version="2026.09.4", content_hash=digest(text)
            )
            return text

        return load_skill

    async def parse(
        self, request: str, previous: dict | None = None, clarification: list[dict] | None = None
    ) -> ParsedRequest:
        @tool
        async def lookup_instrument(query: str) -> str:
            """Resolve an asset/company name to provider symbols and instrument types."""
            self.store.emit(self.run_id, "tool", "查询资产身份", query=query[:150])
            try:
                return json.dumps(await self.providers.market.lookup(query), ensure_ascii=False)
            except Exception:
                return "资产查询暂不可用。仅使用可明确识别的常见代码；存在歧义时请求澄清。"

        agent = create_agent(
            self.model,
            checkpointer=False,
            tools=[lookup_instrument],
            system_prompt=self.prompts["planner"],
            response_format=ToolStrategy(ParsedRequest),
            middleware=[
                BudgetMiddleware(self.budget),
                ToolProtocolMiddleware(),
                ModelCallLimitMiddleware(run_limit=5, exit_behavior="error"),
            ],
        )
        today = datetime.now(timezone.utc).date()
        content = json.dumps(
            {
                "request": request,
                "today": str(today),
                "default_start": str(today.replace(year=today.year - 5, day=min(today.day, 28))),
                "previous_spec": previous,
                "clarification_context": clarification or [],
            },
            ensure_ascii=False,
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": content}]},
            {"recursion_limit": 40, "callbacks": [SafeTrace(self.store, self.run_id, "主管")]},
        )
        return require_structured(result, ParsedRequest, "任务解析")

    async def research(
        self, spec: ResearchSpec, changes: list[dict], repair: str = "", data_inventory: dict | None = None
    ) -> ResearchResult:
        # Initial retrieval reserves capacity for two targeted repair rounds. Counters persist
        # across process restarts; repair grants never reset the global budget.
        round_index = 0
        if repair:
            saved = self.root / "repair-budget.json"
            grants = json.loads(saved.read_text()) if saved.exists() else []
            if repair not in grants and len(grants) < 2:
                grants.append(repair)
                self.store.save_json(saved, grants)
            round_index = len(grants)
        search_limit, read_limit = 18 + round_index * 8, 30 + round_index * 10
        previous_path = self.root / "events.json"
        previous = (
            ResearchResult.model_validate_json(previous_path.read_text())
            if repair and previous_path.exists()
            else ResearchResult()
        )
        catalog = json.loads((PROJECT_ROOT / "resources/source_catalog.json").read_text())
        question_path = self.root / "questions.json"
        questions = json.loads(question_path.read_text()) if question_path.exists() else []
        question_ids = {q["id"] for q in questions}

        @tool
        async def record_question_progress(
            question_id: str, source_ids: list[str], gap: str = "", next_action: str = ""
        ) -> str:
            """Record evidence collected and the next investigation step for a research question. This is not final verification."""
            if question_id not in question_ids or any(s not in self.sources for s in source_ids):
                return "问题或原文 ID 不存在，不能记录为已取得证据"
            path = self.root / "question-ledger.json"
            ledger = json.loads(path.read_text()) if path.exists() else []
            ledger.append(
                {
                    "question_id": question_id,
                    "source_ids": source_ids,
                    "gap": gap[:1000],
                    "next_action": next_action[:1000],
                }
            )
            self.store.save_json(path, ledger)
            self.store.emit(
                self.run_id,
                "question_progress",
                "研究问题调查进展已记录",
                question_id=question_id,
                sources=len(source_ids),
                has_gap=bool(gap),
            )
            return "调查进展已保存；结论仍须独立核验"

        @tool
        def source_directory(query: str) -> str:
            """Discover public source locators for common research topics. Hints contain no event facts; read and verify them."""
            matches = [r for r in catalog if any(k.lower() in query.lower() for k in r["keywords"])]
            self.store.emit(self.run_id, "tool", "查询公开来源目录", query=query, matches=len(matches))
            return json.dumps({"status": "discovery_only", "entries": matches}, ensure_ascii=False)

        @tool
        async def search_public(
            query: str,
            start: str,
            end: str,
            provider: str = "web",
            change_id: str = "",
            question_id: str = "",
        ) -> str:
            """Search public sources. ISO start/end dates. For a targeted move, pass its change_id. Leads are not evidence."""
            if provider not in self.providers.news:
                return json.dumps(
                    {"error": "未注册的资讯数据源", "available": list(self.providers.news)},
                    ensure_ascii=False,
                )
            failures = sum(c.get("provider") == "web" and c.get("status") == "failed" for c in self.coverage)
            if provider == "web" and failures >= 2:
                return "网页搜索已累计失败两次，本次停止重复请求且不扣预算。改用 hn 短关键词与指定时间窗，或读取来源目录中的官方公告。"
            if question_ids and question_id not in question_ids:
                return "请为这次查询指定 research_questions 中的 question_id，说明要解决哪个问题"
            duplicate = next(
                (
                    c
                    for c in self.coverage
                    if c.get("query", "").strip().lower() == query.strip().lower()
                    and c.get("provider") == provider
                    and c.get("start") == start
                    and c.get("end") == end
                    and c.get("status") == "success"
                ),
                None,
            )
            if duplicate:
                return json.dumps(
                    {"cached": True, "results": duplicate.get("results", duplicate.get("urls", []))},
                    ensure_ascii=False,
                )
            if self.search_count >= search_limit or not self.budget.can_investigate:
                return "检索预算已用完。请使用已读证据并明确剩余缺口。"
            self.search_count += 1
            self.persist()
            self.store.emit(self.run_id, "tool", "检索公开来源", query=query[:250], provider=provider)
            try:
                begin, finish = date.fromisoformat(start), date.fromisoformat(end)
                if begin < spec.start - timedelta(days=30) or finish > spec.end + timedelta(days=30):
                    return "检索区间超出本次研究范围。"
                items = await self.providers.news[provider].search(query, begin, finish)
                record = {
                    "query": query,
                    "provider": provider,
                    "start": start,
                    "end": end,
                    "hits": len(items),
                    "status": "success",
                    "urls": [v["url"] for v in items],
                    "results": items,
                    "change_id": change_id if any(c["id"] == change_id for c in changes) else "",
                    "question_id": question_id,
                }
                self.coverage.append(record)
                self.store.emit(
                    self.run_id,
                    "search_results",
                    "发现公开来源线索",
                    query=query[:250],
                    sources=[
                        {
                            "id": item["url"],
                            "url": item["url"],
                            "title": item.get("title", item["url"]),
                            "status": "candidate",
                        }
                        for item in items[:8]
                    ],
                )
                self.persist()
                return json.dumps(items, ensure_ascii=False)
            except Exception as exc:
                self.coverage.append(
                    {
                        "query": query,
                        "provider": provider,
                        "start": start,
                        "end": end,
                        "hits": 0,
                        "status": "failed",
                        "error": type(exc).__name__,
                    }
                )
                self.persist()
                return "检索失败；尝试其他免费来源或记录覆盖缺口。"

        @tool
        async def read_public_source(url: str, provider: str = "web") -> str:
            """Read a public primary source, returning a stable source_id, publication metadata and untrusted text."""
            if provider not in self.providers.news:
                return json.dumps(
                    {"error": "未注册的资讯数据源", "available": list(self.providers.news)},
                    ensure_ascii=False,
                )
            for source_id, source in self.sources.items():
                if source.url == url:
                    self.store.emit(
                        self.run_id,
                        "source",
                        "已读取保存的来源",
                        source={
                            "id": source.id,
                            "title": source.title,
                            "url": source.url,
                            "publisher": source.publisher,
                            "status": source.status,
                        },
                    )
                    return json.dumps(
                        {"source": source.model_dump(), "untrusted_text": self.texts[source_id]},
                        ensure_ascii=False,
                    )
            alternatives = [
                u
                for entry in catalog
                if url in entry["urls"]
                for u in entry["urls"]
                if u != url and not self.failed_reads.get(u)
            ]
            if self.failed_reads.get(url, 0) >= 2:
                return json.dumps(
                    {
                        "status": "unavailable",
                        "reason": "本页已读取失败两次，请改用其他来源，不再扣预算",
                        "alternative_locators": alternatives,
                    },
                    ensure_ascii=False,
                )
            if self.read_count >= read_limit or not self.budget.can_investigate:
                return "原文读取预算已用完。"
            self.read_count += 1
            self.persist()
            self.store.emit(self.run_id, "tool", "读取与保存原始证据", url=url[:500])
            try:
                source, text = await self.providers.news[provider].read(url)
                self.sources[source.id], self.texts[source.id] = source, text
                self.store.emit(
                    self.run_id,
                    "source",
                    "原始来源已读取",
                    source={
                        "id": source.id,
                        "title": source.title,
                        "url": source.url,
                        "publisher": source.publisher,
                        "status": source.status,
                    },
                )
                self.persist()
                return json.dumps(
                    {
                        "source": source.model_dump(),
                        "untrusted_text": text,
                        "date_notice": "页面无发布日期元数据；若正文也没有明确事件日期，须换来源补证，不能使用 URL 或讨论时间"
                        if not source.published_at
                        else "",
                        "alternative_locators": alternatives if not source.published_at else [],
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:
                self.failed_reads[url] = self.failed_reads.get(url, 0) + 1
                self.persist()
                self.store.emit(
                    self.run_id, "tool_failure", "原始来源读取失败", url=url[:500], error=type(exc).__name__
                )
                return json.dumps(
                    {
                        "status": "unavailable",
                        "url": url,
                        "error": type(exc).__name__,
                        "instruction": "不能将未读取的页面列为已核验证据",
                        "alternative_locators": alternatives,
                    }
                )

        # Sub-agent has a clean context and a limited tool set for retrieval only.
        subagent = create_agent(
            self.model,
            checkpointer=False,
            tools=[
                self.skill_tool(),
                source_directory,
                search_public,
                read_public_source,
                record_question_progress,
            ],
            system_prompt=self.prompts["researcher"],
            middleware=[
                BudgetMiddleware(self.budget),
                ToolProtocolMiddleware(),
                ModelCallLimitMiddleware(
                    run_limit=min(12, max(1, 42 - self.budget.model_calls)), exit_behavior="end"
                ),
            ],
        )
        self.store.emit(self.run_id, "agent", "研究子 Agent 开始", role="researcher")
        content = json.dumps(
            {
                "spec": spec.model_dump(mode="json"),
                "available_news_providers": list(self.providers.news),
                "research_questions": json.loads((self.root / "questions.json").read_text())
                if (self.root / "questions.json").exists()
                else [],
                "investigation_ledger": json.loads((self.root / "question-ledger.json").read_text())[-30:]
                if (self.root / "question-ledger.json").exists()
                else [],
                "data_inventory": data_inventory or {},
                "market_changes": sorted(changes, key=lambda c: c.get("strength", 0), reverse=True)[:18]
                if spec.intent in {"event_study", "combined"}
                else [],
                "repair_request": repair,
                "previous_events": previous.model_dump(mode="json"),
                "research_targets": research_targets(spec, previous),
                "remaining_budget": {
                    "searches": search_limit - self.search_count,
                    "reads": read_limit - self.read_count,
                },
                "already_read": [s.model_dump() for s in self.sources.values()],
                "discovery_only_source_hints": [
                    entry
                    for entry in catalog
                    if any(
                        k.lower() in " ".join([*spec.symbols, *spec.topics, *spec.required_events]).lower()
                        for k in entry["keywords"]
                    )
                ],
            },
            ensure_ascii=False,
        )
        try:
            async with asyncio.timeout(max(0.01, 660 - self.budget.used)):
                await subagent.ainvoke(
                    {"messages": [{"role": "user", "content": content}]},
                    {
                        "recursion_limit": 100,
                        "callbacks": [SafeTrace(self.store, self.run_id, "研究子 Agent")],
                    },
                )
        except TimeoutError:
            self.store.emit(self.run_id, "budget", "调查时限已到，使用已保存证据完成核验")
        if spec.intent == "asset_comparison" and not spec.required_events:
            # Product definitions and opposing research stay in the source snapshot
            # for final-text verification; this task has no event extraction target.
            return ResearchResult()
        # Retrieval has a hard SDK model-call budget. A separate, tool-free extraction phase
        # always converges on the evidence actually obtained, including partial coverage.
        extractor = create_agent(
            self.model,
            checkpointer=False,
            tools=[],
            system_prompt=self.prompts["extractor"],
            response_format=ToolStrategy(ResearchResult),
            middleware=[
                BudgetMiddleware(self.budget),
                ToolProtocolMiddleware(),
                ModelCallLimitMiddleware(
                    run_limit=min(4, max(1, 46 - self.budget.model_calls)), exit_behavior="error"
                ),
            ],
        )
        evidence = [
            {"source": s.model_dump(), "untrusted_text": self.texts.get(s.id, "")}
            for s in self.sources.values()
        ]
        result = await extractor.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "spec": spec.model_dump(mode="json"),
                                "data_inventory": data_inventory or {},
                                "evidence": evidence,
                                "coverage": self.coverage,
                                "repair_request": repair,
                                "previous_events": previous.model_dump(mode="json"),
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            },
            {"recursion_limit": 32, "callbacks": [SafeTrace(self.store, self.run_id, "证据提取")]},
        )
        output = require_structured(result, ResearchResult, "事件提取")
        verified = []
        for event in output.events:
            if event.public_disclosure_at:
                sid = event.disclosure_source_id
                source = self.sources.get(sid)
                text = self.texts.get(sid, "")
                quoted = len(event.disclosure_quote) >= 12 and event.disclosure_quote in text
                metadata = (
                    source
                    and source.published_at
                    and (
                        same_instant(source.published_at, event.public_disclosure_at)
                        or source.published_at == event.public_disclosure_at
                    )
                )
                if sid not in event.source_ids or not (quoted or metadata):
                    event.public_disclosure_at = None
                    event.uncertainty += " 信息公开时间缺少可定位证据，未采用。"
                else:
                    event.date_source_id = sid
                    event.date_quote = event.disclosure_quote
                    normalize_event_timestamp(event)
            if event.time_precision == "uncertain":
                output.gaps.append(f"候选事件 {event.title} 的发生日期未核实，未纳入事件标注")
                continue
            if not all(source_id in self.sources for source_id in event.source_ids):
                output.gaps.append(f"事件 {event.title} 的引用未读取，已排除")
                continue
            if not has_date_evidence(event, self.sources, self.texts):
                output.gaps.append(
                    f"候选事件 {event.title} 缺少可定位的日期原文或同日发布元数据，未纳入；需要补查日期证据"
                )
                continue
            if not set(event.symbols).intersection(spec.symbols):
                continue
            event.satisfies = [r for r in event.satisfies if r in spec.required_events]
            if spec.event_scope == "focused" and spec.required_events and not event.satisfies:
                output.gaps.append(f"候选事件 {event.title} 超出点名范围，未纳入")
                continue
            # Exact timestamps require supporting source metadata; date-level claims remain explicit.
            if (
                event.published_at
                and not event.public_disclosure_at
                and not any(
                    same_instant(self.sources[i].published_at, event.published_at) for i in event.source_ids
                )
            ):
                event.published_at = None
                event.time_precision = "date"
                event.uncertainty += " 未取得匹配的精确发布时刻，降级为日期对齐。"
            normalize_event_timestamp(event)
            verified.append(event)
        output.events = verified
        self.store.emit(
            self.run_id, "agent", "研究子 Agent 完成", events=len(verified), sources=len(self.sources)
        )
        return output

    async def review(self, bundle: ResearchBundle) -> ReviewResult:
        if bundle.spec.intent == "asset_comparison" and not bundle.events:
            return ReviewResult(
                passed=True,
                summary="没有待核验的事件；产品事实、研究判断与指标交给独立正文核验，不能据此发布正文。",
            )

        @tool
        def compare_numbers(
            left: float, left_unit: NumericUnit, right: float, right_unit: NumericUnit
        ) -> str:
            """Check numeric equivalence across percent, bps and English/Chinese magnitude units, without mental arithmetic."""
            result = compare_units(left, left_unit, right, right_unit)
            self.store.emit(self.run_id, "tool", "核验数值单位换算", **result)
            return json.dumps(result)

        @tool
        def inspect_evidence(source_id: str) -> str:
            """Inspect the saved original text and publication metadata for a known evidence ID."""
            self.store.emit(self.run_id, "tool", "核验原文证据", source_id=source_id)
            if source_id not in self.sources:
                return "引用不可用"
            return json.dumps(
                {
                    "source": self.sources[source_id].model_dump(),
                    "untrusted_text": self.texts.get(source_id, ""),
                },
                ensure_ascii=False,
            )

        reviewer = create_agent(
            self.model,
            checkpointer=False,
            tools=[self.skill_tool(), inspect_evidence, compare_numbers],
            system_prompt=self.prompts["reviewer"],
            middleware=[
                BudgetMiddleware(self.budget),
                ToolProtocolMiddleware(),
                ModelCallLimitMiddleware(
                    run_limit=min(5, max(1, 44 - self.budget.model_calls)), exit_behavior="end"
                ),
            ],
        )
        self.store.emit(self.run_id, "agent", "核验子 Agent 开始", role="reviewer")
        content = {
            "events": [e.model_dump(mode="json") for e in bundle.events],
            "annotations": bundle.annotations,
            "claims": [c.model_dump() for c in bundle.claims],
            "metrics": bundle.metrics,
            "spec": bundle.spec.model_dump(mode="json"),
            "datasets": {
                s: {
                    "id": d.id,
                    "price_basis": d.price_basis,
                    "last_complete_bar": d.bars[-1].date,
                    "calendar": d.instrument.calendar,
                }
                for s, d in bundle.datasets.items()
            },
            "definitions": "direction 与 rating 对应优先的 5 日相对基准收益，若 5 日不满则首个完整窗口。"
            "窗口长度是标的日线条数：加密资产为日历日，股票为交易日。基准用不晚于对应日线关闭时刻的最近收盘，最多陈旧 96 小时。"
            "start/end 是日线日期标签，真实收益窗口以 start_closed_at/end_closed_at UTC 时刻为准。BTC 日期为开盘日，其收盘在次日 00:00 UTC。"
            "同日同标的的多条事件共享市场窗口，不是独立统计样本，系统不对事件反应加总。"
            "rating 是确定性计算的反应幅度，与来源 confidence 是独立维度。区间终点是各标的最后完整日线，允许因日历不同而不同。",
            "warnings": bundle.warnings,
            "sources": [s.model_dump() for s in bundle.sources],
        }
        result = await reviewer.ainvoke(
            {"messages": [{"role": "user", "content": json.dumps(content, ensure_ascii=False)}]},
            {"recursion_limit": 90, "callbacks": [SafeTrace(self.store, self.run_id, "核验子 Agent")]},
        )
        review = await self.structured(
            "review-format",
            ReviewResult,
            {"context": content, "notes": review_notes(result["messages"])},
            limit=min(2, max(1, 46 - self.budget.model_calls)),
        )
        if any(f.severity == "critical" for f in review.findings) and self.budget.model_calls <= 42:
            # A fresh context adjudicates consequential findings against the original
            # evidence. Preserve both decisions for audit instead of silently removing
            # events because the first reviewer misread a unit or a date convention.
            disputed_ids = {f.object_id for f in review.findings if f.severity == "critical"}
            disputed_events = [e for e in bundle.events if e.id in disputed_ids]
            disputed_sources = {
                sid
                for e in disputed_events
                for sid in [*e.source_ids, e.date_source_id, e.disclosure_source_id]
                if sid
            }
            audit_path = self.root / "review-adjudications.json"
            audits = json.loads(audit_path.read_text()) if audit_path.exists() else []
            audit = {"initial": review.model_dump(), "status": "pending"}
            audits.append(audit)
            self.store.save_json(audit_path, audits)
            adjudication_prompt = (
                self.prompts["reviewer"]
                + "\n你是核验争议复核者，只核查 prior_review 已列出的具体缺陷，不重新核查整个研究。"
                "前一核验结果也是待验证主张。对照原文，保留成立的 critical；纠正误读并解释依据。"
                "只在缺陷涉及数值单位时调用 compare_numbers，一次批量提交所需比较，不检查无关数字。"
                "亿=100 million，billion=10亿。不能拿指引与预期两个不同指标相比较。"
                "缺少争议对象原文时保留原有缺陷，不能猜测已解决。"
            )
            adjudicator = create_agent(
                self.model,
                checkpointer=False,
                tools=[compare_numbers],
                system_prompt=adjudication_prompt,
                middleware=[
                    BudgetMiddleware(self.budget),
                    ToolProtocolMiddleware(),
                    ModelCallLimitMiddleware(run_limit=2, exit_behavior="end"),
                ],
            )
            try:
                disputed = {
                    "prior_review": review.model_dump(),
                    "spec": content["spec"],
                    "definitions": content["definitions"],
                    "events": [e.model_dump(mode="json") for e in disputed_events],
                    "annotations": [a for a in bundle.annotations if a["event_id"] in disputed_ids],
                    "claims": [c.model_dump() for c in bundle.claims if c.id in disputed_ids],
                    "disputed_evidence": [
                        {"source": self.sources[sid].model_dump(), "untrusted_text": self.texts.get(sid, "")}
                        for sid in disputed_sources
                        if sid in self.sources
                    ],
                }
                adjudicated = await adjudicator.ainvoke(
                    {"messages": [{"role": "user", "content": json.dumps(disputed, ensure_ascii=False)}]},
                    {
                        "recursion_limit": 16,
                        "callbacks": [SafeTrace(self.store, self.run_id, "核验争议复核")],
                    },
                )
                review = await self.structured(
                    "review-format",
                    ReviewResult,
                    {"context": disputed, "notes": review_notes(adjudicated["messages"])},
                    limit=2,
                )
                audit.update(status="reviewed", adjudicated=review.model_dump())
            except Exception as exc:
                # Optional dispute review cannot erase the initial defects or abort synthesis.
                audit.update(status="incomplete", error_type=type(exc).__name__)
            self.store.save_json(audit_path, audits)
            self.store.emit(self.run_id, "review_adjudication", "复核影响交付的核验争议", **audit)
        review.passed = not any(f.severity == "critical" for f in review.findings)
        return review

    async def explain(
        self,
        bundle: ResearchBundle,
        question: str,
        selected: str | None = None,
        history: list[dict] | None = None,
        on_chunk=None,
    ) -> str:
        from uuid import uuid4

        from .research_text import NarrativeService

        scope = f"chat-{uuid4().hex[:12]}"
        budget = ExecutionBudget(self.store, self.run_id, name=f"{scope}-budget", seconds=180)
        budget.start()
        ticker = asyncio.create_task(budget.heartbeat())
        questions = [
            ResearchQuestion(
                id="followup",
                question=question,
                acceptance="直接回答追问，数字与事实均有当前快照依据；新范围明确需另行研究。",
                kind="custom",
            )
        ]
        try:
            async with asyncio.timeout(budget.remaining):
                assessment = await NarrativeService(self, budget, scope).compose(
                    bundle, questions, question, history, selected
                )
            if not assessment.text:
                raise ValueError("未获得可发布的已核验回答，已保留核验记录")
            if on_chunk is not None:
                await on_chunk(assessment.text)
            return assessment.text
        finally:
            ticker.cancel()
            budget.stop()
