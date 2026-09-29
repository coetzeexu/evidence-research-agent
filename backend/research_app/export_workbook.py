from pathlib import Path

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name as col

from .analytics import month_end_anchors, monthly_formula_backtest
from .domain import ResearchBundle
from .security import allowed_link


def export_workbook(bundle: ResearchBundle, target: Path):
    spec = bundle.spec
    book = xlsxwriter.Workbook(target, {"strings_to_formulas": False, "strings_to_urls": False})
    book.set_properties({"title": spec.title, "author": "Evidence", "comments": f"Research {bundle.id}"})
    fmt = {
        "title": book.add_format({"bold": True, "font_size": 20, "font_color": "#355A45"}),
        "head": book.add_format(
            {
                "bold": True,
                "bg_color": "#355A45",
                "font_color": "#FFFFFF",
                "text_wrap": True,
                "valign": "vcenter",
            }
        ),
        "text": book.add_format({"font_color": "#536654", "valign": "top", "text_wrap": True}),
        "number": book.add_format({"num_format": "#,##0.00;[Red](#,##0.00);–", "font_color": "#263D2E"}),
        "pct": book.add_format({"num_format": "0.00%;[Red](0.00%);–", "font_color": "#263D2E"}),
        "input": book.add_format({"bg_color": "#EDF4FC", "font_color": "#1761A0", "num_format": "0.00"}),
        "weight": book.add_format({"bg_color": "#EDF4FC", "font_color": "#1761A0", "num_format": "0.0%"}),
        "date": book.add_format({"num_format": "yyyy-mm-dd", "font_color": "#536654"}),
        "ok": book.add_format({"font_color": "#38744C", "num_format": "0.000000"}),
    }

    def sheet(name, headers=None, widths=None):
        ws = book.add_worksheet(name)
        ws.hide_gridlines(2)
        ws.set_default_row(20)
        ws.set_column(0, 35, 17)
        if headers:
            ws.write_row(0, 0, headers, fmt["head"])
            ws.set_row(0, 32)
            ws.freeze_panes(1, 1)
        if widths:
            for c, width in widths.items():
                ws.set_column(c, c, width)
        return ws

    overview = sheet("Overview", widths={0: 28, 1: 30, 2: 26, 3: 24, 4: 24})
    overview.merge_range("A1:E2", "Evidence · 研究回测底稿", fmt["title"])
    overview.merge_range("A4:E4", spec.title, fmt["text"])
    overview.merge_range(
        "A6:E7",
        "蓝色单元格为输入。Parameters 修改权重、成本与再平衡频率后，MonthlyCalc 与本页公式自动重算。ExecutionLedger 为原研究下一开盘成交快照，不随 Excel 参数更改。",
        fmt["text"],
    )
    overview.merge_range(
        "A9:E10",
        "所有价格来自有哈希的行情快照。月度估值采用不晚于股票收盘的可用日线；BTC 价格可能来自前一 UTC 日。宏观数据为当前历史版本，仅作事后解释。",
        fmt["text"],
    )
    overview.write("A12", "研究版本", fmt["text"])
    overview.write("B12", bundle.id)
    overview.write("A13", "区间", fmt["text"])
    overview.write("B13", f"{spec.start} / {spec.end}")
    for i, d in enumerate(bundle.disclosures):
        overview.merge_range(25 + i * 5, 0, 26 + i * 5, 4, d["description"] + d["reason"], fmt["text"])
        overview.merge_range(27 + i * 5, 0, 28 + i * 5, 4, d["limitations"], fmt["text"])
        overview.write_url(29 + i * 5, 0, d["url"], string="GLD 官方产品说明")

    params = sheet("Parameters", ["参数", "可修改数值", "口径 / 约束"], {0: 25, 1: 22, 2: 80})
    entries = [
        ("初始资金", spec.initial_capital, "美元"),
        ("交易成本 bps", spec.cost_bps, "0–100；只按成交额计费，GLD 管理费已体现在价格中"),
        ("再平衡月数", spec.rebalance_months, "0=持有；1=每月；3=每季；12=每年"),
        ("权重合计", "", "必须为 100%"),
        ("公式口径", "月度配置近似", "上期持仓获得下一期收益，在估值时点近似调仓；不等同于开盘执行台账"),
    ]
    for r, row in enumerate(entries, 1):
        params.write(r, 0, row[0], fmt["text"])
        params.write(r, 1, row[1], fmt["input"] if r < 4 else fmt["text"])
        params.write(r, 2, row[2], fmt["text"])
    n = len(spec.symbols)
    params.write_formula(4, 1, f"=SUM(B8:B{7 + n})", fmt["pct"], 1)
    for i, symbol in enumerate(spec.symbols):
        params.write(7 + i, 0, symbol, fmt["text"])
        params.write(7 + i, 1, spec.weights[i], fmt["weight"])
    params.data_validation("B2", {"validate": "decimal", "criteria": ">", "value": 0})
    params.data_validation("B3", {"validate": "decimal", "criteria": "between", "minimum": 0, "maximum": 100})
    params.data_validation("B4", {"validate": "list", "source": [0, 1, 3, 12]})
    params.data_validation(
        7, 1, 6 + n, 1, {"validate": "decimal", "criteria": "between", "minimum": 0, "maximum": 1}
    )

    daily = sheet(
        "Daily",
        [
            "Symbol",
            "Date",
            "Open",
            "High",
            "Low",
            "Close",
            "AdjClose",
            "Volume",
            "Opened UTC",
            "Closed UTC",
            "Dataset ID",
        ],
        {8: 30, 9: 30, 10: 30},
    )
    daily_index, r = {}, 1
    for symbol, dataset in bundle.datasets.items():
        for bar in dataset.bars:
            daily_index[(symbol, bar.date)] = r + 1
            daily.write_row(
                r,
                0,
                [
                    symbol,
                    bar.date,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.adj_close,
                    bar.volume,
                    bar.opened_at,
                    bar.closed_at,
                    dataset.id,
                ],
            )
            r += 1
    daily.autofilter(0, 0, r - 1, 10)

    anchors = (
        bundle.comparison.get("anchors", [])
        if len(spec.symbols) > 1
        else month_end_anchors(bundle.datasets, spec.symbols, spec.start, spec.end)
    )
    approximation = monthly_formula_backtest(anchors, spec)
    monthly = sheet(
        "Monthly", ["估值日期", "估值 UTC", *spec.symbols, *[f"{s} 实际日线" for s in spec.symbols]], {1: 30}
    )
    for i, anchor in enumerate(anchors, 1):
        monthly.write(i, 0, anchor["date"])
        monthly.write(i, 1, anchor["at"])
        for j, symbol in enumerate(spec.symbols):
            actual = anchor["actual"][symbol]
            monthly.write_formula(
                i,
                2 + j,
                f"=Daily!G{daily_index[(symbol, actual['date'])]}",
                fmt["number"],
                anchor["prices"][symbol],
            )
            monthly.write(i, 2 + n + j, actual["closed_at"])

    headers = [
        "估值日期",
        *[f"{s} 调仓前" for s in spec.symbols],
        "费用前资产",
        "再平衡",
        "成交额近似",
        "费用",
        "净资产",
        *[f"{s} 调仓后" for s in spec.symbols],
        "历史峰值",
        "回撤",
        "期间收益",
        "Python 初始校验",
        "初始参数差额",
    ]
    calc = sheet("MonthlyCalc", headers)
    gross, reb, turnover, fee, nav, post = n + 1, n + 2, n + 3, n + 4, n + 5, n + 6
    peak, dd, ret, baseline, delta = post + n, post + n + 1, post + n + 2, post + n + 3, post + n + 4

    def ref(c, row):
        return f"{col(c)}{row}"

    for i, data in enumerate(approximation["rows"], 1):
        er = i + 1
        calc.write_formula(i, 0, f"=Monthly!A{er}", None, data["date"])
        previous_values = (
            approximation["rows"][i - 2]["values"]
            if i > 1
            else [spec.initial_capital * w for w in spec.weights]
        )
        for j in range(n):
            formula = (
                f"=Parameters!$B$2*Parameters!$B${8 + j}"
                if i == 1
                else f"={ref(post + j, er - 1)}*Monthly!{col(2 + j)}{er}/Monthly!{col(2 + j)}{er - 1}"
            )
            calc.write_formula(i, 1 + j, formula, fmt["number"], previous_values[j] * data["growth"][j])
        calc.write_formula(i, gross, f"=SUM(B{er}:{col(n)}{er})", fmt["number"], data["gross"])
        calc.write_formula(
            i,
            reb,
            "=TRUE()" if i == 1 else f"=IF(Parameters!$B$4=0,FALSE(),MOD({i - 1},Parameters!$B$4)=0)",
            None,
            data["rebalance"],
        )
        tf = (
            f"={ref(gross, er)}"
            if i == 1
            else "="
            + "+".join(f"ABS({ref(gross, er)}*Parameters!$B${8 + j}-{ref(1 + j, er)})" for j in range(n))
        )
        calc.write_formula(
            i,
            turnover,
            tf,
            fmt["number"],
            data["cost"] / (spec.cost_bps / 10000) if data["rebalance"] and spec.cost_bps else 0,
        )
        calc.write_formula(
            i,
            fee,
            f"=IF({ref(reb, er)},{ref(turnover, er)}*Parameters!$B$3/10000,0)",
            fmt["number"],
            data["cost"],
        )
        calc.write_formula(
            i,
            nav,
            f"=IF(ABS(Parameters!$B$5-1)>0.00000001,NA(),{ref(gross, er)}-{ref(fee, er)})",
            fmt["number"],
            data["nav"],
        )
        for j in range(n):
            calc.write_formula(
                i,
                post + j,
                f"=IF({ref(reb, er)},{ref(nav, er)}*Parameters!$B${8 + j},{ref(j + 1, er)})",
                fmt["number"],
                data["values"][j],
            )
        peak_value = max(spec.initial_capital, max(r["nav"] for r in approximation["rows"][:i]))
        calc.write_formula(
            i, peak, f"=MAX(Parameters!$B$2,{col(nav)}$2:{ref(nav, er)})", fmt["number"], peak_value
        )
        calc.write_formula(i, dd, f"={ref(nav, er)}/{ref(peak, er)}-1", fmt["pct"], data["drawdown"])
        calc.write_formula(
            i,
            ret,
            f"={ref(nav, er)}/" + ("Parameters!$B$2" if i == 1 else ref(nav, er - 1)) + "-1",
            fmt["pct"],
            data["nav"] / (spec.initial_capital if i == 1 else approximation["rows"][i - 2]["nav"]) - 1,
        )
        calc.write(i, baseline, data["nav"], fmt["number"])
        calc.write_formula(i, delta, f"={ref(nav, er)}-{ref(baseline, er)}", fmt["ok"], 0)
    end = len(anchors) + 1
    if anchors:
        overview.write("A16", "月度近似期末净资产", fmt["text"])
        overview.write_formula(
            "B16", f"=MonthlyCalc!{ref(nav, end)}", fmt["number"], approximation["rows"][-1]["nav"]
        )
        overview.write("A17", "累计收益（含初始费用）", fmt["text"])
        overview.write_formula(
            "B17", "=B16/Parameters!B2-1", fmt["pct"], approximation["metrics"]["total_return"]
        )
        overview.write("A18", "最大回撤", fmt["text"])
        overview.write_formula(
            "B18",
            f"=MIN(MonthlyCalc!{col(dd)}2:{col(dd)}{end})",
            fmt["pct"],
            approximation["metrics"]["max_drawdown"],
        )
        overview.write("A19", "公式 / Python 初始差额", fmt["text"])
        overview.write_formula(
            "B19",
            f"=MAX(MonthlyCalc!{col(delta)}2:{col(delta)}{end})-MIN(MonthlyCalc!{col(delta)}2:{col(delta)}{end})",
            fmt["ok"],
            0,
        )
        overview.merge_range(
            "A21:E22",
            "初始参数差额用于核对交付时默认参数。修改参数后差额变化是预期现象。Sources 与 EventWindows 保留原始链接和对应交易窗口。",
            fmt["text"],
        )
        chart = book.add_chart({"type": "line"})
        chart.add_series(
            {
                "name": "月度配置近似",
                "categories": ["MonthlyCalc", 1, 0, end - 1, 0],
                "values": ["MonthlyCalc", 1, nav, end - 1, nav],
                "line": {"color": "#547B5B", "width": 2},
            }
        )
        chart.set_title({"name": "可重算的配置净资产"})
        chart.set_legend({"none": True})
        chart.set_size({"width": 830, "height": 330})
        overview.insert_chart("A34", chart)

    trades = sheet(
        "ExecutionLedger",
        [
            "Symbol",
            "Signal UTC",
            "Execution UTC",
            "Adjusted units",
            "Adjusted open",
            "Notional",
            "Cost",
            "Cash after",
        ],
        {1: 30, 2: 30},
    )
    for i, trade in enumerate(bundle.comparison.get("backtest", {}).get("trades", []), 1):
        trades.write_row(
            i,
            0,
            [
                trade[k]
                for k in [
                    "symbol",
                    "signal_at",
                    "executed_at",
                    "units",
                    "price",
                    "notional",
                    "cost",
                    "cash_after",
                ]
            ],
        )
    windows = sheet(
        "EventWindows",
        [
            "Event ID",
            "事件",
            "来源日期",
            "对齐交易日",
            "Symbol",
            "Window",
            "Return",
            "Benchmark",
            "Relative",
            "Strength",
            "Confidence",
            "Source IDs",
            "说明",
            "Window start UTC",
            "Window end UTC",
        ],
        {0: 32, 1: 55, 11: 40, 12: 80, 13: 30, 14: 30},
    )
    r = 1
    for annotation in bundle.annotations:
        event = next(e for e in bundle.events if e.id == annotation["event_id"])
        for window in annotation["windows"]:
            windows.write_row(
                r,
                0,
                [
                    event.id,
                    event.title,
                    str(event.date),
                    annotation["date"],
                    annotation["symbol"],
                    window["days"],
                    window.get("return"),
                    window.get("benchmark_return"),
                    window.get("relative_return"),
                    annotation["rating"],
                    annotation["confidence"],
                    ", ".join(event.source_ids),
                    annotation["uncertainty"],
                    window.get("start_closed_at"),
                    window.get("end_closed_at"),
                ],
            )
            r += 1
    sources = sheet(
        "Sources",
        ["ID", "Title", "Original URL", "Retrieved UTC", "SHA-256", "Status"],
        {0: 34, 1: 65, 2: 85, 3: 30, 4: 70},
    )
    records = [(s.id, s.title, s.url, s.retrieved_at, s.content_hash, s.status) for s in bundle.sources]
    records.extend(
        (d.id, s, d.source_url, d.retrieved_at, d.content_hash, d.price_basis)
        for s, d in bundle.datasets.items()
    )
    for i, row in enumerate(records, 1):
        sources.write_row(i, 0, row)
        if allowed_link(row[2]):
            sources.write_url(i, 2, row[2], string=row[2])
    macro = sheet("Macro", ["Series", "Observation date", "Value", "Vintage use"], {3: 60})
    r = 1
    for series, points in bundle.comparison.get("macro", {}).items():
        for point in points:
            macro.write_row(r, 0, [series, point["date"], point["value"], "当前历史版本，仅用于事后分析"])
            r += 1
    quality = sheet("Coverage", ["检查项", "状态", "依据 / 缺口"], {0: 40, 1: 20, 2: 95})
    quality.write_row(
        1,
        0,
        [
            "研究要求覆盖",
            "通过" if bundle.quality.get("passed") else "部分完成",
            "覆盖检查与事实核验分别执行；相关不代表因果",
        ],
    )
    r = 2
    for item in bundle.quality.get("requirements", []):
        quality.write_row(
            r, 0, [item["requirement"], item["status"], ", ".join(item["event_ids"])], fmt["text"]
        )
        r += 1
    for item in bundle.quality.get("repair_actions", []):
        quality.write_row(r, 0, [item["query"], "尚有缺口", item["reason"]], fmt["text"])
        r += 1
    links = sheet(
        "Associations",
        ["异动日期", "资产", "事件 ID", "滞后日线数", "关联类型", "依据", "来源 ID"],
        {2: 35, 4: 30, 5: 85, 6: 45},
    )
    r = 1
    for change in bundle.changes:
        for link in change.get("associations", []):
            links.write_row(
                r,
                0,
                [
                    change["date"],
                    change["symbol"],
                    link["event_id"],
                    link["lag_bars"],
                    link["relation"],
                    link["reason"],
                    ", ".join(link["source_ids"]),
                ],
                fmt["text"],
            )
            r += 1
    sensitivity = bundle.comparison.get("sensitivity", {})
    if sensitivity:
        ws = sheet(
            "Sensitivity",
            [
                "情景",
                "开始",
                "结束",
                "权重",
                "成本 bps",
                "再平衡月数",
                "年化收益",
                "最大回撤",
                "年化波动",
                "累计费用 USD",
                "数据 ID",
            ],
            {0: 28, 3: 22, 10: 70},
        )
        for r, row in enumerate(sensitivity["rows"], 1):
            ws.write_row(
                r,
                0,
                [
                    row["label"],
                    row["start"],
                    row["end"],
                    str(row["weights"]),
                    row["cost_bps"],
                    row["rebalance_months"],
                ],
            )
            for c, key in enumerate(["cagr", "max_drawdown", "volatility"], 6):
                ws.write(r, c, row[key], fmt["pct"])
            ws.write(r, 9, row["total_cost"], fmt["number"])
            ws.write(r, 10, ", ".join(sensitivity["dataset_ids"]))
        ws.merge_range(
            len(sensitivity["rows"]) + 3,
            0,
            len(sensitivity["rows"]) + 5,
            10,
            sensitivity["method"] + sensitivity["caveat"],
            fmt["text"],
        )
    book.close()
