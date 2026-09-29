"""Small numeric catalogue for prose: every value carries its calculation context."""

import math

from .research_contract import ResearchMetric

# Units are storage units, not a guess from the value. Ratios are stored as 0.01,
# basis points as 1, and counts as integers. Unknown numeric fields fail closed.
METRIC_DEFINITIONS = {
    "total_return": ("percent", "累计收益", "区间末值除以初值减一；不能与年化收益混用"),
    "cagr": ("percent", "年化收益", "按实际区间长度换算的复合年化收益率"),
    "volatility": ("percent", "年化波动", "收益标准差乘以年化换算周期数的平方根"),
    "max_drawdown": ("percent", "最大回撤", "相对历史高点的最深跌幅，使用带符号负值"),
    "return": ("percent", "窗口收益", "指定窗口末值除以初值减一"),
    "relative_return": ("percent", "相对基准收益", "标的收益减基准收益；不是事件因果效应"),
    "benchmark_return": ("percent", "基准收益", "与标的相同窗口的基准收益"),
    "standardized_response": ("number", "标准化反应幅度", "相对收益除以事前波动，不是百分比"),
    "bars": ("integer", "完整日线数", "实际已闭合日线条数；不是月度或收益观测数"),
    "volume": ("integer", "成交量", "数据源报告的该日成交量，具体交易单位以数据源为准"),
    "open": ("usd", "开盘价", "美元开盘价，复权口径见 method"),
    "high": ("usd", "最高价", "美元最高价，复权口径见 method"),
    "low": ("usd", "最低价", "美元最低价，复权口径见 method"),
    "close": ("usd", "收盘价", "美元收盘价，复权口径见 method"),
    "observations": ("integer", "估值观测数", "价格或净值的估值锚点数；不是相邻收益观测数"),
    "return_observations": ("integer", "收益观测数", "连续估值锚点间的收益数量，等于估值观测数减一"),
    "frequency": (
        "integer",
        "年化换算周期数",
        "年化换算所用的每年估值周期数；月度为12，不是交易或再平衡次数",
    ),
    "sharpe_proxy": ("number", "夏普代理", "超额收益均值与标准差之比的年化代理；无量纲"),
    "cost_bps": ("bps", "单边交易成本", "以基点存储，1 bps 等于0.01%；不再乘100"),
    "rebalance_months": ("integer", "再平衡间隔月数", "每隔多少个月再平衡；0代表买入持有，不是年化因子"),
    "anchors": ("integer", "共同估值锚点数", "各资产共同月末估值数，不能替代CPI配对样本数"),
    "threshold": ("percent", "高通胀分组阈值", "按CPI同比水平分组的阈值，不是资产收益"),
    "high_inflation_n": ("integer", "高通胀配对样本数", "CPI同比和资产月收益均可用且达到阈值的月份数"),
    "low_inflation_n": ("integer", "低通胀配对样本数", "CPI同比和资产月收益均可用且低于阈值的月份数"),
    "high_inflation_mean_return": ("percent", "高通胀月平均收益", "高通胀配对月份的资产收益算术均值"),
    "low_inflation_mean_return": ("percent", "低通胀月平均收益", "低通胀配对月份的资产收益算术均值"),
    "inflation_correlation": ("number", "通胀相关系数", "资产月收益与CPI同比水平的皮尔逊相关系数，无量纲"),
    "stress_n": ("integer", "压力月份数", "事后选出的基准最差月份数量"),
    "stress_positive_months": ("integer", "压力期正收益月份数", "压力样本中资产收益严格大于零的月份数"),
    "positive_months": ("integer", "正收益月份数", "同一压力样本中资产收益严格大于零的月份数"),
    "outperform_months": ("integer", "跑赢基准月份数", "同一压力样本中资产收益严格大于基准收益的月份数"),
    "not_outperform_months": ("integer", "未跑赢基准月份数", "同一压力样本中收益小于或等于基准的月份数"),
}


def metric_catalog(bundle):
    result = {}
    spec, comparison = bundle.spec, bundle.comparison
    ids = [bundle.datasets[s].id for s in spec.symbols]
    labels = {
        "total_return": "累计收益",
        "cagr": "年化收益",
        "volatility": "年化波动",
        "max_drawdown": "最大回撤",
        "return": "收益",
        "relative_return": "相对基准收益",
        "benchmark_return": "基准收益",
        "standardized_response": "标准化反应幅度",
    }

    def add(prefix, values, start, end, frequency, method, group, sources, definitions=None):
        for key, value in values.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                continue
            mid = f"{prefix}.{key}"
            definition = (definitions or {}).get(key, METRIC_DEFINITIONS.get(key))
            if definition is None:
                raise ValueError(f"指标缺少显式单位与含义契约：{mid}")
            unit, label, meaning = definition
            result[mid] = ResearchMetric(
                id=mid,
                label=f"{prefix} · {label}",
                value=float(value),
                unit=unit,
                meaning=meaning,
                start=start,
                end=end,
                frequency=frequency,
                method=method,
                comparison_group=group,
                dataset_ids=sources,
            )

    for symbol in spec.symbols:
        ds = bundle.datasets[symbol]
        bars = [b for b in ds.bars if str(spec.start) <= b.date <= str(spec.end)]
        if not bars:
            continue
        add(
            f"market.{symbol}",
            {"bars": len(bars)},
            bars[0].date,
            bars[-1].date,
            "日线",
            ds.price_basis,
            "coverage",
            [ds.id],
        )
        add(
            f"latest.{symbol}",
            {k: getattr(bars[-1], k) for k in ["open", "high", "low", "close", "volume"]},
            bars[-1].date,
            bars[-1].date,
            "日线",
            ds.price_basis,
            "ohlcv",
            [ds.id],
        )
    for metric in bundle.metrics:
        if metric["id"].startswith("performance-"):
            add(
                f"daily.{metric['symbol']}",
                {k: metric[k] for k in labels if k in metric},
                metric["start"],
                metric["end"],
                "日线",
                "复权价格回顾，无交易费用",
                "daily",
                metric["dataset_ids"],
            )
    for annotation in bundle.annotations:
        for window in annotation["windows"]:
            if window.get("complete"):
                add(
                    f"event.{annotation['event_id']}.{annotation['symbol']}.{window['days']}",
                    {k: window[k] for k in labels if k in window},
                    window["start"],
                    window["end"],
                    f"{window['days']} 根完整日线",
                    "事件窗口；相对收益为标的减基准，非因果效应",
                    "event",
                    annotation["dataset_ids"],
                )
        alternative = annotation.get("date_sensitivity") or {}
        for window in alternative.get("windows", []):
            if window.get("complete"):
                add(
                    f"next-session.{annotation['event_id']}.{annotation['symbol']}.{window['days']}",
                    {k: window[k] for k in labels if k in window},
                    window["start"],
                    window["end"],
                    f"{window['days']} 根完整日线",
                    "日期不明盘前盘后时，下一交易日起算的敏感性窗口",
                    "event",
                    annotation["dataset_ids"],
                )
    for change in sorted(bundle.changes, key=lambda c: c.get("strength", 0), reverse=True)[:5]:
        add(
            f"move.{change['id']}",
            {"return": change["return"]},
            change["date"],
            change["date"],
            "后续五日" if change["type"] == "回升拐点" else "一日",
            change.get("note", "复权收盘到收盘"),
            "event",
            [change["dataset_id"]],
        )
    if not comparison.get("available"):
        return result
    anchors = comparison["anchors"]
    start, end = anchors[0]["date"], anchors[-1]["date"]
    execution = "共同月末估值，信号后下一可交易开盘执行，含指定交易费用与现金余额"
    for name, test in {
        "portfolio": comparison["backtest"],
        **comparison.get("execution_baselines", {}),
    }.items():
        add(
            f"execution.{name}",
            {**test["metrics"], "return_observations": max(0, test["metrics"]["observations"] - 1)},
            start,
            end,
            "共同月度",
            execution,
            "execution",
            ids,
        )
    add(
        "config",
        {
            "cost_bps": spec.cost_bps,
            "rebalance_months": spec.rebalance_months,
            "anchors": len(anchors),
            **{f"weight_{s}": w for s, w in zip(spec.symbols, spec.weights)},
        },
        start,
        end,
        "共同月度",
        execution,
        "config",
        ids,
        {
            f"weight_{s}": ("percent", f"{s}配置权重", "事前设定的目标权重，不是事后最优比例")
            for s in spec.symbols
        },
    )
    for row in comparison["asset_metrics"]:
        add(
            f"monthly.{row['symbol']}",
            {**row, "return_observations": max(0, row["observations"] - 1)},
            start,
            end,
            "共同月度",
            "复权价格，无交易费用",
            "monthly-price",
            ids,
        )
    for row in comparison.get("inflation_summary", []):
        symbol = row["symbol"]
        add(
            f"inflation.{symbol}",
            {**row, "n": row["high_inflation_n"] + row["low_inflation_n"]},
            start,
            end,
            "共同月度",
            "月度资产收益与 CPI 同比水平的关系；不是价格水平或通胀变动；当前历史版本仅作回顾，非当时已知交易信号",
            "inflation",
            [*ids, "fred-CPIAUCNS"],
            {
                "n": (
                    "integer",
                    "CPI有效配对样本数",
                    "CPI同比与资产收益同时可用的配对月份数；等于高低分组样本数之和",
                ),
            },
        )
        stress = comparison["stress_periods"]
        add(
            f"stress.{symbol}",
            {
                "positive_months": sum(r["returns"][symbol] > 0 for r in stress),
                "outperform_months": sum(r["returns"][symbol] > r["benchmark_return"] for r in stress),
                "not_outperform_months": sum(r["returns"][symbol] <= r["benchmark_return"] for r in stress),
                "n": len(stress),
            },
            start,
            end,
            "共同月度",
            "事后选取基准最差月份；跑赢基准不等于保本",
            "stress",
            [*ids, bundle.datasets[spec.benchmark].id],
            {"n": ("integer", "压力样本月份数", "事后选取的压力月份数量；不是全区间收益样本数")},
        )
    for row in comparison.get("stress_periods", []):
        add(
            f"stress-month.{row['date']}",
            {**row["returns"], spec.benchmark: row["benchmark_return"]},
            row["date"],
            row["date"],
            "共同月度",
            "事后选取基准最差月份的同期收益",
            "stress",
            [*ids, bundle.datasets[spec.benchmark].id],
            {
                s: ("percent", f"{s}压力月收益", "指定压力月份的资产收益，正收益与跑赢基准分别判断")
                for s in [*spec.symbols, spec.benchmark]
            },
        )
    for series in comparison.get("series", []):
        valid = [(d, v) for d, v in zip(series["dates"], series["real"]) if v is not None]
        if len(valid) > 1:
            add(
                f"real.{series['symbol']}",
                {"total_return": valid[-1][1] / valid[0][1] - 1},
                valid[0][0],
                valid[-1][0],
                "共同月度",
                "复权价格/CPI购买力回顾，无额外交易费用",
                "real-price",
                [*ids, "fred-CPIAUCNS"],
            )
    for i, row in enumerate(comparison.get("correlations", [])):
        add(
            f"correlation.{row['x']}.{row['y']}",
            {"value": row["value"], "n": row["n"]},
            start,
            end,
            "共同月度",
            "两资产月度收益的样本皮尔逊相关性；不是价格水平相关性",
            "correlation",
            ids,
            {
                "value": ("number", "资产收益相关系数", "两资产配对收益的皮尔逊相关系数，无量纲"),
                "n": ("integer", "资产相关性配对样本数", "两资产收益同时可用的配对数量；不能用于CPI相关性"),
            },
        )
    for i, row in enumerate(comparison.get("sensitivity", {}).get("rows", [])):
        add(
            f"sensitivity.{i}",
            {
                **{k: row[k] for k in [*labels, "cost_bps", "rebalance_months"] if k in row},
                **{f"weight_{s}": w for s, w in zip(spec.symbols, row["weights"])},
            },
            row["start"],
            row["end"],
            "共同月度",
            f"{execution}；情景 {row['label']}",
            "sensitivity",
            ids,
            {
                f"weight_{s}": ("percent", f"{s}情景权重", "敏感性分析的目标权重，不是事后最优比例")
                for s in spec.symbols
            },
        )
    return result


def display_metric(metric):
    if metric.unit == "percent":
        return f"{metric.value:.2%}"
    if metric.unit == "bps":
        return f"{metric.value:g} bps"
    if metric.unit == "integer":
        return f"{metric.value:,.0f}"
    if metric.unit == "usd":
        return f"{metric.value:,.2f} 美元"
    return f"{metric.value:.3f}".rstrip("0").rstrip(".")
