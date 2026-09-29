import asyncio
import json
from contextlib import suppress
from datetime import timedelta
from pathlib import Path
from typing import TypedDict

from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from .agents import AgentRuntime, ResearchResult
from .analytics import build_bundle, detect_changes, validate_bundle
from .budget import ExecutionBudget
from .config import Settings
from .data_providers import DataProviders, load_providers
from .domain import MarketDataset, ResearchBundle, ResearchSpec, SourceRecord
from .quality import assess_quality, associate_changes
from .research_contract import ResearchQuestion
from .research_text import NarrativeService, research_questions
from .storage import Store


class RunState(TypedDict, total=False):
    run_id: str
    spec: dict
    repair_round: int
    repair: str
    review: dict
    reuse: bool
    needs_input: bool


class CancelledRun(Exception):
    pass


class Pipeline:
    def __init__(
        self,
        config: Settings,
        store: Store,
        run_id: str,
        export: bool | None = None,
        providers: DataProviders | None = None,
    ):
        self.config, self.store, self.run_id = config, store, run_id
        self.export = bool(store.get(run_id).get("export_reports", True)) if export is None else export
        self.root = store.run_dir(run_id)
        self.runtime = AgentRuntime(config, store, run_id)
        self.providers = (
            providers or getattr(self.runtime, "providers", None) or load_providers(config)
        ).validate()
        self.runtime.providers = self.providers
        self.budget = getattr(self.runtime, "budget", None) or ExecutionBudget(store, run_id)

    def check(self):
        if self.store.get(self.run_id)["status"] == "cancelled":
            raise CancelledRun()

    def read(self, name: str):
        return json.loads((self.root / name).read_text())

    def write(self, name: str, value):
        self.store.save_json(self.root / name, value)

    async def plan(self, state: RunState):
        self.check()
        self.store.emit(self.run_id, "step", "理解任务与解析资产", phase="plan")
        run = self.store.get(self.run_id)
        previous = self.store.get(run["parent_id"]) if run.get("parent_id") else None
        extra_questions = []
        if run["spec"]:
            spec = ResearchSpec.model_validate(run["spec"])
        else:
            previous_spec, clarification = self.store.clarification_context(run)
            parsed = await self.runtime.parse(run["prompt"], previous_spec, clarification=clarification)
            if parsed.needs_clarification or parsed.spec is None:
                self.store.update(
                    self.run_id, status="needs_input", error=parsed.question or "请明确资产与研究目标"
                )
                return {"needs_input": True}
            spec = parsed.spec
            extra_questions = [q.model_dump() for q in parsed.questions]
        self.store.update(self.run_id, title=spec.title, spec=spec.model_dump(mode="json"))
        reuse = False
        if previous and previous.get("bundle_path") and not run.get("refresh_requested"):
            keys = ["symbols", "start", "end", "topics", "benchmark", "required_events", "event_scope"]
            previous_spec = ResearchSpec.model_validate(previous["spec"]).model_dump(mode="json")
            reuse = all(previous_spec[key] == spec.model_dump(mode="json")[key] for key in keys)
            parent_dir = self.store.run_dir(previous["id"])
            required = ["collection.json", "events.json", "research-evidence.json"]
            reuse = reuse and all((parent_dir / name).exists() for name in required)
            if reuse:
                for filename in required:
                    if (parent_dir / filename).exists():
                        self.write(filename, json.loads((parent_dir / filename).read_text()))
                parent_bundle = ResearchBundle.model_validate_json(Path(previous["bundle_path"]).read_text())
                self.write("parent-review.json", {**parent_bundle.review, "inherited_from": parent_bundle.id})
                self.write(
                    "events.json",
                    {
                        "events": [e.model_dump(mode="json") for e in parent_bundle.events],
                        "gaps": parent_bundle.warnings,
                    },
                )
                self.runtime = AgentRuntime(self.config, self.store, self.run_id)
                self.runtime.providers = self.providers
                self.runtime.budget = self.budget
        questions = research_questions(spec, extra_questions, run["prompt"])
        self.write("questions.json", [q.model_dump() for q in questions])
        self.store.emit(
            self.run_id,
            "questions",
            "研究问题与完成标准已确定",
            questions=[q.model_dump() for q in questions],
        )
        self.store.emit(
            self.run_id,
            "plan",
            "研究计划已确定",
            symbols=spec.symbols,
            start=str(spec.start),
            end=str(spec.end),
            assumptions=spec.assumptions,
            reuse=reuse,
        )
        return {
            "spec": spec.model_dump(mode="json"),
            "repair_round": 0,
            "repair": "",
            "reuse": reuse,
            "needs_input": False,
        }

    async def collect(self, state: RunState):
        self.check()
        if state.get("reuse") and (self.root / "collection.json").exists():
            self.store.emit(self.run_id, "step", "复用相同区间的数据快照", phase="collect")
            return {}
        spec = ResearchSpec.model_validate(state["spec"])
        self.store.emit(self.run_id, "step", "获取完整日线与宏观数据", phase="collect")
        symbols = list(dict.fromkeys([*spec.symbols, spec.benchmark]))
        semaphore = asyncio.Semaphore(3)

        async def fetch(symbol):
            async with semaphore:
                data = await self.providers.market.history(
                    symbol,
                    spec.start - timedelta(days=400),
                    spec.end,
                    self.config.data_dir / "cache",
                    refresh=bool(self.store.get(self.run_id).get("refresh_requested")),
                )
                self.store.emit(
                    self.run_id,
                    "data",
                    f"{symbol} 行情已校验",
                    bars=len(data.bars),
                    through=data.bars[-1].date,
                    dataset_id=data.id,
                    source={
                        "id": data.id,
                        "url": data.source_url,
                        "title": f"{symbol} 行情快照",
                        "status": "retrieved",
                    },
                )
                return symbol, data

        pairs = await asyncio.gather(*(fetch(symbol) for symbol in symbols))
        datasets = dict(pairs)
        macro, sources, warnings = {}, [], []
        if len(spec.symbols) > 1:
            for series_id in ["CPIAUCNS", "DGS3MO"]:
                try:
                    data, source = await self.providers.macro.series(
                        series_id, spec.start - timedelta(days=400), spec.end
                    )
                    macro[series_id] = data
                    sources.append(source.model_dump())
                except Exception:
                    warnings.append(f"{series_id} 未获取；相关宏观指标不输出")
        self.write(
            "collection.json",
            {
                "datasets": {k: v.model_dump() for k, v in datasets.items()},
                "macro": macro,
                "sources": sources,
                "warnings": warnings,
            },
        )
        return {}

    async def research(self, state: RunState):
        self.check()
        if not self.budget.can_investigate:
            if not (self.root / "events.json").exists():
                self.write("events.json", {"events": [], "gaps": ["调查预算已用完，事件证据未取得"]})
            return {}
        if state.get("reuse") and not state.get("repair") and (self.root / "events.json").exists():
            self.store.emit(self.run_id, "step", "复用已核验事件与来源", phase="research")
            return {}
        spec = ResearchSpec.model_validate(state["spec"])
        collection = self.read("collection.json")
        changes = []
        for symbol in spec.symbols:
            ds = MarketDataset.model_validate(collection["datasets"][symbol])
            changes.extend(detect_changes(ds, spec.start, spec.end, maximum=10))
        self.store.emit(self.run_id, "step", "事件发现与原文核实", phase="research")
        inventory = {
            "datasets": {
                s: {
                    "id": d["id"],
                    "bars": len(d["bars"]),
                    "first": d["bars"][0]["date"],
                    "last": d["bars"][-1]["date"],
                    "source_url": d["source_url"],
                }
                for s, d in collection["datasets"].items()
            },
            "macro": {
                s: {"observations": len(rows), "source_id": f"fred-{s}"}
                for s, rows in collection["macro"].items()
            },
        }
        try:
            async with asyncio.timeout(max(0.01, 720 - self.budget.used)):
                result = await self.runtime.research(
                    spec, changes, state.get("repair", ""), data_inventory=inventory
                )
        except (TimeoutError, ModelCallLimitExceededError) as exc:
            result = (
                ResearchResult.model_validate(self.read("events.json"))
                if (self.root / "events.json").exists()
                else ResearchResult()
            )
            reason = "调查时限已到" if isinstance(exc, TimeoutError) else "本轮事件提取格式未收敛"
            result.gaps.append(f"{reason}，保留已提取事件和原文，进入正文核验")
            self.store.emit(self.run_id, "budget", result.gaps[-1], phase="research")
        self.write("events.json", result.model_dump(mode="json"))
        return {}

    async def analyze(self, state: RunState):
        self.check()
        self.store.emit(self.run_id, "step", "计算行情反应与研究指标", phase="analyze")
        spec = ResearchSpec.model_validate(state["spec"])
        collection = self.read("collection.json")
        events = ResearchResult.model_validate(self.read("events.json"))
        sources = {
            s.id: s
            for s in [
                *self.runtime.sources.values(),
                *(SourceRecord.model_validate(s) for s in collection["sources"]),
            ]
        }
        bundle = build_bundle(
            self.run_id,
            spec,
            {k: MarketDataset.model_validate(v) for k, v in collection["datasets"].items()},
            list(sources.values()),
            events.events,
            collection["macro"],
            self.runtime.coverage,
        )
        bundle.warnings.extend(collection["warnings"])
        bundle.warnings.extend(events.gaps)
        self.write("bundle.json", bundle.model_dump(mode="json"))
        return {}

    async def review(self, state: RunState):
        self.check()
        self.store.emit(self.run_id, "step", "复核引用、时间与计算", phase="review")
        bundle = ResearchBundle.model_validate(self.read("bundle.json"))
        deterministic = validate_bundle(bundle)
        if not deterministic["passed"]:
            raise ValueError("; ".join(deterministic["failures"]))
        if state.get("reuse") and not state.get("repair"):
            parent = self.read("parent-review.json")
            active_ids = {e.id for e in bundle.events} | {a["id"] for a in bundle.annotations}
            active_ids |= {s.id for s in bundle.sources} | {c.id for c in bundle.claims}
            findings = [f for f in parent.get("findings", []) if f["object_id"] in active_ids]
            review = {
                "passed": not any(f["severity"] == "critical" for f in findings),
                "findings": findings,
                "summary": "事件证据与未解决提示沿用父版本；已重新验证数值与引用。",
                "inherited_from": parent["inherited_from"],
            }
        elif self.budget.can_investigate:
            try:
                async with asyncio.timeout(max(0.01, 720 - self.budget.used)):
                    result = await self.runtime.review(bundle)
                    review = result.model_dump()
            except TimeoutError:
                review = {
                    "passed": False,
                    "findings": [],
                    "summary": "事件核验时限已到，保留原文进入最终正文核验",
                }
        else:
            review = {"passed": False, "findings": [], "summary": "调查预算已到，转入最终正文独立核验"}
        review["deterministic"] = deterministic
        bundle.review = review
        bundle.quality = assess_quality(bundle)
        self.write("bundle.json", bundle.model_dump(mode="json"))
        critical = [f for f in review["findings"] if f["severity"] == "critical"]
        # Hard budget: at most two retrieval repair rounds.
        actions = bundle.quality["repair_actions"]
        repair = (
            json.dumps({"critical": critical, "coverage_actions": actions}, ensure_ascii=False)
            if (critical or actions) and state.get("repair_round", 0) < 2 and self.budget.can_investigate
            else ""
        )
        self.store.emit(
            self.run_id,
            "quality",
            "研究要求覆盖检查",
            passed=bundle.quality["passed"],
            missing=len(actions),
            repair_round=state.get("repair_round", 0),
        )
        return {
            "review": review,
            "repair": repair,
            "repair_round": state.get("repair_round", 0) + (1 if repair else 0),
        }

    async def synthesize(self, state: RunState):
        self.check()
        bundle = ResearchBundle.model_validate(self.read("bundle.json"))
        critical = [f for f in bundle.review.get("findings", []) if f["severity"] == "critical"]
        if critical:
            rejected = {f["object_id"] for f in critical}
            rejected.update(a["event_id"] for a in bundle.annotations if a["id"] in rejected)
            for event in bundle.events:
                if any(source_id in rejected for source_id in event.source_ids):
                    rejected.add(event.id)
            bundle.events = [event for event in bundle.events if event.id not in rejected]
            bundle.annotations = [a for a in bundle.annotations if a["event_id"] not in rejected]
            valid_metric_ids = {a["metric_id"] for a in bundle.annotations}
            bundle.metrics = [
                m
                for m in bundle.metrics
                if not m["id"].startswith("event-window-") or m["id"] in valid_metric_ids
            ]
            for change in bundle.changes:
                change["event_ids"] = [i for i in change["event_ids"] if i not in rejected]
            bundle.claims = [c for c in bundle.claims if not set(c.evidence_ids).intersection(rejected)]
            bundle.warnings.append("部分证据问题在预算内未能修复，相关事件已移除；详见核验记录。")
        associate_changes(bundle.changes, bundle.annotations, bundle.events, bundle.datasets)
        bundle.quality = assess_quality(bundle)
        if not bundle.quality["passed"]:
            bundle.warnings.append("执行已结束，研究要求仍有缺口；详见需求覆盖清单，不将部分交付标为完整。")
        self.write("bundle.json", bundle.model_dump(mode="json"))
        questions = [ResearchQuestion.model_validate(q) for q in self.read("questions.json")]
        bundle.research = await NarrativeService(
            self.runtime, self.budget, allow_retrieval=state.get("repair_round", 0) < 2
        ).compose(bundle, questions, self.store.get(self.run_id)["prompt"])
        self.write("bundle.json", bundle.model_dump(mode="json"))
        self.write("questions.json", [q.model_dump() for q in bundle.research.questions])
        repair = ""
        reviews = bundle.research.reviews
        if (
            bundle.research.status != "complete"
            and state.get("repair_round", 0) < 2
            and self.budget.can_investigate
            and reviews
            and self.read("research-text-attempts.json")["attempts"] < 3
        ):
            retrieval = [
                v for v in reviews[-1].get("review", {}).get("claims", []) if v["repair"] == "retrieve"
            ]
            retrieval.extend(
                {"finding_id": check["finding_id"], **violation}
                for check in reviews[-1].get("meaning_review", {}).get("checks", [])
                for violation in check["violations"]
                if violation["repair"] == "retrieve"
            )
            retrieval.extend(g for g in reviews[-1].get("open_gaps", []) if g.get("next_action"))
            if retrieval:
                repair = json.dumps(
                    {
                        "text_repair": retrieval,
                        "questions": [
                            q.model_dump() for q in bundle.research.questions if q.status != "answered"
                        ],
                    },
                    ensure_ascii=False,
                )
        return {"repair": repair, "repair_round": state.get("repair_round", 0) + bool(repair)}

    async def render(self, state: RunState):
        self.check()
        bundle = ResearchBundle.model_validate(self.read("bundle.json"))
        if bundle.research is None or not bundle.research.text:
            raise ValueError("未获得可发布的已核验正文，证据与核验记录已保存")
        (self.root / "research.txt").write_text(bundle.research.text)
        if self.export:
            from .exporters import export_all

            self.store.emit(self.run_id, "step", "生成交互报告与研究文件", phase="render")
            await asyncio.to_thread(export_all, bundle, self.root / "artifacts")
            status = bundle.completion_status
        else:
            status = "researched"
        self.check()
        self.store.update(self.run_id, status=status, bundle_path=str(self.root / "bundle.json"))
        self.store.emit(
            self.run_id,
            "complete",
            "研究产物已生成" if self.export else "研究正文已核验",
            status=status,
            research_status=bundle.research.status,
            events=len(bundle.events),
            sources=len(bundle.sources),
        )
        return {}

    async def run(self):
        if not self.store.update(self.run_id, expected={"queued", "running"}, status="running", error=None):
            return
        graph = StateGraph(RunState)
        for name in ["plan", "collect", "research", "analyze", "review", "synthesize", "render"]:
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "plan")
        graph.add_conditional_edges("plan", lambda s: END if s.get("needs_input") else "collect")
        graph.add_edge("collect", "research")
        graph.add_edge("research", "analyze")
        graph.add_edge("analyze", "review")
        graph.add_conditional_edges("review", lambda s: "research" if s.get("repair") else "synthesize")
        graph.add_conditional_edges("synthesize", lambda s: "research" if s.get("repair") else "render")
        graph.add_edge("render", END)
        self.budget.start()
        ticker = asyncio.create_task(self.budget.heartbeat())
        try:
            async with AsyncSqliteSaver.from_conn_string(
                str(self.config.data_dir / "checkpoints.sqlite3")
            ) as saver:
                compiled = graph.compile(checkpointer=saver)
                config = {"configurable": {"thread_id": self.run_id}, "recursion_limit": 40}
                snapshot = await compiled.aget_state(config)
                async with asyncio.timeout(self.budget.remaining):
                    await compiled.ainvoke(None if snapshot.next else {"run_id": self.run_id}, config)
        except CancelledRun:
            self.store.emit(self.run_id, "cancelled", "任务已取消")
        except Exception as exc:
            # Provider exception text can contain request details. Persist only a sanitized summary.
            from .security import safe_error

            message = safe_error(exc, self.config)
            self.store.update(self.run_id, expected={"running"}, status="failed", error=message)
            self.store.emit(self.run_id, "error", message, error_type=type(exc).__name__)
            raise
        finally:
            ticker.cancel()
            with suppress(asyncio.CancelledError):
                await ticker
            self.budget.stop()
