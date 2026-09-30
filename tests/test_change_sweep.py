from datetime import date

from research_app.change_sweep import SWEEP_ORIGIN, sweep_changes, sweep_leads, targeted
from research_app.quality import assess_quality


def move(id_, day, symbol="GLD"):
    return {"id": id_, "date": day, "symbol": symbol, "strength": 0, "event_ids": []}


async def test_sweep_searches_only_untargeted_moves_in_a_narrow_window():
    changes = [move("done", "2023-08-15"), move("turn", "2023-10-16"), move("fails", "2023-11-20")]
    coverage = [
        {
            "query": "gold",
            "change_id": "done",
            "start": "2023-08-10",
            "end": "2023-08-20",
            "status": "success",
        }
    ]
    calls = []

    async def search(query, begin, finish):
        calls.append((query, begin, finish))
        if begin.month == 11:
            raise TimeoutError
        return [
            {"url": "https://example.com/a", "title": "A"},
            {"url": "javascript:alert(1)", "title": "bad"},
        ]

    records = await sweep_changes(changes, coverage, search, provider="web")
    assert [c[1:] for c in calls] == [
        (date(2023, 10, 11), date(2023, 10, 19)),
        (date(2023, 11, 15), date(2023, 11, 23)),
    ]
    assert all(r["origin"] == SWEEP_ORIGIN and "GLD" in r["query"] for r in records)
    assert targeted(changes[0], coverage)
    assert [r["status"] for r in records] == ["success", "failed"]
    assert targeted(changes[1], coverage)
    # Unsafe schemes never reach the report as clickable leads.
    assert sweep_leads(changes[1], coverage) == [{"title": "A", "url": "https://example.com/a"}]


async def test_sweep_respects_limit():
    changes = [move(f"m{i}", f"2023-0{i + 1}-15") for i in range(5)]

    async def search(query, begin, finish):
        return []

    assert len(await sweep_changes(changes, [], search, provider="hn", limit=2)) == 2


def test_swept_move_is_distinguished_from_researcher_investigation(bundle):
    bundle.spec.intent = "event_study"
    bundle.changes = [move("agent", "2023-08-15"), move("swept", "2023-10-16"), move("failed", "2023-12-15")]
    bundle.coverage = [
        {
            "query": "gold price",
            "change_id": "agent",
            "start": "2023-08-10",
            "end": "2023-08-20",
            "status": "success",
        },
        {
            "query": "GLD stock",
            "change_id": "swept",
            "origin": SWEEP_ORIGIN,
            "start": "2023-10-11",
            "end": "2023-10-19",
            "status": "success",
            "results": [{"url": "https://example.com/lead", "title": "Lead"}],
        },
        {
            "query": "GLD stock",
            "change_id": "failed",
            "origin": SWEEP_ORIGIN,
            "start": "2023-12-10",
            "end": "2023-12-18",
            "status": "failed",
        },
    ]
    assess_quality(bundle)
    by_id = {c["id"]: c["attribution"] for c in bundle.changes}
    assert by_id["agent"]["method"] == "researcher"
    assert by_id["swept"]["method"] == "sweep"
    assert by_id["swept"]["status"] == "investigated_unexplained"
    assert "未读取核验" in by_id["swept"]["note"]
    assert by_id["swept"]["leads"] == [{"title": "Lead", "url": "https://example.com/lead"}]
    assert by_id["failed"]["status"] == "not_investigated"


async def test_sweep_uses_company_name_and_recognises_name_based_searches():
    changes = [move("a", "2023-05-25", "NVDA"), move("b", "2023-09-15", "NVDA")]
    # The researcher searched "Nvidia earnings" around move a, so only b is swept.
    coverage = [{"query": "Nvidia earnings", "start": "2023-05-20", "end": "2023-05-30", "status": "success"}]
    queries = []

    async def search(query, begin, finish):
        queries.append(query)
        return []

    await sweep_changes(changes, coverage, search, provider="hn", names={"NVDA": "NVIDIA Corporation"})
    assert queries == ["nvidia"]
