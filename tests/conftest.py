from datetime import date, datetime, time, timedelta, timezone

import pytest
from research_app.analytics import build_bundle
from research_app.domain import (
    Bar,
    EventRecord,
    Instrument,
    MarketDataset,
    ResearchSpec,
    SourceRecord,
    digest,
)


def dataset(symbol="AAA", crypto=False):
    bars = []
    for i in range(800):
        day = date(2022, 1, 1) + timedelta(days=i)
        if not crypto and day.weekday() > 4:
            continue
        value = 100 * (1.0005**i) * (1 + 0.06 * ((i % 45) / 45))
        opened = datetime.combine(day, time(0) if crypto else time(14, 30), timezone.utc)
        closed = opened + timedelta(hours=24 if crypto else 6.5)
        bars.append(
            Bar(
                date=str(day),
                opened_at=opened.isoformat(),
                closed_at=closed.isoformat(),
                open=value * 0.999,
                high=value * 1.01,
                low=value * 0.99,
                close=value,
                adj_close=value,
                volume=1000 + i,
            )
        )
    return MarketDataset(
        id=f"prices-{symbol}-test",
        instrument=Instrument(
            symbol=symbol,
            name=symbol,
            currency="USD",
            asset_type="CRYPTOCURRENCY" if crypto else "ETF",
            timezone="UTC" if crypto else "America/New_York",
            calendar="24/7" if crypto else "XNYS",
            source_url=f"https://example.com/{symbol}",
        ),
        retrieved_at="2024-03-12T21:00:00+00:00",
        source_url=f"https://example.com/{symbol}",
        content_hash=digest(symbol),
        bars=bars,
    )


@pytest.fixture
def spec():
    return ResearchSpec(
        intent="asset_comparison",
        title="Test allocation",
        symbols=["GLD", "BTC-USD"],
        start=date(2022, 1, 1),
        end=date(2023, 12, 31),
        weights=[0.5, 0.5],
    )


@pytest.fixture
def datasets():
    return {"GLD": dataset("GLD"), "BTC-USD": dataset("BTC-USD", True), "SPY": dataset("SPY")}


@pytest.fixture
def bundle(spec, datasets):
    source = SourceRecord(
        id="src-test",
        title="Verified test source",
        url="https://example.com/source",
        publisher="example.com",
        retrieved_at="2024-01-01T00:00:00+00:00",
    )
    event = EventRecord(
        id="ev-test",
        title="Policy event",
        date=date(2022, 6, 15),
        symbols=spec.symbols,
        summary="Fixture fact only",
        source_ids=[source.id],
    )
    result = build_bundle("testbundle", spec, datasets, [source], [event], {}, [])
    result.review = {"passed": True, "findings": [], "summary": "Fixture verification"}
    return result
