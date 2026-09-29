"""Versioned, deterministic calculations; no model-generated arithmetic."""

import calendar
import math
from bisect import bisect_right
from datetime import date, datetime, timedelta

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from .domain import (
    GLD_DISCLOSURE,
    Claim,
    EventRecord,
    MarketDataset,
    ResearchBundle,
    ResearchSpec,
    SourceRecord,
    now_iso,
)


def finite(value) -> float | None:
    return float(value) if value is not None and math.isfinite(float(value)) else None


def frame(dataset: MarketDataset) -> pd.DataFrame:
    rows = [b.model_dump() for b in dataset.bars]
    result = pd.DataFrame(rows).set_index("date")
    result.index = pd.to_datetime(result.index)
    return result.sort_index()


def performance(values: list[float], dates: list[str], periods: int) -> dict:
    if len(values) < 2:
        return {
            "total_return": None,
            "cagr": None,
            "volatility": None,
            "max_drawdown": None,
            "observations": len(values),
            "frequency": periods,
        }
    prices = np.asarray(values, dtype=float)
    returns = prices[1:] / prices[:-1] - 1
    years = (date.fromisoformat(dates[-1][:10]) - date.fromisoformat(dates[0][:10])).days / 365.25
    drawdowns = prices / np.maximum.accumulate(prices) - 1
    return {
        "total_return": float(prices[-1] / prices[0] - 1),
        "cagr": float((prices[-1] / prices[0]) ** (1 / years) - 1) if years > 0 else None,
        "volatility": float(np.std(returns, ddof=1) * math.sqrt(periods)) if len(returns) > 1 else None,
        "max_drawdown": float(np.min(drawdowns)),
        "observations": len(values),
        "frequency": periods,
    }


def detect_changes(dataset: MarketDataset, start: date, end: date, maximum: int = 18) -> list[dict]:
    data = frame(dataset).loc[: str(end)]
    returns = data.adj_close.pct_change()
    historical_vol = returns.rolling(63, min_periods=40).std().shift(1)
    z = returns / historical_vol.replace(0, np.nan)
    volume_ratio = data.volume / data.volume.rolling(20, min_periods=15).median().shift(1).replace(0, np.nan)
    trend = data.adj_close.pct_change(20)
    acceleration = trend - trend.shift(10)
    candidates = []
    eligible = data.loc[str(start) : str(end)]
    for stamp in eligible.index:
        score = abs(z.get(stamp, np.nan))
        if not math.isfinite(score) or score < 1.6:
            continue
        ret = float(returns.loc[stamp])
        candidates.append(
            {
                "id": f"change-{dataset.instrument.symbol}-{stamp.date()}",
                "symbol": dataset.instrument.symbol,
                "date": str(stamp.date()),
                "confirmed_at": data.loc[stamp, "closed_at"],
                "type": "上涨" if ret > 0 else "下跌",
                "return": ret,
                "strength": float(score),
                "volume_ratio": finite(volume_ratio.loc[stamp]),
                "acceleration_20d": finite(acceleration.loc[stamp]),
                "dataset_id": dataset.id,
                "event_ids": [],
            }
        )
    selected = []
    for candidate in sorted(candidates, key=lambda c: c["strength"], reverse=True):
        day = date.fromisoformat(candidate["date"])
        if all(abs((day - date.fromisoformat(row["date"])).days) > 5 for row in selected):
            selected.append(candidate)
        if len(selected) >= maximum:
            break
    # Reversal candidates require later observations; confirmation time is explicit.
    prices = data.adj_close.to_numpy()
    for i in range(5, len(data) - 5):
        stamp = data.index[i]
        if not (start <= stamp.date() <= end):
            continue
        local = prices[i - 5 : i + 6]
        if prices[i] == np.min(local) and prices[i + 5] / prices[i] - 1 >= 0.06:
            if all(abs((stamp.date() - date.fromisoformat(row["date"])).days) > 8 for row in selected):
                selected.append(
                    {
                        "id": f"turn-{dataset.instrument.symbol}-{stamp.date()}",
                        "symbol": dataset.instrument.symbol,
                        "date": str(stamp.date()),
                        "confirmed_at": data.iloc[i + 5].closed_at,
                        "type": "回升拐点",
                        "return": float(prices[i + 5] / prices[i] - 1),
                        "strength": 0,
                        "volume_ratio": finite(volume_ratio.iloc[i]),
                        "dataset_id": dataset.id,
                        "event_ids": [],
                        "note": "使用后续五个交易日确认，仅用于回顾标注",
                    }
                )
                if len(selected) >= maximum + 5:
                    break
    return sorted(selected, key=lambda c: c["date"])


def event_windows(
    event: EventRecord,
    dataset: MarketDataset,
    benchmark: MarketDataset,
    windows: list[int],
    end: date | None = None,
    _date_alternative: bool = False,
) -> dict | None:
    bars = [b for b in dataset.bars if end is None or b.date <= str(end)]
    idx = next((i for i, bar in enumerate(bars) if bar.date >= str(event.date)), None)
    if idx is None or idx == 0:
        return None
    uncertainty = event.uncertainty
    if event.published_at:
        try:
            published = datetime.fromisoformat(event.published_at.replace("Z", "+00:00"))
            if published.tzinfo is None:
                raise ValueError("Publication timezone absent")
            idx = next(
                (i for i, bar in enumerate(bars) if datetime.fromisoformat(bar.closed_at) > published), None
            )
            if idx is None or idx == 0:
                return None
            if datetime.fromisoformat(bars[idx].opened_at) < published:
                uncertainty += " 日线包含公告前交易，无法精确隔离盘中反应。"
        except ValueError:
            uncertainty += " 发布时间缺少有效时区，按日期近似对齐。"
    else:
        uncertainty += " 来源只有日期，盘前/盘后时间不确定；使用当日或下一交易日近似。"
    before = bars[idx - 1]
    bench_bars = benchmark.bars
    bench_times = [datetime.fromisoformat(b.closed_at) for b in bench_bars]

    def bench_at(stamp: str):
        at = datetime.fromisoformat(stamp)
        j = bisect_right(bench_times, at) - 1
        return (
            bench_bars[j].adj_close if j >= 0 and (at - bench_times[j]).total_seconds() <= 96 * 3600 else None
        )

    history = np.array([b.adj_close for b in bars[max(0, idx - 64) : idx]])
    historical_sigma = np.std(history[1:] / history[:-1] - 1, ddof=1) if len(history) >= 41 else None
    past_vol = np.median([b.volume for b in bars[max(0, idx - 20) : idx]])
    results = []
    for width in windows:
        j = idx + width - 1
        if j >= len(bars):
            results.append(
                {
                    "days": width,
                    "complete": False,
                    "return": None,
                    "relative_return": None,
                    "reason": "窗口尚未满",
                }
            )
            continue
        finish = bars[j]
        ret = finish.adj_close / before.adj_close - 1
        bench_start, bench_end = bench_at(before.closed_at), bench_at(finish.closed_at)
        bench_return = bench_end / bench_start - 1 if bench_start and bench_end else None
        relative = ret - bench_return if bench_return is not None else None
        # This is a descriptive standardized response, not a calibrated test statistic or probability.
        strength = (
            abs(relative) / (historical_sigma * math.sqrt(width))
            if (relative is not None and historical_sigma and historical_sigma > 0)
            else None
        )
        results.append(
            {
                "days": width,
                "complete": True,
                "start": before.date,
                "end": finish.date,
                "start_closed_at": before.closed_at,
                "end_closed_at": finish.closed_at,
                "return": float(ret),
                "benchmark_return": finite(bench_return),
                "relative_return": finite(relative),
                "standardized_response": finite(strength),
            }
        )
    primary = next(
        (w for w in results if w["days"] == 5 and w["complete"]),
        next((w for w in results if w["complete"]), None),
    )
    strength = primary.get("standardized_response") if primary else None
    rating = "不可评估" if strength is None else "高" if strength >= 2 else "中" if strength >= 1 else "低"
    reaction = primary.get("relative_return") if primary else None
    confidence = event.confidence
    if event.time_precision != "timestamp" and confidence == "high":
        confidence = "medium"
    output = {
        "id": f"association-{event.id}-{dataset.instrument.symbol}",
        "event_id": event.id,
        "symbol": dataset.instrument.symbol,
        "date": bars[idx].date,
        "price": bars[idx].close,
        "rating": rating,
        "confidence": confidence,
        "direction": "上涨"
        if reaction and reaction > 0
        else "下跌"
        if reaction and reaction < 0
        else "不明显",
        "direction_window_days": primary["days"] if primary else None,
        "volume_ratio": bars[idx].volume / past_vol if past_vol > 0 else None,
        "windows": results,
        "uncertainty": uncertainty.strip(),
        "metric_id": f"event-window-{event.id}-{dataset.instrument.symbol}",
        "dataset_ids": [dataset.id, benchmark.id],
    }
    if not event.published_at and event.timing_basis != "retrospective" and not _date_alternative:
        following = bars[idx + 1] if idx + 1 < len(bars) else None
        if following:
            shifted = event.model_copy(
                update={"date": date.fromisoformat(following.date), "public_disclosure_at": None}
            )
            alternative = event_windows(shifted, dataset, benchmark, windows, end, _date_alternative=True)
            if alternative:
                output["date_sensitivity"] = {
                    "date": alternative["date"],
                    "windows": alternative["windows"],
                    "rating": alternative["rating"],
                    "direction": alternative["direction"],
                    "reason": "盘前/盘后未知，比较当日与下一交易日起算；两者均非精确盘中因果效应",
                }
    return output


def month_end_anchors(
    datasets: dict[str, MarketDataset], symbols: list[str], start: date, end: date
) -> list[dict]:
    """Monthly common valuations use completed bars at or BEFORE an equity-close anchor."""
    primary = next(
        (datasets[s] for s in symbols if datasets[s].instrument.calendar != "24/7"), datasets[symbols[0]]
    )
    observed_through = min(datetime.fromisoformat(datasets[s].retrieved_at).date() for s in symbols)
    by_month = {}
    for bar in primary.bars:
        day = date.fromisoformat(bar.date)
        if start <= day <= end:
            by_month[bar.date[:7]] = bar
    lookup_times = {s: [datetime.fromisoformat(b.closed_at) for b in datasets[s].bars] for s in symbols}
    schedule = None
    if primary.instrument.calendar != "24/7":
        schedule = xcals.get_calendar(
            "XNYS", start=str(start.replace(day=1)), end=str(end + timedelta(days=31))
        )
    rows = []
    for month, anchor in sorted(by_month.items()):
        year, number = map(int, month.split("-"))
        last_calendar_day = date(year, number, calendar.monthrange(year, number)[1])
        if last_calendar_day > min(end, observed_through):
            continue
        expected_day = (
            schedule.date_to_session(str(last_calendar_day), direction="previous").date()
            if schedule is not None
            else last_calendar_day
        )
        if anchor.date != str(expected_day):
            continue
        stamp = datetime.fromisoformat(anchor.closed_at)
        prices, actual, valid = {}, {}, True
        for symbol in symbols:
            i = bisect_right(lookup_times[symbol], stamp) - 1
            if i < 0:
                valid = False
                break
            bar = datasets[symbol].bars[i]
            age = (stamp - datetime.fromisoformat(bar.closed_at)).total_seconds() / 3600
            if age > 96:
                valid = False
                break
            prices[symbol] = bar.adj_close
            actual[symbol] = {"date": bar.date, "closed_at": bar.closed_at, "age_hours": age}
        if valid:
            rows.append({"date": anchor.date, "at": anchor.closed_at, "prices": prices, "actual": actual})
    return rows


def portfolio_backtest(anchors: list[dict], spec: ResearchSpec, datasets: dict[str, MarketDataset]) -> dict:
    """Monthly decisions, next-bar-open execution, explicit positions/cash/trade ledger.

    Adjusted price units are used consistently; this is a total-return proxy with fractional units.
    Signals contain only fixed user weights and calendar rules, never future prices.
    """
    if len(anchors) < 3:
        return {"rows": [], "trades": [], "metrics": {}, "warnings": ["完整共同月份不足，无法回测"]}
    symbols = spec.symbols
    weights = dict(zip(symbols, spec.weights, strict=True))
    holdings = {s: 0.0 for s in symbols}
    cash = spec.initial_capital
    ledger, rows = [], []
    fee = spec.cost_bps / 10000
    pending = []
    for index, anchor in enumerate(anchors):
        at = datetime.fromisoformat(anchor["at"])
        fills = sorted(
            (t for t in pending if t["execution_at"] <= at),
            key=lambda t: (t["execution_at"], t["target_value"] > 0),
        )
        # Orders are sized from signal-time holdings and prices; sells precede buys at equal timestamps.
        for fill in fills:
            symbol, price = fill["symbol"], fill["price"]
            delta = fill["units"]
            if delta < 0:
                delta = max(delta, -holdings[symbol])
            else:
                delta = min(delta, max(0, cash) / (price * (1 + fee)))
            notional = delta * price
            cost = abs(notional) * fee
            cash -= notional + cost
            holdings[symbol] += delta
            ledger.append(
                {
                    "symbol": symbol,
                    "signal_at": fill["signal_at"],
                    "executed_at": fill["execution_at"].isoformat(),
                    "units": delta,
                    "price": price,
                    "notional": notional,
                    "cost": cost,
                    "cash_after": cash,
                }
            )
        pending = [t for t in pending if t["execution_at"] > at]
        values = {s: holdings[s] * anchor["prices"][s] for s in symbols}
        nav = cash + sum(values.values())
        rows.append(
            {
                "date": anchor["date"],
                "at": anchor["at"],
                "nav": nav,
                "cash": cash,
                "holdings": dict(holdings),
                "asset_values": values,
                "weights": {s: values[s] / nav for s in symbols},
            }
        )
        rebalance = index == 0 or (spec.rebalance_months > 0 and index % spec.rebalance_months == 0)
        if not rebalance or index == len(anchors) - 1:
            continue
        # Avoid over-allocation: reserve fees, and use only signal-time NAV in target sizing.
        deployable = nav / (1 + 2 * fee)
        for symbol in symbols:
            signal_price = anchor["prices"][symbol]
            delta = deployable * weights[symbol] / signal_price - holdings[symbol]
            future = next(
                (b for b in datasets[symbol].bars if datetime.fromisoformat(b.opened_at) > at), None
            )
            if future:
                adjusted_open = future.open * future.adj_close / future.close
                pending.append(
                    {
                        "symbol": symbol,
                        "signal_at": anchor["at"],
                        "execution_at": datetime.fromisoformat(future.opened_at),
                        "units": delta,
                        "price": adjusted_open,
                        "target_value": delta,
                    }
                )
    metrics = performance([r["nav"] for r in rows], [r["date"] for r in rows], 12)
    return {
        "rows": rows,
        "trades": ledger,
        "metrics": metrics,
        "warnings": [
            "按月末已知价格确定份额，下一可交易日开盘执行；跨市场成交时间不同，可能保留现金。",
            "使用可分割的复权价格单位模拟总回报，成本按成交额计；结果为历史配置模拟。",
        ],
    }


def monthly_formula_backtest(anchors: list[dict], spec: ResearchSpec) -> dict:
    """Recalculable close-to-close allocation worksheet, distinctly labelled from execution simulation.

    A rebalance decision at previous valuation applies to the NEXT interval. Costs deducted at that
    starting valuation. This conventional monthly approximation is shared verbatim with Excel formulas.
    """
    if not anchors:
        return {"rows": [], "metrics": {}}
    weights = np.asarray(spec.weights, dtype=float)
    capital = float(spec.initial_capital)
    values = capital * weights
    rows = []
    peak = capital
    previous_prices = np.array([anchors[0]["prices"][s] for s in spec.symbols])
    for i, anchor in enumerate(anchors):
        prices = np.array([anchor["prices"][s] for s in spec.symbols])
        growth = prices / previous_prices if i else np.ones(len(weights))
        before = values * growth
        gross = float(before.sum())
        rebalance = i == 0 or (spec.rebalance_months > 0 and i % spec.rebalance_months == 0)
        turnover = float(np.abs(gross * weights - before).sum()) if i else gross
        costs = turnover * spec.cost_bps / 10000 if rebalance else 0.0
        nav = gross - costs
        values = nav * weights if rebalance else before
        peak = max(peak, nav)
        rows.append(
            {
                "date": anchor["date"],
                "nav": nav,
                "gross": gross,
                "cost": costs,
                "rebalance": rebalance,
                "values": list(map(float, values)),
                "drawdown": nav / peak - 1,
                "growth": list(map(float, growth)),
            }
        )
        previous_prices = prices
    metrics = performance([r["nav"] for r in rows], [r["date"] for r in rows], 12)
    metrics["total_return"] = rows[-1]["nav"] / capital - 1
    years = (date.fromisoformat(rows[-1]["date"]) - date.fromisoformat(rows[0]["date"])).days / 365.25
    metrics["cagr"] = (rows[-1]["nav"] / capital) ** (1 / years) - 1 if years else None
    metrics["max_drawdown"] = min(r["drawdown"] for r in rows)
    return {
        "rows": rows,
        "metrics": metrics,
        "method": "月度估值配置近似；上期权重作用于下期收益，成交执行模拟另列",
    }


def compare(spec: ResearchSpec, datasets: dict[str, MarketDataset], macro: dict) -> dict:
    all_symbols = list(dict.fromkeys([*spec.symbols, spec.benchmark]))
    anchors = month_end_anchors(datasets, all_symbols, spec.start, spec.end)
    month_numbers = [int(r["date"][:4]) * 12 + int(r["date"][5:7]) for r in anchors]
    missing_months = any(b - a != 1 for a, b in zip(month_numbers, month_numbers[1:]))
    if len(anchors) < 3 or missing_months:
        return {
            "available": False,
            "anchors": [],
            "diagnostic_anchors": anchors,
            "warnings": [
                "缺失完整共同月份，无法按连续月度计算年化指标和回测；请检查行情覆盖。"
                if missing_months
                else "共同完整月度样本不足，至少需要三个连续月末锚点。"
            ],
            "series": [],
            "asset_metrics": [],
            "correlations": [],
            "stress_periods": [],
            "backtest": {},
            "formula_backtest": {},
        }
    prices = pd.DataFrame(
        [{s: r["prices"][s] for s in all_symbols} for r in anchors], index=[r["date"] for r in anchors]
    )
    returns = prices.pct_change().dropna()
    series, metrics = [], []
    cpi = {point["date"][:7]: point["value"] for point in macro.get("CPIAUCNS", [])}
    for symbol in spec.symbols:
        vals = prices[symbol].to_numpy()
        normal = vals / vals[0] * 100
        drawdown = vals / np.maximum.accumulate(vals) - 1
        real = []
        first_cpi = cpi.get(anchors[0]["date"][:7])
        for i, row in enumerate(anchors):
            current = cpi.get(row["date"][:7])
            real.append(float(normal[i] * first_cpi / current) if first_cpi and current else None)
        series.append(
            {
                "symbol": symbol,
                "dates": list(prices.index),
                "normalized": normal.tolist(),
                "drawdown": drawdown.tolist(),
                "real": real,
            }
        )
        metrics.append({"symbol": symbol, **performance(vals.tolist(), list(prices.index), 12)})
    correlations = []
    for x in spec.symbols:
        for y in spec.symbols:
            correlations.append(
                {"x": x, "y": y, "value": finite(returns[x].corr(returns[y])), "n": len(returns)}
            )
    rolling = {
        s: [finite(v) for v in returns[s].rolling(12, min_periods=12).corr(returns[spec.benchmark])]
        for s in spec.symbols
    }
    stress = []
    for stamp in returns[spec.benchmark].nsmallest(min(6, len(returns))).index:
        stress.append(
            {
                "date": stamp,
                "benchmark_return": float(returns.loc[stamp, spec.benchmark]),
                "returns": {s: float(returns.loc[stamp, s]) for s in spec.symbols},
                "selection": "全样本事后选择的基准最差月份",
            }
        )
    inflation = []
    for i in range(1, len(anchors)):
        month = anchors[i]["date"][:7]
        year, mon = map(int, month.split("-"))
        previous_year = f"{year - 1}-{mon:02d}"
        if month in cpi and previous_year in cpi:
            inflation.append(
                {
                    "date": anchors[i]["date"],
                    "yoy": cpi[month] / cpi[previous_year] - 1,
                    "returns": {s: float(returns.loc[anchors[i]["date"], s]) for s in spec.symbols},
                }
            )
    inflation_summary = []
    for symbol in spec.symbols:
        higher = [r for r in inflation if r["yoy"] >= 0.03]
        lower = [r for r in inflation if r["yoy"] < 0.03]
        inflation_summary.append(
            {
                "symbol": symbol,
                "threshold": 0.03,
                "high_inflation_n": len(higher),
                "low_inflation_n": len(lower),
                "high_inflation_mean_return": finite(np.mean([r["returns"][symbol] for r in higher]))
                if higher
                else None,
                "low_inflation_mean_return": finite(np.mean([r["returns"][symbol] for r in lower]))
                if lower
                else None,
                "inflation_correlation": finite(
                    pd.Series([r["returns"][symbol] for r in inflation]).corr(
                        pd.Series([r["yoy"] for r in inflation])
                    )
                )
                if len(inflation) >= 3
                else None,
                "stress_positive_months": sum(r["returns"][symbol] > 0 for r in stress),
                "stress_n": len(stress),
            }
        )
    rf_points = macro.get("DGS3MO", [])
    rf_returns = []
    for anchor in anchors[1:]:
        before = [r for r in rf_points if r["date"] < anchor["date"]]
        rf_returns.append((1 + before[-1]["value"] / 100) ** (1 / 12) - 1 if before else None)
    for metric in metrics:
        matched = [
            (r, rf) for r, rf in zip(returns[metric["symbol"]], rf_returns, strict=True) if rf is not None
        ]
        excess = np.array([r - rf for r, rf in matched])
        metric["sharpe_proxy"] = (
            float(excess.mean() / excess.std(ddof=1) * math.sqrt(12))
            if len(excess) > 2 and excess.std() > 0
            else None
        )
        metric["risk_free_method"] = "DGS3MO 年化收益率折月代理，当前历史版本，非现金工具总回报"
    return {
        "available": True,
        "anchors": anchors,
        "series": series,
        "asset_metrics": metrics,
        "correlations": correlations,
        "rolling_correlation": {"dates": list(returns.index), "values": rolling},
        "stress_periods": stress,
        "inflation": inflation,
        "inflation_summary": inflation_summary,
        "macro": macro,
        "backtest": portfolio_backtest(anchors, spec, datasets),
        "execution_baselines": {
            symbol: portfolio_backtest(
                anchors,
                ResearchSpec.model_validate(
                    {**spec.model_dump(), "weights": [float(s == symbol) for s in spec.symbols]}
                ),
                datasets,
            )
            for symbol in spec.symbols
        },
        "formula_backtest": monthly_formula_backtest(anchors, spec),
        "warnings": [
            "共同月度估值采用不晚于锚点的完整日线；各资产实际价格时间在底稿中保留。",
            "宏观序列采用当前历史版本，只用于事后解释；未用于交易信号。",
        ],
    }


def build_bundle(
    run_id: str,
    spec: ResearchSpec,
    datasets: dict[str, MarketDataset],
    sources: list[SourceRecord],
    events: list[EventRecord],
    macro: dict,
    coverage: list[dict],
    mode: str = "live",
) -> ResearchBundle:
    warnings = [w for ds in datasets.values() for w in ds.warnings]
    annotations, changes, metrics, claims = [], [], [], []
    benchmark = datasets[spec.benchmark]
    source_ids = {s.id for s in sources}
    valid_events = [
        e for e in events if spec.start <= e.date <= spec.end and all(s in source_ids for s in e.source_ids)
    ]
    for symbol in spec.symbols:
        ds = datasets[symbol]
        bars = [b for b in ds.bars if str(spec.start) <= b.date <= str(spec.end)]
        if len(bars) < 2:
            raise ValueError(f"{symbol} 研究区间数据不足")
        p = performance(
            [b.adj_close for b in bars],
            [b.date for b in bars],
            365 if ds.instrument.calendar == "24/7" else 252,
        )
        metric = {
            "id": f"performance-{symbol}",
            "symbol": symbol,
            "dataset_ids": [ds.id],
            "start": bars[0].date,
            "end": bars[-1].date,
            **p,
        }
        metrics.append(metric)
        claims.append(
            Claim(
                id=f"claim-performance-{symbol}",
                kind="analysis",
                evidence_ids=[ds.id],
                metric_ids=[metric["id"]],
                text=f"{symbol} 在 {bars[0].date} 至 {bars[-1].date} 的"
                f"复权累计收益为 {p['total_return']:.2%}，最大回撤为 {p['max_drawdown']:.2%}。",
            )
        )
        changes.extend(detect_changes(ds, spec.start, spec.end))
        for event in valid_events:
            if symbol not in event.symbols:
                continue
            association = event_windows(event, ds, benchmark, spec.windows, end=spec.end)
            if association:
                annotations.append(association)
                metrics.append(
                    {
                        "id": association["metric_id"],
                        "symbol": symbol,
                        "windows": association["windows"],
                        "dataset_ids": association["dataset_ids"],
                    }
                )
    from .quality import assess_quality, associate_changes

    associate_changes(changes, annotations, valid_events, datasets)
    if not valid_events:
        warnings.append("当前研究尚无足够已核验事件；行情变化保留为未解释，不生成因果结论。")
    for association in annotations:
        nearby = [
            a
            for a in annotations
            if a["symbol"] == association["symbol"]
            and a["event_id"] != association["event_id"]
            and abs((date.fromisoformat(a["date"]) - date.fromisoformat(association["date"])).days) <= 5
        ]
        if nearby:
            association["uncertainty"] += " 同期存在其他已收录事件，无法分离各自作用。"
        same_day = [a["event_id"] for a in nearby if a["date"] == association["date"]]
        if same_day:
            association["shared_window_event_ids"] = same_day
            association["uncertainty"] += " 同日事件共享同一行情窗口，不能当作独立样本或叠加影响。"
    comparison = compare(spec, datasets, macro) if len(spec.symbols) > 1 else {}
    if comparison.get("available"):
        from .sensitivity import sensitivity_analysis

        comparison["sensitivity"] = sensitivity_analysis(spec, datasets, comparison["anchors"])
    warnings.extend(comparison.get("warnings", []))
    if mode == "sample":
        warnings.append("样例模式：事件来自注明来源的固定研究样例，未模拟本次 LLM 自主检索。")
    bundle = ResearchBundle(
        id=run_id,
        created_at=now_iso(),
        mode=mode,
        spec=spec,
        datasets=datasets,
        sources=sources,
        events=valid_events,
        annotations=annotations,
        changes=changes,
        metrics=metrics,
        comparison=comparison,
        claims=claims,
        coverage=coverage,
        warnings=list(dict.fromkeys(warnings)),
        disclosures=[GLD_DISCLOSURE] if "GLD" in spec.symbols else [],
    )
    bundle.quality = assess_quality(bundle)
    return bundle


def validate_bundle(bundle: ResearchBundle) -> dict:
    sources = {s.id for s in bundle.sources} | {d.id for d in bundle.datasets.values()}
    metrics = {m["id"] for m in bundle.metrics}
    failures = []
    for claim in bundle.claims:
        if not claim.evidence_ids or set(claim.evidence_ids) - sources or set(claim.metric_ids) - metrics:
            failures.append(f"无法解析结论引用：{claim.id}")
    for event in bundle.events:
        if not event.source_ids or set(event.source_ids) - sources:
            failures.append(f"无法解析事件引用：{event.id}")
    events = {e.id: e for e in bundle.events}
    for annotation in bundle.annotations:
        event = events.get(annotation["event_id"])
        if event is None or annotation["metric_id"] not in metrics:
            failures.append(f"无法解析行情标注引用：{annotation['id']}")
            continue
        expected = event_windows(
            event,
            bundle.datasets[annotation["symbol"]],
            bundle.datasets[bundle.spec.benchmark],
            bundle.spec.windows,
            end=bundle.spec.end,
        )
        if not expected:
            failures.append(f"事件无法对齐研究区间：{annotation['id']}")
            continue
        for field in ["rating", "direction", "direction_window_days"]:
            if annotation.get(field) != expected[field]:
                failures.append(f"事件反应等级或方向不符：{annotation['id']}")
        if len(annotation["windows"]) != len(expected["windows"]):
            failures.append(f"事件窗口数量不符：{annotation['id']}")
        for actual_window, expected_window in zip(annotation["windows"], expected["windows"]):
            for field in [
                "days",
                "complete",
                "start",
                "end",
                "benchmark_return",
                "relative_return",
                "standardized_response",
            ]:
                actual, target = actual_window.get(field), expected_window.get(field)
                same = (
                    math.isclose(actual, target, rel_tol=1e-10, abs_tol=1e-10)
                    if isinstance(actual, (int, float)) and isinstance(target, (int, float))
                    else actual == target
                )
                if not same:
                    failures.append(f"窗口 {field} 与行情或基准不符：{annotation['id']}")
        bars = {b.date: b for b in bundle.datasets[annotation["symbol"]].bars}
        for window in annotation["windows"]:
            if not window["complete"]:
                continue
            begin, end = bars.get(window["start"]), bars.get(window["end"])
            if not begin or not end or abs(end.adj_close / begin.adj_close - 1 - window["return"]) > 1e-10:
                failures.append(f"窗口收益与原始价格不符：{annotation['id']}")
            if end and event.published_at:
                stamp = datetime.fromisoformat(event.published_at.replace("Z", "+00:00"))
                if stamp.tzinfo and datetime.fromisoformat(end.closed_at) <= stamp:
                    failures.append(f"窗口截止时刻早于公告：{annotation['id']}")
    for row in bundle.comparison.get("backtest", {}).get("rows", []):
        if row["cash"] < -1e-6 or abs(row["nav"] - row["cash"] - sum(row["asset_values"].values())) > 1e-6:
            failures.append("回测资金守恒校验失败")
    return {
        "passed": not failures,
        "failures": failures,
        "claims": len(bundle.claims),
        "events": len(bundle.events),
        "annotations": len(bundle.annotations),
    }
