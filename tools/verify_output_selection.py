"""Live planner-only acceptance; does not run research, exports, or change the agent loop."""

import asyncio
import json
from dataclasses import replace

from research_app.agents import AgentRuntime
from research_app.config import PROJECT_ROOT, settings
from research_app.domain import digest, now_iso
from research_app.storage import Store

CASES = [
    (
        "nvda-original",
        "回顾英伟达（NVDA）近五年行情数据（开盘价、收盘价、最高价、最低价、成交量），梳理同期AI行业大事件，如ChatGPT发布、B100芯片发布、DeepSeek，在K线图上标记行情变化触发时刻的主要事件、影响评级，产物可交互、可溯源，最终生成一个HTML。",
        ["html"],
        None,
    ),
    (
        "comparison-original",
        "请构建黄金与比特币作为避险/抗通胀资产的可交互比较分析体系，产物包括Excel回测底稿、PPT决策框架、Word策略报告。",
        ["xlsx", "pptx", "docx"],
        None,
    ),
    ("report", "研究NVDA近五年AI行业事件，生成报告", ["html"], None),
    ("strategy-report", "比较黄金GLD与BTC-USD，生成策略报告", ["html"], None),
    ("document", "研究NVDA近五年行情，生成文档", ["docx"], None),
    ("slides", "比较黄金GLD与BTC-USD，准备汇报材料", ["pptx"], None),
    ("workbook", "比较黄金GLD与BTC-USD，提供回测底稿", ["xlsx"], None),
    ("all", "研究NVDA近五年行情，生成HTML、Excel、PPT和Word四种产物", ["html", "xlsx", "pptx", "docx"], None),
    ("text-only", "研究NVDA近五年行情，只给文字，不导出文件", [], None),
    ("replace", "改为只要PPT", ["pptx"], "comparison-original"),
    ("inherit", "区间改为2023-01-01至2025-12-31", ["xlsx", "pptx", "docx"], "comparison-original"),
    ("add", "再加Excel底稿", ["html", "xlsx"], "report"),
    ("remove", "不要Word，其余保留", ["xlsx", "pptx"], "comparison-original"),
]


async def main():
    folder = PROJECT_ROOT.parent.parent / "work" / ("output-selection-" + now_iso().replace(":", "-"))
    config = replace(settings(), data_dir=folder)
    if not config.model_ready:
        raise SystemExit("Model configuration required")
    store = Store(folder)
    results, specs = [], {}
    for name, prompt, expected, previous in CASES:
        rid = store.create(prompt)
        runtime = AgentRuntime(config, store, rid)
        try:
            parsed = await runtime.parse(prompt, specs.get(previous))
            actual = parsed.spec.outputs if parsed.spec else None
            row = {
                "case": name,
                "prompt": prompt,
                "previous": previous,
                "expected": expected,
                "actual": actual,
                "passed": actual is not None
                and set(actual) == set(expected)
                and not parsed.needs_clarification,
            }
            if parsed.spec:
                specs[name] = parsed.spec.model_dump(mode="json")
        except Exception as exc:
            row = {"case": name, "passed": False, "error_type": type(exc).__name__}
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    record = {
        "at": now_iso(),
        "scope": "Real model planner only; no research loop or report content evaluation",
        "planner_prompt_sha256": digest((PROJECT_ROOT / "prompts/planner.md").read_text()),
        "passed": all(r["passed"] for r in results),
        "cases": results,
    }
    (PROJECT_ROOT / "evals/output-selection-20260929.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    )
    if not record["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
