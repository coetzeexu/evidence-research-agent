"""Small numeric catalogue for prose: every value carries its calculation context."""

import math

from .research_contract import ResearchMetric


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

    def add(prefix, values, start, end, frequency, method, group, sources, units=None):
        for key, value in values.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                continue
            mid = f"{prefix}.{key}"
            result[mid] = ResearchMetric(
                id=mid,
                label=f"{prefix} · {labels.get(key, key)}",
                value=float(value),
                unit=(units or {}).get(key, "percent"),
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
            {"bars": "integer"},
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
            {"open": "usd", "high": "usd", "low": "usd", "close": "usd", "volume": "integer"},
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
                    {"standardized_response": "number"},
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
                    {"standardized_response": "number"},
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
            test["metrics"],
            start,
            end,
            "共同月度",
            execution,
            "execution",
            ids,
            {"observations": "integer", "sharpe_proxy": "number"},
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
        {"cost_bps": "bps", "rebalance_months": "integer", "anchors": "integer"},
    )
    for row in comparison["asset_metrics"]:
        add(
            f"monthly.{row['symbol']}",
            row,
            start,
            end,
            "共同月度",
            "复权价格，无交易费用",
            "monthly-price",
            ids,
            {"sharpe_proxy": "number", "observations": "integer"},
        )
    for row in comparison.get("inflation_summary", []):
        symbol = row["symbol"]
        add(
            f"inflation.{symbol}",
            row,
            start,
            end,
            "共同月度",
            "月度资产收益与 CPI 同比水平的关系；不是价格水平或通胀变动；当前历史版本仅作回顾，非当时已知交易信号",
            "inflation",
            [*ids, "fred-CPIAUCNS"],
            {
                "high_inflation_n": "integer",
                "low_inflation_n": "integer",
                "stress_n": "integer",
                "stress_positive_months": "integer",
                "inflation_correlation": "number",
            },
        )
        stress = comparison["stress_periods"]
        add(
            f"stress.{symbol}",
            {
                "positive_months": sum(r["returns"][symbol] > 0 for r in stress),
                "outperform_months": sum(r["returns"][symbol] > r["benchmark_return"] for r in stress),
                "n": len(stress),
            },
            start,
            end,
            "共同月度",
            "事后选取基准最差月份；跑赢基准不等于保本",
            "stress",
            [*ids, bundle.datasets[spec.benchmark].id],
            {"positive_months": "integer", "outperform_months": "integer", "n": "integer"},
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
            {"value": "number", "n": "integer"},
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
            {"cost_bps": "bps", "rebalance_months": "integer"},
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
