"""Auditable coverage gates and directed event associations, not causal attribution."""

from datetime import date, datetime

from .change_sweep import SWEEP_ORIGIN, instrument_aliases, mentions, sweep_leads
from .domain import ResearchBundle


def associate_changes(changes, annotations, events, datasets):
    event_map = {e.id: e for e in events}
    for change in changes:
        bars = datasets[change["symbol"]].bars
        indices = {b.date: i for i, b in enumerate(bars)}
        change_index = indices[change["date"]]
        links = []
        for annotation in annotations:
            if annotation["symbol"] != change["symbol"]:
                continue
            event = event_map[annotation["event_id"]]
            event_index = indices.get(annotation["date"])
            if event_index is None:
                continue
            lag = change_index - event_index
            if event.timing_basis == "retrospective":
                if lag == 0:
                    links.append(
                        {
                            "event_id": event.id,
                            "lag_bars": 0,
                            "relation": "retrospective_report",
                            "source_ids": event.source_ids,
                            "reason": "事后报道记录该日事件或市场反应，仅用于解释复核，不是当时可用的交易信号，也不构成因果证明。",
                        }
                    )
                continue
            # Never explain an earlier movement using a later disclosure. Count actual bars,
            # so weekends do not hide delayed reactions like a Friday-to-Monday repricing.
            if not 0 <= lag <= 5:
                continue
            if event.published_at:
                stamp = datetime.fromisoformat(event.published_at.replace("Z", "+00:00"))
                if stamp.tzinfo and stamp >= datetime.fromisoformat(bars[change_index].closed_at):
                    continue
            links.append(
                {
                    "event_id": event.id,
                    "lag_bars": lag,
                    "relation": "same_session_candidate" if lag == 0 else "delayed_candidate",
                    "source_ids": event.source_ids,
                    "reason": f"来源支持的事件公开后第 {lag} 根日线出现变化；"
                    "同标的与时间先后支持候选关联，未证明该事件触发行情。",
                }
            )
        change["associations"] = sorted(links, key=lambda r: (r["lag_bars"], r["event_id"]))
        change["event_ids"] = [r["event_id"] for r in change["associations"]]


def assess_quality(bundle: ResearchBundle) -> dict:
    """No opaque aggregate score: each unsatisfied condition is explicit and repairable.

    Refreshes each change's attribution state first so counts and markers never diverge.
    """
    attribute_changes(bundle)
    spec = bundle.spec
    sources = {s.id: s for s in bundle.sources if s.status == "retrieved"}
    supported = [e for e in bundle.events if e.source_ids and all(s in sources for s in e.source_ids)]
    requirements = []
    actions = []
    for required in spec.required_events:
        matched = [e.id for e in supported if required in e.satisfies]
        requirements.append(
            {"requirement": required, "event_ids": matched, "status": "covered" if matched else "missing"}
        )
        if not matched:
            actions.append(
                {
                    "kind": "required_event",
                    "query": required,
                    "reason": "用户点名要求尚无已读原文支持的对应事件",
                }
            )
    periods = []
    if spec.intent in {"event_study", "combined"} and spec.event_scope == "broad":
        for year in range(spec.start.year, spec.end.year + 1):
            begin, end = max(spec.start, date(year, 1, 1)), min(spec.end, date(year, 12, 31))
            ids = [e.id for e in supported if begin <= e.date <= end]
            searched = any(
                q.get("status") == "success"
                and str(year) in q.get("query", "")
                and any(
                    query_mentions_instrument(bundle, symbol, q.get("query", "")) for symbol in spec.symbols
                )
                for q in bundle.coverage
            )
            # Coverage is investigation, not a quota of manufactured events.
            required = (end - begin).days >= 180
            periods.append(
                {
                    "start": str(begin),
                    "end": str(end),
                    "event_ids": ids,
                    "required": required,
                    "status": "covered" if ids else "investigated" if searched else "gap",
                    "searched": searched,
                }
            )
            if required and not ids and not searched:
                actions.append(
                    {
                        "kind": "period_gap",
                        "query": f"{' '.join(spec.symbols)} {year}",
                        "reason": "超过半年研究区间尚未调查；允许调查后仍无可确认事件，不能凑事件数",
                        "start": str(begin),
                        "end": str(end),
                    }
                )
    # Demand targeted investigation of major moves, never demand a matching news story.
    # A successful search may still find nothing; preserve that as unexplained, not fabricated.
    investigated = []
    candidates = (
        bundle.changes if spec.event_scope == "broad" and spec.intent in {"event_study", "combined"} else []
    )
    for change in sorted(candidates, key=lambda c: c.get("strength", 0), reverse=True)[:5]:
        day = date.fromisoformat(change["date"])
        searches = change_searches(bundle, change)
        checked = bool(change["event_ids"] or searches)
        investigated.append(
            {
                "change_id": change["id"],
                "date": change["date"],
                "symbol": change["symbol"],
                "event_ids": change["event_ids"],
                "queries": searches,
                "investigated": checked,
            }
        )
        if not checked:
            actions.append(
                {
                    "kind": "uninvestigated_move",
                    "query": f"{change['symbol']} {day}",
                    "date": str(day),
                    "change_id": change["id"],
                    "reason": "主要异动尚未进行窄时间窗检索",
                }
            )
    missing_data = []
    for symbol in spec.symbols:
        bars = [b for b in bundle.datasets[symbol].bars if str(spec.start) <= b.date <= str(spec.end)]
        if not bars or (date.fromisoformat(bars[0].date) - spec.start).days > 7:
            missing_data.append(f"{symbol} 起始覆盖不足")
        if not bars or (spec.end - date.fromisoformat(bars[-1].date)).days > 7:
            missing_data.append(f"{symbol} 截止覆盖不足")
    if len(spec.symbols) > 1 and not bundle.comparison.get("available"):
        missing_data.append("共同月度数据不可用")
    # Macro series alone do not satisfy the information-source requirement. A read
    # product definition/research source does; it need not invent a dated event.
    information_sources = [s for s in sources.values() if s.publisher != "FRED"]
    if not information_sources:
        actions.append(
            {"kind": "source_gap", "query": " ".join(spec.symbols), "reason": "尚无已读资讯或产品定义原文"}
        )
    return {
        "version": "1.0",
        "passed": not actions and not missing_data,
        "requirements": requirements,
        "periods": periods,
        "major_moves": investigated,
        "repair_actions": actions,
        "data_gaps": missing_data,
        "event_count": len(supported),
        "source_count": len(sources),
        "changes": len(bundle.changes),
        "associated_changes": sum(bool(c["event_ids"]) for c in bundle.changes),
        "attribution": {
            status: sum(c.get("attribution", {}).get("status") == status for c in bundle.changes)
            for status in ATTRIBUTION_STATUSES
        },
        "note": "关联数量不代表归因准确率；未找到事件不等于研究失败，未调查用户要求需披露。",
    }


ATTRIBUTION_STATUSES = ("linked", "investigated_unexplained", "not_investigated")
ATTRIBUTION_NOTES = {
    "linked": "已有来源支持的事件在变化前后 0-5 根日线内公开；仅为候选关联，不证明因果。",
    "investigated_unexplained": "已按该日窄时间窗检索，未取得可核实的同期公开事件；保留为未解释变化。",
    "not_investigated": "本轮预算内未对该日做专项检索；不能据此判断是否存在同期事件。",
}


def change_searches(bundle, change, include_sweep: bool = True) -> list[str]:
    """Successful narrow-window searches that targeted this move or its instrument."""
    day = date.fromisoformat(change["date"])
    searches = []
    for query in bundle.coverage:
        if not include_sweep and query.get("origin") == SWEEP_ORIGIN:
            continue
        try:
            lo, hi = date.fromisoformat(query["start"]), date.fromisoformat(query["end"])
        except (ValueError, KeyError):
            continue
        if (
            lo <= day <= hi
            and (hi - lo).days <= 31
            and query.get("status") == "success"
            and (
                query.get("change_id") == change["id"]
                or query_mentions_instrument(bundle, change["symbol"], query.get("query", ""))
            )
        ):
            searches.append(query["query"])
    return searches


SWEEP_NOTE = (
    "研究 Agent 预算内未专项调查，由代码按该日前 5 天至后 3 天自动检索一次；"
    "列出的候选线索未读取核验，不构成事件证据，也不证明该日无同期事件。"
)


def researcher_searched(bundle, change) -> bool:
    return bool(change_searches(bundle, change, include_sweep=False))


def attribute_changes(bundle: ResearchBundle) -> None:
    """Give every displayed move an explicit, auditable attribution state.

    Absence of a linked event is split into "searched and found nothing" versus
    "never searched", so a reader can tell a research gap from a genuine blank.
    """
    for change in bundle.changes:
        queries = change_searches(bundle, change)
        status = (
            "linked"
            if change.get("associations")
            else "investigated_unexplained"
            if queries
            else "not_investigated"
        )
        # Sweep records are tagged per move; a linked event always comes from sources the
        # research agent read, so only unlinked moves can be "sweep only".
        swept = any(
            q.get("origin") == SWEEP_ORIGIN and q.get("change_id") == change["id"] for q in bundle.coverage
        )
        method = (
            "researcher"
            if status == "linked"
            else "none"
            if not queries
            else "sweep"
            if swept and not researcher_searched(bundle, change)
            else "researcher"
        )
        note = (
            SWEEP_NOTE
            if status == "investigated_unexplained" and method == "sweep"
            else ATTRIBUTION_NOTES[status]
        )
        change["attribution"] = {
            "status": status,
            "queries": queries,
            "note": note,
            "method": method,
            "leads": sweep_leads(change, bundle.coverage) if status != "linked" else [],
        }


def query_mentions_instrument(bundle, symbol, query):
    aliases = instrument_aliases(symbol, bundle.datasets[symbol].instrument.name)
    return mentions(query, aliases) or symbol.lower() in query.lower()
