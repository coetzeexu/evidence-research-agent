from datetime import date

from research_app.agents import compare_units
from research_app.domain import EventRecord
from research_app.quality import assess_quality, associate_changes
from research_app.sensitivity import sensitivity_analysis


def test_association_is_forward_only_and_counts_sessions(datasets):
    ds = datasets["GLD"]
    events = [
        EventRecord(
            id="e",
            title="release",
            date=date(2023, 1, 20),
            symbols=["GLD"],
            summary="fact",
            source_ids=["source"],
        )
    ]
    annotations = [{"symbol": "GLD", "event_id": "e", "date": "2023-01-20"}]
    changes = [
        {"symbol": "GLD", "date": d, "event_ids": []}
        for d in ["2023-01-19", "2023-01-23", "2023-01-27", "2023-01-30"]
    ]
    associate_changes(changes, annotations, events, {"GLD": ds})
    assert [bool(c["event_ids"]) for c in changes] == [False, True, True, False]
    assert changes[1]["associations"][0]["lag_bars"] == 1
    assert changes[2]["associations"][0]["lag_bars"] == 5
    assert changes[1]["associations"][0]["relation"] == "delayed_candidate"


def test_later_publication_cannot_explain_earlier_close(datasets):
    event = EventRecord(
        id="late",
        title="after close",
        date=date(2023, 1, 20),
        published_at="2023-01-20T22:00:00+00:00",
        symbols=["GLD"],
        summary="fact",
        source_ids=["src"],
    )
    changes = [{"symbol": "GLD", "date": "2023-01-20", "event_ids": []}]
    associate_changes(
        changes, [{"symbol": "GLD", "event_id": "late", "date": "2023-01-20"}], [event], datasets
    )
    assert not changes[0]["event_ids"]


def test_required_release_cannot_be_satisfied_by_a_paper(bundle):
    bundle.spec.required_events = ["模型首次发布"]
    bundle.events[0].title = "模型论文公开"
    bundle.events[0].satisfies = []
    quality = assess_quality(bundle)
    assert quality["requirements"][0]["status"] == "missing"
    bundle.quality = quality
    assert bundle.completion_status == "partial"
    bundle.events[0].satisfies = ["模型首次发布"]
    assert assess_quality(bundle)["requirements"][0]["status"] == "covered"
    bundle.sources[0].status = "metadata_only"
    assert assess_quality(bundle)["requirements"][0]["status"] == "missing"


def test_major_move_can_be_investigated_without_inventing_an_event(bundle):
    bundle.spec.intent = "event_study"
    bundle.changes = [{"id": "c", "date": "2023-06-15", "symbol": "GLD", "strength": 4, "event_ids": []}]
    bundle.coverage = [
        {
            "query": "GLD 2023-06-15",
            "start": "2023-06-12",
            "end": "2023-06-18",
            "status": "success",
            "hits": 0,
        }
    ]
    quality = assess_quality(bundle)
    assert quality["major_moves"][0]["investigated"]
    assert quality["associated_changes"] == 0
    bundle.coverage[0]["end"] = "2023-12-31"
    assert not assess_quality(bundle)["major_moves"][0]["investigated"]


def test_every_marked_move_has_distinct_attribution_state(bundle):
    bundle.spec.intent = "event_study"
    bundle.changes = [
        {
            "id": "linked",
            "date": "2023-06-15",
            "symbol": "GLD",
            "strength": 4,
            "event_ids": ["e"],
            "associations": [{"event_id": "e", "lag_bars": 0}],
        },
        {"id": "searched", "date": "2023-08-15", "symbol": "GLD", "strength": 3, "event_ids": []},
        {"id": "blank", "date": "2023-10-16", "symbol": "GLD", "strength": 2, "event_ids": []},
    ]
    bundle.coverage = [
        {
            "query": "gold price",
            "change_id": "searched",
            "start": "2023-08-10",
            "end": "2023-08-20",
            "status": "success",
            "hits": 0,
        },
        # Failed or overly wide searches never count as investigating the move.
        {"query": "GLD", "start": "2023-10-01", "end": "2023-10-31", "status": "failed"},
        {"query": "GLD", "start": "2023-01-01", "end": "2023-12-31", "status": "success"},
    ]
    quality = assess_quality(bundle)
    states = {c["id"]: c["attribution"]["status"] for c in bundle.changes}
    assert states == {"linked": "linked", "searched": "investigated_unexplained", "blank": "not_investigated"}
    assert bundle.changes[1]["attribution"]["queries"] == ["gold price"]
    assert quality["attribution"] == {"linked": 1, "investigated_unexplained": 1, "not_investigated": 1}


def test_long_uncovered_period_is_a_gap(bundle):
    bundle.spec.intent = "event_study"
    quality = assess_quality(bundle)
    assert any(a["kind"] == "period_gap" and "2023" in a["query"] for a in quality["repair_actions"])
    bundle.coverage = [{"query": "GLD 2023 events", "status": "success", "hits": 0}]
    assert not any(
        a["kind"] == "period_gap" and "2023" in a["query"] for a in assess_quality(bundle)["repair_actions"]
    )


def test_display_rounding_does_not_create_numeric_false_alarm():
    result = compare_units(992.14, "percent", 9.921367985713552, "number")
    assert result["display_compatible"] and not result["equal"]
    assert not compare_units(992.14, "percent", 0.99213679857, "number")["display_compatible"]


def test_sensitivity_keeps_base_parameters_and_uses_execution_method(bundle, datasets):
    from research_app.analytics import month_end_anchors, portfolio_backtest

    spec = bundle.spec
    original = spec.model_dump()
    anchors = month_end_anchors(datasets, [*spec.symbols, spec.benchmark], spec.start, spec.end)
    result = sensitivity_analysis(spec, datasets, anchors)
    expected = portfolio_backtest(anchors, spec, datasets)["metrics"]
    assert result["rows"][0]["total_return"] == expected["total_return"]
    assert {r["dimension"] for r in result["rows"]} == {"baseline", "cost", "frequency", "weights"}
    assert spec.model_dump() == original
    assert all(sum(r["weights"]) == 1 for r in result["rows"])


def test_company_name_alias_counts_as_investigation(bundle):
    bundle.spec.intent = "event_study"
    bundle.datasets["GLD"].instrument.name = "SPDR Gold Shares"
    bundle.changes = [{"id": "c", "date": "2023-06-15", "symbol": "GLD", "strength": 4, "event_ids": []}]
    bundle.coverage = [{"query": "gold", "start": "2023-06-12", "end": "2023-06-18", "status": "success"}]
    assert assess_quality(bundle)["major_moves"][0]["investigated"]
    bundle.coverage[0]["query"] = "share prices"
    assert not assess_quality(bundle)["major_moves"][0]["investigated"]


def test_focused_study_does_not_force_unrelated_years_or_moves(bundle):
    bundle.spec.intent = "event_study"
    bundle.spec.event_scope = "focused"
    q = assess_quality(bundle)
    assert not q["periods"] and not q["major_moves"]


def test_comparison_uses_question_coverage_not_dated_event_quota(bundle):
    bundle.events = []
    quality = assess_quality(bundle)
    assert quality["passed"]
    assert quality["major_moves"] == quality["periods"] == []
    bundle.spec.required_events = ["用户指定危机"]
    assert not assess_quality(bundle)["passed"]
    bundle.spec.required_events = []
    bundle.sources[0].publisher = "FRED"
    assert not assess_quality(bundle)["passed"]


def test_retrospective_metadata_cannot_shift_original_event_date():
    from research_app.agents import normalize_event_timestamp

    event = EventRecord(
        id="svb",
        title="Bank closure",
        date=date(2023, 3, 10),
        published_at="2023-03-12T18:00:00+00:00",
        time_precision="timestamp",
        symbols=["GLD"],
        summary="Closure on March 10",
        source_ids=["s"],
    )
    normalize_event_timestamp(event)
    assert event.date == date(2023, 3, 10)
    assert event.published_at is None and event.time_precision == "date"
    assert "事后报道" in event.uncertainty


def test_research_targets_prioritize_uncovered_recent_year_and_respect_focus(bundle):
    from research_app.agents import ResearchResult, research_targets

    spec = bundle.spec.model_copy(
        update={
            "intent": "event_study",
            "start": date(2022, 1, 1),
            "end": date(2024, 12, 31),
            "required_events": ["release"],
        }
    )
    prior = ResearchResult(
        events=[bundle.events[0].model_copy(update={"date": date(2022, 6, 1), "satisfies": ["release"]})]
    )
    targets = research_targets(spec, prior)
    assert [r["start"] for r in targets] == ["2024-01-01", "2023-01-01"]
    spec.event_scope = "focused"
    assert research_targets(spec, prior) == []


def test_date_evidence_requires_saved_text_or_matching_publication(bundle):
    from research_app.agents import has_date_evidence

    event = bundle.events[0]
    source = bundle.sources[0]
    sources = {source.id: source}
    event.date_source_id = source.id
    texts = {source.id: "On June 15, 2022, the policy was announced."}
    assert not has_date_evidence(event, sources, texts)
    event.date_quote = "On June 15, 2022, the policy was announced."
    assert has_date_evidence(event, sources, texts)
    event.date_quote = "On June 16, 2022, the policy was announced."
    assert not has_date_evidence(event, sources, texts)
    event.date_quote = ""
    source.published_at = str(event.date)
    assert has_date_evidence(event, sources, texts)
    event.date_source_id = "unread"
    assert not has_date_evidence(event, sources, texts)


def test_postclose_retrospective_report_describes_original_session_only(datasets):
    from research_app.agents import normalize_event_timestamp

    event = EventRecord(
        id="report",
        title="Friday selloff recap",
        date=date(2023, 1, 20),
        published_at="2023-01-20T23:00:00Z",
        timing_basis="retrospective",
        symbols=["GLD"],
        summary="Observed reaction",
        source_ids=["src"],
    )
    normalize_event_timestamp(event)
    assert event.published_at is None
    changes = [{"symbol": "GLD", "date": d, "event_ids": []} for d in ["2023-01-20", "2023-01-23"]]
    associate_changes(
        changes, [{"symbol": "GLD", "event_id": event.id, "date": "2023-01-20"}], [event], datasets
    )
    assert changes[0]["associations"][0]["relation"] == "retrospective_report"
    assert changes[1]["event_ids"] == []
