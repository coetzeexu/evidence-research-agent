"""Deterministic narrow-window sweep for chart moves the researcher never searched.

The model-driven researcher spends its search budget on named events and the
strongest moves first, so weak or late-confirmed moves (reversal turns) are often
left "not investigated". This sweep closes that gap without spending model calls:
one bounded, instrument-scoped search per remaining move. Results are recorded as
candidate leads in coverage only; they are never promoted to events or evidence.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import date, timedelta

Search = Callable[[str, date, date], Awaitable[list[dict]]]

SWEEP_ORIGIN = "deterministic_sweep"
BEFORE_DAYS, AFTER_DAYS = 5, 3


IGNORED_NAME_TOKENS = {"corporation", "inc", "shares", "trust", "fund", "etf", "usd", "the", "and"}


def instrument_aliases(symbol: str, name: str = "") -> set[str]:
    """Lower-case tokens that identify an instrument in a free-text query."""
    tokens = {
        t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) >= 3 and t not in IGNORED_NAME_TOKENS
    }
    return tokens | {symbol.lower()}


def mentions(query: str, aliases: set[str]) -> bool:
    return bool(aliases & set(re.findall(r"[a-z0-9]+", query.lower())))


def targeted(change: dict, coverage: list[dict], name: str = "") -> bool:
    """Whether a successful narrow search already targeted this move."""
    aliases = instrument_aliases(change["symbol"], name)
    day = date.fromisoformat(change["date"])
    for record in coverage:
        if record.get("status") != "success":
            continue
        if record.get("change_id") == change["id"]:
            return True
        try:
            lo, hi = date.fromisoformat(record["start"]), date.fromisoformat(record["end"])
        except (KeyError, ValueError):
            continue
        if (
            lo <= day <= hi
            and (hi - lo).days <= 31
            and (
                mentions(record.get("query", ""), aliases)
                or change["symbol"].lower() in record.get("query", "").lower()
            )
        ):
            return True
    return False


async def sweep_changes(
    changes: list[dict],
    coverage: list[dict],
    search: Search,
    *,
    provider: str,
    names: dict[str, str] | None = None,
    limit: int = 8,
    timeout: float = 60,
) -> list[dict]:
    """Search each untargeted move once and append the records to ``coverage``.

    Returns the new coverage records. Failures are recorded, not raised, so the
    attribution table can tell "searched, failed" from "never searched".
    """
    names = names or {}
    pending = [
        c
        for c in sorted(changes, key=lambda c: c["date"])
        if not targeted(c, coverage, names.get(c["symbol"], ""))
    ][:limit]

    async def one(change: dict) -> dict:
        day = date.fromisoformat(change["date"])
        begin, finish = day - timedelta(days=BEFORE_DAYS), day + timedelta(days=AFTER_DAYS)
        name = next(iter(sorted(instrument_aliases("", names.get(change["symbol"], "")) - {""})), "")
        # Hacker News search matches short keywords; the web provider can take a phrase.
        query = (name or change["symbol"]) if provider == "hn" else f"{name} {change['symbol']} stock".strip()
        record = {
            "query": query,
            "provider": provider,
            "start": str(begin),
            "end": str(finish),
            "change_id": change["id"],
            "origin": SWEEP_ORIGIN,
        }
        try:
            items = await asyncio.wait_for(search(query, begin, finish), timeout)
        except Exception as exc:  # noqa: BLE001 - a failed lead search is a coverage fact
            return {**record, "hits": 0, "status": "failed", "error": type(exc).__name__}
        items = items[:5]
        return {
            **record,
            "hits": len(items),
            "status": "success",
            "urls": [item["url"] for item in items],
            "results": items,
        }

    records = list(await asyncio.gather(*(one(c) for c in pending)))
    coverage.extend(records)
    return records


def sweep_leads(change: dict, coverage: list[dict], maximum: int = 3) -> list[dict]:
    """Unread candidate leads found by the sweep for one move (never evidence)."""
    leads = []
    for record in coverage:
        if record.get("origin") == SWEEP_ORIGIN and record.get("change_id") == change["id"]:
            for item in record.get("results", [])[:maximum]:
                if not str(item.get("url", "")).startswith(("https://", "http://")):
                    continue
                leads.append({"title": str(item.get("title") or item["url"])[:200], "url": item["url"]})
    return leads[:maximum]
