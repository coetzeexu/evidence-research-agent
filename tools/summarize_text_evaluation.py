"""Summarize explicitly selected live suites without rewriting their original records."""

import argparse
import json
from collections import Counter

from research_app.config import PROJECT_ROOT

EXPECTED_CASES = {"nvda": 3, "gold-bitcoin": 3, "amd": 1, "gold-ethereum": 1}
REQUIRED_CHECKS = {
    "verified_text",
    "complete",
    "required_questions",
    "deterministic_provenance",
    "recomputed_metrics",
    "publication_review_hashes",
    "market_calculations",
    "replayed_numeric_relationships",
    "inference_review",
    "symbols",
    "requested_dates",
    "no_exports",
    "bounded",
    "bounded_tools",
}


def summarize(root, suites):
    if not suites or len(set(suites)) != len(suites) or any(not s.isalnum() for s in suites):
        raise ValueError("Provide distinct alphanumeric suite names")
    records = []
    for suite in suites:
        folder = root / suite
        if not folder.is_dir():
            raise ValueError(f"Missing suite: {suite}")
        results = [json.loads(p.read_text()) for p in folder.glob("*.result.json")]
        for result in sorted(results, key=lambda row: row["started_at"]):
            rid = result["run_id"]
            audit_path = folder / f"{rid}.content-audit.json"
            audit = json.loads(audit_path.read_text()) if audit_path.exists() else None
            expected = REQUIRED_CHECKS | {
                "requested_execution" if result["case"].startswith("gold-") else "explicit_events_preserved"
            }
            checks = result.get("checks", {})
            passed = (
                result.get("automated_pass") is True
                and expected <= checks.keys()
                and all(value is True for value in checks.values())
                and result.get("mode") == "live-end-to-end"
            )
            audit_passed = (
                (
                    audit.get("content_pass") is True
                    and audit.get("run_id") == rid
                    and audit.get("bundle_hash") == result.get("bundle_hash")
                    and bool(result.get("bundle_hash"))
                    and not any(i.get("severity") in {"critical", "error"} for i in audit.get("issues", []))
                )
                if audit
                else None
            )
            records.append(
                {
                    "suite": suite,
                    "case": result["case"],
                    "run_id": rid,
                    "automated_pass": passed,
                    "content_pass": audit_passed,
                    "issues": audit.get("issues", []) if audit else [],
                    "budget": result.get("budget", {}),
                    "usage": result.get("usage", {}),
                    "checks": checks,
                    "code_hash": result["code_hash"],
                    "code_unchanged": result["code_unchanged"],
                    "bundle_hash": result.get("bundle_hash"),
                    "result_file": f"{suite}/{result['case']}-{rid}.result.json",
                    "text_file": f"{suite}/{result['case']}-{rid}.txt",
                }
            )
    matrix_complete = Counter(r["case"] for r in records) == EXPECTED_CASES
    unique_runs = len({r["run_id"] for r in records}) == len(records)
    one_version = len({r["code_hash"] for r in records}) == 1 and all(r["code_unchanged"] for r in records)
    complete = matrix_complete and unique_runs and all(r["content_pass"] is not None for r in records)
    passed = complete and one_version and all(r["automated_pass"] and r["content_pass"] for r in records)
    return {
        "status": "evaluation_finished" if complete else "evaluation_in_progress",
        "acceptance_passed": passed,
        "planned_cases": EXPECTED_CASES,
        "completed_runs": len(records),
        "matrix_complete": matrix_complete,
        "unique_runs": unique_runs,
        "fixed_version": one_version,
        "automated_pass_count": sum(r["automated_pass"] for r in records),
        "independently_accepted_count": sum(r["content_pass"] is True for r in records),
        "results": records,
    }


def markdown(summary, summary_name):
    lines = [
        "# 当前版本运行验收",
        "",
        f"完整研究运行 {summary['completed_runs']}/8 次，基础自动检查通过 {summary['automated_pass_count']} 次，"
        f"独立基础内容复核通过 {summary['independently_accepted_count']} 次。"
        f"本轮验收：{'通过' if summary['acceptance_passed'] else '尚未全部通过'}。",
        "",
        "固定问题、日期与生产代码，NVDA / GLD-BTC 各连续三次，AMD / GLD-ETH 各一次。"
        "每次从需求解析、实时采集到正文核验完整执行；未使用快照代替真实运行，也未手改研究结果。",
        "",
        "基础检查覆盖必答问题、原文和指标引用、重算数字、比较口径、时间范围、发布核验及预算。"
        "独立复核在生产核验上下文之外检查重要事实、指标和结论边界；通过不代表预测准确率或因果关系得到证明。",
        "",
        "| 场景 | 运行 ID / 正文 | 自动检查 | 内容复核 | 秒 | 模型调用 |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ]
    for row in summary["results"]:
        content = "通过" if row["content_pass"] else "需修订" if row["content_pass"] is False else "待复核"
        lines.append(
            f"| {row['case']} | [{row['run_id']}](../evals/text-research/{row['text_file']}) | "
            f"{'通过' if row['automated_pass'] else '未通过'} | {content} | "
            f"{row['budget'].get('elapsed_seconds', 0):.1f} | {row['budget'].get('model_calls', 0)} |"
        )
    hashes = sorted({r["code_hash"] for r in summary["results"]})
    models = sorted({m for r in summary["results"] for m in r["usage"].get("actual_models", [])})
    lines += [
        "",
        f"生产代码、Prompt、技能和来源目录保持同一哈希：{summary['fixed_version']}。",
        "",
        "版本哈希：" + "、".join(f"`{h}`" for h in hashes) + "。",
        "",
        "实际服务返回的模型标识：" + "、".join(f"`{m}`" for m in models) + "。",
        "",
        "八次文字评估均关闭导出。会话、流式进度及文件生成由单独的本机浏览器用例验证。",
        "",
        f"[机器可读汇总](../evals/text-research/{summary_name}) · [工程与浏览器验证](validation.md)",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suites", nargs="+", required=True)
    parser.add_argument("--output", default="acceptance-summary.json")
    parser.add_argument("--write-doc", action="store_true")
    args = parser.parse_args()
    if "/" in args.output or "\\" in args.output or not args.output.endswith(".json"):
        parser.error("--output must be a JSON filename")
    root = PROJECT_ROOT / "evals/text-research"
    result = summarize(root, args.suites)
    (root / args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if args.write_doc:
        (PROJECT_ROOT / "docs/final-evaluation.md").write_text(markdown(result, args.output))
    print(json.dumps({k: v for k, v in result.items() if k != "results"}, ensure_ascii=False))
    raise SystemExit(0 if result["acceptance_passed"] else 1)
