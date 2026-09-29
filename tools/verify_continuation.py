"""Opt-in current-code live checks. Existing sample results and credentials stay untouched."""

import asyncio
import json
from pathlib import Path

from research_app.agents import AgentRuntime
from research_app.analytics import validate_bundle
from research_app.config import PROJECT_ROOT, settings
from research_app.domain import ResearchBundle, now_iso
from research_app.pipeline import Pipeline
from research_app.security import safe_error
from research_app.storage import Store


async def main():
    cfg = settings()
    store = Store(cfg.data_dir)
    result = {"started_at": now_iso(), "checks": [], "model_requested": cfg.model}
    output = PROJECT_ROOT / "evals/continuation-results.json"

    def record(row):
        result["checks"].append(row)
        store.save_json(output, result)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    parent = store.create("研究苹果近三年事件，基准 QQQ，成本 25 bps", mode="evaluation")
    store.update(parent, status="needs_input", error="苹果指 AAPL 股票吗？")
    child = store.create("是的，只要 HTML", mode="evaluation", parent_id=parent)
    try:
        job = Pipeline(cfg, store, child, export=False)
        state = await job.plan({})
        spec = state.get("spec", {})
        passed = (
            spec.get("symbols") == ["AAPL"] and spec.get("benchmark") == "QQQ" and spec.get("cost_bps") == 25
        )
        store.update(child, status="complete" if passed else "failed")
        record({"check": "clarification", "run_id": child, "passed": passed, "spec": spec})
    except Exception as exc:
        record({"check": "clarification", "passed": False, "error": safe_error(exc, cfg)})

    for name, request in [
        (
            "event_generalization",
            "研究 AMD 2024-01-01 至 2025-12-31 的行情与 MI300/MI350 AI 加速器行业事件，基准 QQQ，标注原始证据及事件窗口，生成四种文件。",
        ),
        (
            "comparison_generalization",
            "比较黄金 GLD 与以太坊 ETH-USD 从 2023-01-01 至 2025-12-31 的避险、抗通胀和配置表现，基准 SPY，权重 60/40，季度再平衡，成本 20 bps，生成四种文件。",
        ),
    ]:
        rid = store.create(request, mode="evaluation", refresh=True)
        print(json.dumps({"check": name, "run_id": rid, "status": "started"}), flush=True)
        try:
            await Pipeline(cfg, store, rid).run()
            run = store.get(rid)
            bundle = ResearchBundle.model_validate_json(Path(run["bundle_path"]).read_text())
            expected = (
                {"intent": "event_study", "symbols": ["AMD"], "benchmark": "QQQ"}
                if name == "event_generalization"
                else {
                    "intent": "asset_comparison",
                    "symbols": ["GLD", "ETH-USD"],
                    "weights": [0.6, 0.4],
                    "rebalance_months": 3,
                    "cost_bps": 20.0,
                }
            )
            semantic_passed = all(getattr(bundle.spec, key) == value for key, value in expected.items())
            trace = store.events(rid)
            record(
                {
                    "check": name,
                    "run_id": rid,
                    "status": run["status"],
                    "passed": run["status"] == "complete"
                    and validate_bundle(bundle)["passed"]
                    and semantic_passed,
                    "semantic_passed": semantic_passed,
                    "models_returned": sorted({e["payload"]["model"] for e in trace if e["kind"] == "model"}),
                    "model_calls": sum(e["kind"] == "model" for e in trace),
                    "tool_calls": sum(e["kind"] == "tool" for e in trace),
                    "skills": [e["label"] for e in trace if e["kind"] == "skill"],
                    "spec": bundle.spec.model_dump(mode="json"),
                    "events": len(bundle.events),
                    "sources": len(bundle.sources),
                    "validation": validate_bundle(bundle),
                    "macro": list(bundle.comparison.get("macro", {})),
                    "months": len(bundle.comparison.get("anchors", [])),
                    "warnings": bundle.warnings,
                }
            )
            if name == "comparison_generalization":
                answer = await AgentRuntime(cfg, store, rid).explain(
                    bundle, "这里组合的最大回撤是多少？请区分两个口径并注明来源。"
                )
                record(
                    {
                        "check": "live_chat",
                        "run_id": rid,
                        "passed": all(
                            f"{bundle.comparison[k]['metrics']['max_drawdown']:.2%}" in answer
                            for k in ["backtest", "formula_backtest"]
                        )
                        and any(f"[{d.id}]" in answer for d in bundle.datasets.values()),
                        "answer": answer,
                        "expected_metrics": {
                            k: bundle.comparison.get(k, {}).get("metrics", {})
                            for k in ["backtest", "formula_backtest"]
                        },
                    }
                )
        except Exception as exc:
            record({"check": name, "run_id": rid, "passed": False, "error": safe_error(exc, cfg)})
    result["finished_at"] = now_iso()
    store.save_json(output, result)


if __name__ == "__main__":
    asyncio.run(main())
