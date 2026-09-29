"""Collect immutable live results and separate content audits; never promote a model verdict."""

import json

from research_app.config import PROJECT_ROOT

SUITES = ["FinalNVDA", "FinalGoldBTC", "FinalAMD", "FinalGoldETH"]


def summarize():
    root = PROJECT_ROOT / "evals/text-research"
    records = []
    for suite in SUITES:
        results = [json.loads(p.read_text()) for p in (root / suite).glob("*.result.json")]
        for result in sorted(results, key=lambda row: row["started_at"]):
            rid = result["run_id"]
            audit_path = root / suite / f"{rid}.content-audit.json"
            audit = json.loads(audit_path.read_text()) if audit_path.exists() else None
            records.append(
                {
                    "suite": suite,
                    "case": result["case"],
                    "run_id": rid,
                    "automated_pass": result["automated_pass"],
                    "content_pass": audit["content_pass"] if audit else None,
                    "issues": audit["issues"] if audit else [],
                    "budget": result.get("budget", {}),
                    "usage": result.get("usage", {}),
                    "checks": result.get("checks", {}),
                    "code_hash": result["code_hash"],
                    "code_unchanged": result["code_unchanged"],
                    "result_file": f"{suite}/{result['case']}-{rid}.result.json",
                    "text_file": f"{suite}/{result['case']}-{rid}.txt",
                }
            )
    complete = len(records) == 8 and all(r["content_pass"] is not None for r in records)
    one_version = len({r["code_hash"] for r in records}) == 1 and all(r["code_unchanged"] for r in records)
    passed = complete and one_version and all(r["automated_pass"] and r["content_pass"] for r in records)
    summary = {
        "status": "evaluation_finished" if complete else "evaluation_in_progress",
        "acceptance_passed": passed,
        "pause_requested_after_evaluation": True,
        "planned_runs": 8,
        "completed_runs": len(records),
        "fixed_version": one_version,
        "automated_pass_count": sum(r["automated_pass"] for r in records),
        "independently_accepted_count": sum(r["content_pass"] is True for r in records),
        "results": records,
    }
    (root / "final-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    lines = [
        "# 固定版本真实评估结果",
        "",
        f"已完成 {len(records)}/8 次，自动检查通过 {summary['automated_pass_count']} 次。"
        f"整体内容验收：{'通过' if passed else '未通过'}。",
        "",
        "自动 complete 仅表示程序与生产模型核验通过；不等同独立内容验收。"
        "逐条审阅由 Codex 在生产核验器之外，对照正文、保存原文和确定性指标完成，不以单一模型评分作结论。",
        "",
        "| 场景 | 运行 ID | 自动检查 | 内容复核 | 秒 | 模型调用 |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ]
    for r in records:
        link = f"../evals/text-research/{r['text_file']}"
        content = "通过" if r["content_pass"] else "需修订" if r["content_pass"] is False else "待审阅"
        lines.append(
            f"| {r['case']} | [{r['run_id']}]({link}) | "
            f"{'通过' if r['automated_pass'] else '未通过'} | {content} | "
            f"{r['budget'].get('elapsed_seconds', 0):.1f} | {r['budget'].get('model_calls', 0)} |"
        )
    lines += [
        "",
        "每次原始记录均保留，没有覆盖失败结果或手改正文。全部运行显式关闭导出；真实文件导出测试未执行。",
        "",
        "## 内容复核发现",
        "",
    ]
    for r in records:
        lines.append(f"- **{r['run_id']}**：" + "；".join(issue["reason"] for issue in r["issues"]))
    models = sorted({model for r in records for model in r["usage"].get("actual_models", [])})
    lines += [
        "",
        "## 版本与复核入口",
        "",
        f"生产代码/Prompt/技能/来源目录是否保持同一哈希：{one_version}。",
        "",
        f"实际服务返回的模型标识：`{', '.join(models)}`。该标识不证明底层模型家族。",
        "",
        "[机器可读汇总](../evals/text-research/final-summary.json) · "
        "[工程验证](../evals/engineering-verification.json) · "
        "[API/CLI 验证](../evals/text-api-cli-verification.json)",
    ]
    (PROJECT_ROOT / "docs/final-evaluation.md").write_text("\n".join(lines) + "\n")
    return summary


if __name__ == "__main__":
    result = summarize()
    print(json.dumps({key: value for key, value in result.items() if key != "results"}))
