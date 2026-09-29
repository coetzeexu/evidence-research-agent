"""Text-only live evaluation. All attempts are immutable; no renderer or browser is used."""

import argparse
import asyncio
import json
import shutil
import sys
from dataclasses import replace
from importlib.metadata import version

from research_app.agents import AgentRuntime
from research_app.analytics import build_bundle, validate_bundle
from research_app.config import PROJECT_ROOT, settings
from research_app.domain import ResearchBundle, digest, now_iso
from research_app.pipeline import Pipeline
from research_app.research_contract import MeaningReview, NarrativeDraft, NarrativeReview
from research_app.research_logic import verify_relationships
from research_app.research_metrics import metric_catalog
from research_app.research_semantics import verify_meaning
from research_app.research_text import NarrativeService, research_questions, validate_draft
from research_app.security import safe_error
from research_app.storage import Store

CASES = {
    "nvda": {
        "prompt": "回顾 NVDA 在 2021-09-28 至 2026-09-28 的五年 OHLCV 日线及 AI 行业大事件。必须核实 ChatGPT 首次公开发布、Blackwell（B100/B200）平台发布、DeepSeek-R1 模型发布；调查 2025-01-27 下跌，区分模型发布、论文公开和市场反应日期。分析主要行情变化、对应事件、反应强度与关联可信度、竞争性解释和局限。只输出有原文和数值依据的中文调研文字，不导出报告。",
        "symbols": ["NVDA"],
    },
    "gold-bitcoin": {
        "prompt": "比较 2021-09-28 至 2026-09-28 黄金 GLD 与比特币 BTC-USD 的避险和抗通胀表现，美元计价，GLD/BTC 权重 60/40、季度再平衡、单边交易成本 20 bps、初始资本 100000 美元、基准 SPY。分析压力期保护、实际购买力、通胀关联、同口径组合与单资产基线，以及成本/权重/频率/分段敏感性，形成有条件的决策框架。只输出有证据的中文调研文字，不导出报告。",
        "symbols": ["GLD", "BTC-USD"],
    },
    "amd": {
        "prompt": "研究 AMD 在 2023-01-01 至 2026-09-28 的日线和 AI 产业相关行情变化，必须核实 MI300 系列发布，基准 SPY。分析主要异动及同期信息、反应强度、替代解释和证据局限。只输出可复核中文文字，不导出报告。",
        "symbols": ["AMD"],
    },
    "gold-ethereum": {
        "prompt": "比较 2021-09-28 至 2026-09-28 黄金 GLD 和以太坊 ETH-USD 的避险、抗通胀及组合价值。美元计价，GLD/ETH 权重 60/40，季度再平衡，单边成本 20 bps，初始资本 100000 美元，基准 SPY。给出压力月份、实际购买力、通胀关联、同口径单资产与组合及敏感性分析的有条件结论。只输出可溯源中文文字，不导出报告。",
        "symbols": ["GLD", "ETH-USD"],
    },
}


def code_hash():
    paths = [
        p
        for folder in ["backend/research_app", "prompts", "skills", "resources"]
        for p in (PROJECT_ROOT / folder).rglob("*")
        if p.suffix in {".py", ".md", ".json"}
    ]
    return digest({str(p.relative_to(PROJECT_ROOT)): digest(p.read_text()) for p in sorted(paths)})


def audit_numbers(bundle):
    fresh = build_bundle(
        bundle.id,
        bundle.spec,
        bundle.datasets,
        bundle.sources,
        bundle.events,
        bundle.comparison.get("macro", {}),
        bundle.coverage,
    )
    expected = metric_catalog(fresh)
    return all(
        m.id in expected and m.model_dump() == expected[m.id].model_dump() for m in bundle.research.metrics
    )


def check_text(bundle, texts):
    result = bundle.research
    if result is None:
        return {"verified_text": False}
    errors, _ = validate_draft(
        NarrativeDraft(findings=result.findings),
        bundle,
        result.questions,
        texts,
        {m.id: m for m in result.metrics},
    )
    relations_passed = True
    meanings_passed = True
    for finding in result.findings:
        audits = [
            a
            for a in result.reviews
            if a.get("accepted_hashes", {}).get(finding.id) == digest(finding.model_dump())
        ]
        if not audits:
            relations_passed = False
            continue
        review = NarrativeReview.model_validate(audits[-1]["review"])
        relation_errors, _ = verify_relationships(
            NarrativeDraft(findings=[finding]), review, {m.id: m for m in result.metrics}
        )
        relations_passed &= not relation_errors
        meaning = MeaningReview.model_validate(audits[-1].get("meaning_review", {"checks": []}))
        meanings_passed &= not verify_meaning(NarrativeDraft(findings=[finding]), meaning)
    return {
        "verified_text": bool(result.text and result.findings),
        "complete": result.status == "complete",
        "required_questions": all(q.status == "answered" for q in result.questions if q.required),
        "deterministic_provenance": not errors,
        "recomputed_metrics": audit_numbers(bundle),
        "publication_review_hashes": all(
            any(a.get("accepted_hashes", {}).get(f.id) == digest(f.model_dump()) for a in result.reviews)
            for f in result.findings
        ),
        "market_calculations": validate_bundle(bundle)["passed"],
        "replayed_numeric_relationships": relations_passed,
        "inference_review": meanings_passed,
    }


def usage_summary(store, run_id):
    events, cursor = [], 0
    while batch := store.events(run_id, cursor):
        events.extend(batch)
        cursor = batch[-1]["seq"]
    models = [e["payload"] for e in events if e["kind"] == "model"]
    return {
        "actual_models": sorted({m.get("model", "unknown") for m in models}),
        "completed_model_calls": len(models),
        "input_tokens": sum(m.get("usage", {}).get("input_tokens", 0) for m in models),
        "output_tokens": sum(m.get("usage", {}).get("output_tokens", 0) for m in models),
        "failed_model_calls": sum(e["kind"] == "model_error" for e in events),
    }


async def evaluate(case_name, config, store, output, snapshot=False):
    case = CASES[case_name]
    run_id = store.create(case["prompt"], export_reports=False)
    root = store.run_dir(run_id)
    record = {
        "case": case_name,
        "run_id": run_id,
        "started_at": now_iso(),
        "code_hash": code_hash(),
        "mode": "frozen-text" if snapshot else "live-end-to-end",
        "prompt": case["prompt"],
        "manual_edits": False,
        "independent_content_audit": "pending",
        "runtime": {
            "python": sys.version.split()[0],
            "packages": {
                name: version(name) for name in ["langchain", "langgraph", "langchain-openai", "pydantic"]
            },
        },
    }
    print(json.dumps({"case": case_name, "run_id": run_id, "status": "started"}), flush=True)
    try:
        if snapshot:
            original = settings()
            old = ResearchBundle.model_validate_json(
                (PROJECT_ROOT / "samples" / case_name / "bundle.json").read_text()
            )
            evidence = original.data_dir / "runs" / old.id / "research-evidence.json"
            shutil.copyfile(evidence, root / "research-evidence.json")
            bundle = build_bundle(
                run_id,
                old.spec,
                old.datasets,
                old.sources,
                old.events,
                old.comparison.get("macro", {}),
                old.coverage,
            )
            bundle.review = old.review
            runtime = AgentRuntime(config, store, run_id)
            try:
                bundle.research = await NarrativeService(runtime).compose(
                    bundle, research_questions(bundle.spec), case["prompt"]
                )
            finally:
                runtime.budget.stop()
            store.save_json(root / "bundle.json", bundle.model_dump(mode="json"))
        else:
            await Pipeline(config, store, run_id, export=False).run()
            bundle = ResearchBundle.model_validate_json((root / "bundle.json").read_text())
        evidence = json.loads((root / "research-evidence.json").read_text())
        checks = check_text(bundle, evidence["texts"])
        checks["symbols"] = bundle.spec.symbols == case["symbols"]
        if not snapshot:
            checks["requested_dates"] = (
                str(bundle.spec.start) == ("2023-01-01" if case_name == "amd" else "2021-09-28")
                and str(bundle.spec.end) == "2026-09-28"
            )
            if len(case["symbols"]) > 1:
                checks["requested_execution"] = (
                    bundle.spec.weights == [0.6, 0.4]
                    and bundle.spec.rebalance_months == 3
                    and bundle.spec.cost_bps == 20
                    and bundle.spec.initial_capital == 100000
                    and bundle.spec.benchmark == "SPY"
                )
            else:
                required = " ".join(bundle.spec.required_events).lower()
                checks["explicit_events_preserved"] = all(
                    word.lower() in required
                    for word in (["ChatGPT", "Blackwell", "DeepSeek"] if case_name == "nvda" else ["MI300"])
                )
        checks["no_exports"] = not (root / "artifacts").exists()
        budget = json.loads((root / "execution-budget.json").read_text())
        checks["bounded"] = budget["elapsed_seconds"] <= 901 and budget["model_calls"] <= 64
        checks["bounded_tools"] = (
            evidence.get("search_count", 0) <= 34 and evidence.get("read_count", 0) <= 50
        )
        text = bundle.research.text if bundle.research else ""
        (output / f"{case_name}-{run_id}.txt").write_text(text)
        store.save_json(output / f"{case_name}-{run_id}.bundle.json", bundle.model_dump(mode="json"))
        store.save_json(
            output / f"{case_name}-{run_id}.research.json",
            bundle.research.model_dump(mode="json") if bundle.research else {},
        )
        record.update(
            checks=checks,
            automated_pass=all(checks.values()),
            budget=budget,
            bundle_hash=digest(bundle.model_dump(mode="json")),
            spec=bundle.spec.model_dump(mode="json"),
        )
    except Exception as exc:
        record.update(automated_pass=False, error=safe_error(exc, config))
        if (root / "execution-budget.json").exists():
            record["budget"] = json.loads((root / "execution-budget.json").read_text())
    record["finished_at"] = now_iso()
    record["usage"] = usage_summary(store, run_id)
    record["code_unchanged"] = record["code_hash"] == code_hash()
    if not record["code_unchanged"]:
        record["automated_pass"] = False
    store.save_json(output / f"{case_name}-{run_id}.result.json", record)
    print(
        json.dumps(
            {
                "case": case_name,
                "run_id": run_id,
                "passed": record["automated_pass"],
                "checks": record.get("checks", {}),
                "error": record.get("error"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return record


async def main(args):
    if not args.suite.isalnum():
        raise ValueError("suite 仅使用字母和数字，避免覆盖其他目录")
    output = PROJECT_ROOT / "evals/text-research" / args.suite
    if output.exists():
        raise ValueError("保留已有评估，请使用新的 suite 名称")
    output.mkdir(parents=True)
    config = replace(
        settings(), data_dir=PROJECT_ROOT.parent.parent / "work/agent-text-evaluations" / args.suite
    )
    store = Store(config.data_dir)
    groups = {
        "all": ["nvda"] * 3 + ["gold-bitcoin"] * 3 + ["amd", "gold-ethereum"],
        "events": ["nvda"] * 3 + ["amd"],
        "comparison": ["gold-bitcoin"] * 3 + ["gold-ethereum"],
    }
    names = groups.get(args.case, [args.case] * args.repeats)
    if args.snapshot and args.case not in {"nvda", "gold-bitcoin"}:
        raise ValueError("冻结样例仅支持 nvda 或 gold-bitcoin")
    frozen_hash = code_hash()
    records = []
    for name in names:
        if code_hash() != frozen_hash:
            raise RuntimeError("评估期间代码发生变化；本批不作为最终固定版本验收")
        records.append(await evaluate(name, config, store, output, args.snapshot))
        store.save_json(
            output / "summary.json",
            {
                "code_hash": frozen_hash,
                "planned_cases": names,
                "results": records,
                "automated_pass": len(records) == len(names) and all(r["automated_pass"] for r in records),
                "independent_content_audit": "pending",
            },
        )
        if args.fail_fast and not records[-1]["automated_pass"]:
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=[*CASES, "all", "events", "comparison"], default="all")
    parser.add_argument("--suite", required=True)
    parser.add_argument("--snapshot", action="store_true")
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--fail-fast", action="store_true", help="保留首个失败后停止批次，用于开发复验")
    asyncio.run(main(parser.parse_args()))
