from datetime import date, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from research_app.analytics import (
    build_bundle,
    compare,
    event_windows,
    month_end_anchors,
    monthly_formula_backtest,
    performance,
    portfolio_backtest,
    validate_bundle,
)
from research_app.domain import EventRecord


def test_return_and_drawdown_have_independent_expected_values():
    m = performance([100, 120, 90, 108], ["2020-01-01", "2020-06-01", "2020-09-01", "2021-01-01"], 12)
    assert m["total_return"] == pytest.approx(0.08)
    assert m["max_drawdown"] == pytest.approx(-0.25)


def test_after_close_and_weekend_align_forward(datasets):
    event = EventRecord(
        id="event",
        title="After close",
        date=date(2022, 6, 17),
        published_at="2022-06-17T21:01:00+00:00",
        time_precision="timestamp",
        symbols=["GLD"],
        summary="",
        source_ids=["s"],
    )
    a = event_windows(event, datasets["GLD"], datasets["SPY"], [1, 5, 20])
    assert a["date"] == "2022-06-20"
    assert a["windows"][0]["start"] == "2022-06-17"
    assert a["direction_window_days"] == 5


def test_incomplete_event_window_and_date_precision(datasets):
    ds = datasets["GLD"]
    e = EventRecord(
        id="e",
        title="Recent",
        date=date.fromisoformat(ds.bars[-1].date),
        symbols=["GLD"],
        summary="",
        source_ids=["s"],
        confidence="high",
    )
    a = event_windows(e, ds, datasets["SPY"], [1, 5])
    assert not a["windows"][1]["complete"]
    assert a["confidence"] == "medium"


def test_crypto_utc_close_includes_equity_after_hours_event(datasets):
    event = EventRecord(
        id="late",
        title="Policy",
        date=date(2022, 6, 17),
        published_at="2022-06-17T21:19:04+00:00",
        time_precision="timestamp",
        symbols=["BTC-USD"],
        summary="",
        source_ids=["s"],
    )
    result = event_windows(event, datasets["BTC-USD"], datasets["SPY"], [1])
    window = result["windows"][0]
    assert window["end"] == "2022-06-17"
    assert window["end_closed_at"] == "2022-06-18T00:00:00+00:00"
    assert (
        datetime.fromisoformat(window["start_closed_at"])
        < datetime.fromisoformat(event.published_at)
        < datetime.fromisoformat(window["end_closed_at"])
    )


def test_cross_market_asof_never_uses_future_close(datasets, spec):
    anchors = month_end_anchors(datasets, [*spec.symbols, spec.benchmark], spec.start, spec.end)
    assert len(anchors) == 24
    for anchor in anchors:
        for actual in anchor["actual"].values():
            assert datetime.fromisoformat(actual["closed_at"]) <= datetime.fromisoformat(anchor["at"])
            assert 0 <= actual["age_hours"] <= 96
        assert anchor["actual"]["BTC-USD"]["date"] < anchor["date"]


def test_partial_month_is_excluded(datasets, spec):
    anchors = month_end_anchors(datasets, spec.symbols, spec.start, date(2023, 12, 15))
    assert anchors[-1]["date"].startswith("2023-11")


def test_completed_historical_weekend_month_end_is_included(datasets, spec):
    for dataset in datasets.values():
        dataset.bars = [b for b in dataset.bars if b.date <= "2023-12-31"]
    anchors = month_end_anchors(datasets, [*spec.symbols, spec.benchmark], spec.start, spec.end)
    assert anchors[-1]["date"] == "2023-12-29"


def test_execution_after_signal_and_cash_conservation(datasets, spec):
    anchors = month_end_anchors(datasets, spec.symbols, spec.start, spec.end)
    result = portfolio_backtest(anchors, spec, datasets)
    assert result["trades"]
    for trade in result["trades"]:
        assert datetime.fromisoformat(trade["executed_at"]) > datetime.fromisoformat(trade["signal_at"])
        assert trade["cash_after"] >= -1e-7
        assert trade["cost"] == pytest.approx(abs(trade["notional"]) * 0.001)
    for row in result["rows"]:
        assert row["nav"] == pytest.approx(row["cash"] + sum(row["asset_values"].values()))


def test_initial_fee_included_in_reported_return(spec):
    anchors = [
        {"date": d, "prices": {"GLD": 100, "BTC-USD": 100}}
        for d in ["2022-01-31", "2022-02-28", "2022-03-31"]
    ]
    result = monthly_formula_backtest(anchors, spec)
    assert result["metrics"]["total_return"] == pytest.approx(-0.001)
    assert result["metrics"]["max_drawdown"] == pytest.approx(-0.001)


@given(st.lists(st.floats(min_value=0.2, max_value=5, allow_nan=False), min_size=2, max_size=12))
def test_drawdown_cannot_be_positive(values):
    dates = [f"2020-{i + 1:02d}-01" for i in range(len(values))]
    result = performance(values, dates, 12)
    assert -1 < result["max_drawdown"] <= 0


def test_full_bundle_references_and_ledger(bundle):
    assert validate_bundle(bundle)["passed"]
    bundle.events[0].source_ids = ["fabricated"]
    assert not validate_bundle(bundle)["passed"]


def test_validator_rejects_window_return_that_disagrees_with_prices(bundle):
    bundle.annotations[0]["windows"][0]["return"] += 0.25
    result = validate_bundle(bundle)
    assert not result["passed"]
    assert any("窗口收益与原始价格不符" in failure for failure in result["failures"])


def test_no_cost_buy_hold_equals_weighted_asset_growth(spec):
    spec = spec.model_copy(update={"cost_bps": 0, "rebalance_months": 0})
    anchors = [
        {"date": "2022-01-31", "prices": {"GLD": 100, "BTC-USD": 100}},
        {"date": "2022-02-28", "prices": {"GLD": 120, "BTC-USD": 80}},
        {"date": "2022-03-31", "prices": {"GLD": 150, "BTC-USD": 60}},
    ]
    out = monthly_formula_backtest(anchors, spec)
    assert out["rows"][-1]["nav"] == pytest.approx(105000)
    assert out["rows"][-1]["values"] == pytest.approx([75000, 30000])


def test_historical_research_cannot_use_bars_after_requested_end(spec, datasets, bundle):
    spec = spec.model_copy(update={"end": date(2022, 6, 15)})
    result = build_bundle("bounded", spec, datasets, bundle.sources, bundle.events, {}, [])
    assert result.annotations
    for annotation in result.annotations:
        assert annotation["windows"][0]["complete"]
        assert not annotation["windows"][1]["complete"]
    assert all(c["confirmed_at"][:10] <= str(spec.end) for c in result.changes)


def test_missing_month_end_does_not_turn_midmonth_price_into_monthly_close(spec, datasets):
    datasets["GLD"].bars = [b for b in datasets["GLD"].bars if not "2022-06-15" <= b.date <= "2022-06-30"]
    anchors = month_end_anchors(datasets, [*spec.symbols, spec.benchmark], spec.start, spec.end)
    assert not any(row["date"].startswith("2022-06") for row in anchors)
    result = compare(spec, datasets, {})
    assert result["available"] is False
    assert not result["asset_metrics"]
    assert not result["anchors"]
    assert any("缺失" in warning for warning in result["warnings"])


def test_relative_returns_and_strength_are_validated_against_benchmark(bundle):
    bundle.annotations[0]["windows"][0]["relative_return"] += 0.5
    assert not validate_bundle(bundle)["passed"]
