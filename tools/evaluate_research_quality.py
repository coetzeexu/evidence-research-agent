"""Opt-in unedited end-to-end runs. Coverage checks are not a factual-accuracy benchmark."""

import argparse
import asyncio
import json
from hashlib import sha256

from research_app.agents import has_date_evidence
from research_app.analytics import validate_bundle
from research_app.config import PROJECT_ROOT, settings
from research_app.domain import ResearchBundle, SourceRecord, now_iso
from research_app.pipeline import Pipeline
from research_app.security import safe_error
from research_app.storage import Store

CASES = {
    "nvda": {
        "prompt": "回顾 NVDA 近五年日线和同期 AI 行业大事件，必须覆盖 ChatGPT 发布、Blackwell 平台发布、"
        "DeepSeek 相关事件；重点调查 2025-01-27 的下跌与同期信息，区分论文日、模型发布日和市场反应日。输出 HTML、Excel、PPT、Word。",
        "symbols": ["NVDA"],
        "required_terms": ["ChatGPT", "Blackwell", "DeepSeek"],
    },
    "gold-bitcoin": {
        "prompt": "比较黄金 GLD 与比特币 BTC-USD 近五年避险和抗通胀表现，美元计价，"
        "60/40 权重，季度再平衡，交易成本 20 bps。生成 Excel 回测底稿、PPT 决策框架、Word 策略报告和 HTML。",
        "symbols": ["GLD", "BTC-USD"],
        "required_terms": [],
    },
    "focused": {
        "prompt": "只研究 NVDA 在 2024 年 3 月 18 日的 Blackwell 平台发布事件，"
        "用 2024-03-01 至 2024-04-30 日线分析事件窗口，基准 SPY。不要加入其他事件，只生成 HTML。",
        "symbols": ["NVDA"],
        "required_terms": ["Blackwell"],
    },
}


async def evaluate(name, resume_id=None):
    config = settings()
    store = Store(config.data_dir)
    case = CASES[name]
    if resume_id:
        saved = store.get(resume_id)
        if saved["prompt"] != case["prompt"] or saved["status"] != "failed":
            raise ValueError("只能恢复该评估用例的失败运行，不能覆盖正在执行或已完成的研究")
        run_id = resume_id
        store.update(run_id, expected={"failed"}, status="queued", error=None)
    else:
        run_id = store.create(case["prompt"], mode="live")
    print(json.dumps({"case": name, "run_id": run_id, "status": "started"}), flush=True)
    result = {
        "case": name,
        "run_id": run_id,
        "started_at": now_iso(),
        "manual_edits": False,
        "resumed_from_checkpoint": bool(resume_id),
    }
    try:
        await Pipeline(config, store, run_id, export=False).run()
        raw = (store.run_dir(run_id) / "bundle.json").read_bytes()
        bundle = ResearchBundle.model_validate_json(raw)
        required = bundle.spec.required_events
        checks = {
            "symbols": bundle.spec.symbols == case["symbols"],
            "numeric_and_reference_integrity": validate_bundle(bundle)["passed"],
            "named_requirements_retained": all(
                any(t.lower() in r.lower() for r in required) for t in case["required_terms"]
            ),
            "coverage_gate": bundle.quality.get("passed", False),
            "independent_review": bundle.review.get("passed", False),
        }
        evidence = json.loads((store.run_dir(run_id) / "research-evidence.json").read_text())
        evidence_sources = {sid: SourceRecord.model_validate(s) for sid, s in evidence["sources"].items()}
        checks["date_evidence"] = bool(bundle.events) and all(
            has_date_evidence(event, evidence_sources, evidence["texts"]) for event in bundle.events
        )
        if name == "focused":
            checks["focused_scope"] = bundle.spec.event_scope == "focused"
            checks["no_unrequested_events"] = bool(bundle.events) and all(e.satisfies for e in bundle.events)
        if name == "nvda":
            changes = [c for c in bundle.changes if c["date"] == "2025-01-27"]
            ids = {e.id for e in bundle.events if "deepseek" in (e.title + e.summary).lower()}
            checks["deepseek_move_candidate"] = any(ids.intersection(c["event_ids"]) for c in changes)
        if name == "gold-bitcoin":
            checks["parameters"] = (
                bundle.spec.weights == [0.6, 0.4]
                and bundle.spec.cost_bps == 20
                and bundle.spec.rebalance_months == 3
            )
            checks["sensitivity"] = len(bundle.comparison.get("sensitivity", {}).get("rows", [])) >= 10
        result.update(
            checks=checks,
            passed=all(checks.values()),
            completion_status=bundle.completion_status,
            bundle_sha256=sha256(raw).hexdigest(),
            quality=bundle.quality,
            review=bundle.review,
            events=len(bundle.events),
            sources=len(bundle.sources),
            spec=bundle.spec.model_dump(mode="json"),
        )
    except Exception as exc:
        result.update(passed=False, error=safe_error(exc, config))
    result["finished_at"] = now_iso()
    print(json.dumps({"case": name, "run_id": run_id, "passed": result["passed"]}), flush=True)
    (PROJECT_ROOT / "evals" / f"research-quality-{name}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    return result


async def main(selection, resume_id=None):
    sem = asyncio.Semaphore(2)

    async def bounded(name):
        async with sem:
            return await evaluate(name, resume_id)

    names = list(CASES) if selection == "all" else [selection]
    results = await asyncio.gather(*(bounded(n) for n in names))
    report = {
        "checked_at": now_iso(),
        "scope": "Unedited live runs; automated coverage, parameters, "
        "numeric integrity and source-reference checks. Not independent human fact checking.",
        "results": results,
    }
    (PROJECT_ROOT / "evals" / "research-quality-latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=[*CASES, "all"], default="all")
    parser.add_argument("--resume", help="从失败运行的 LangGraph 检查点恢复，不重新采集已完成阶段")
    args = parser.parse_args()
    if args.resume and args.case == "all":
        parser.error("--resume 必须指定单一 --case")
    asyncio.run(main(args.case, args.resume))
