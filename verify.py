"""Pre-pitch verification of hot multi-agency prospects.

The engine's strongest open-mandate proof — two brands on one home — decays:
either proving listing can quietly delist (seller consolidated onto a sole
mandate) or go under offer, and the report would still say "open". scorer.py
degrades stale proof to probably_open; this module is the active half of the
guarantee: after each scored crawl it re-fetches, LIVE, exactly the member
listings whose sighting is older than VERIFY_STALE_HOURS for every hot-tier
multi-agency property, then re-groups and re-scores what changed.

This is the automated form of the dashboard's per-property "re-eval" button,
pointed at the top of the funnel only. The request budget is deliberately
small (config.VERIFY_MAX_FETCHES, spread across each listing's own portal
rate limit), so it rides inside every portal's tolerance — including
Property24's — and a fetch that comes back empty is logged as "no longer
served", which is precisely the fact the pitch team needs before dialling.
"""

from __future__ import annotations

import os
import threading

import config
import db
import dedupe
import scorer
import sources as source_registry


def _stale_hot_groups(conn) -> list[list]:
    """Hot, sellable, multi-brand groups with members not seen recently.

    agency_count comes from property_groups (dedupe's brand-level count), and
    the tier/sellable read is per member — any member's score row speaks for
    the group, since scorer.persist writes the same result to every member.
    """
    rows = conn.execute(
        """SELECT l.*, g.group_id, g.agency_count, s.tier, s.sellable
           FROM listings l
           JOIN property_groups g ON g.listing_key = l.listing_key
           JOIN scores s ON s.listing_key = l.listing_key
           WHERE g.agency_count > 1""").fetchall()
    groups: dict[int, list] = {}
    for r in rows:
        groups.setdefault(r["group_id"], []).append(r)
    out = []
    for members in groups.values():
        if not any(m["tier"] == "hot" and (m["sellable"] or 0) == 1
                   for m in members):
            continue
        stale = [m for m in members
                 if (age := _age_hours(m["last_seen"])) is None
                 or age > config.VERIFY_STALE_HOURS]
        if stale:
            out.append(stale)
    # Freshest proof first: the best prospects get verified before the
    # request budget runs out.
    out.sort(key=lambda ms: min(_age_hours(m["last_seen"]) or 1e9 for m in ms))
    return out


def _age_hours(last_seen: str | None) -> float | None:
    seen = scorer._parse_date(last_seen)
    if not seen:
        return None
    return (scorer._utcnow() - seen).total_seconds() / 3600.0


def run(conn, log=print, stop: threading.Event | None = None,
        use_ai: bool = True, max_fetches: int | None = None) -> dict:
    """Verify stale proof on hot prospects. Returns counters for the log."""
    stop = stop or threading.Event()
    budget = max_fetches if max_fetches is not None else config.VERIFY_MAX_FETCHES
    stats = {"checked": 0, "groups": 0, "refetched": 0, "gone": 0,
             "rescored": 0}

    stale_groups = _stale_hot_groups(conn)
    if not stale_groups:
        return stats

    srcs: dict = {}
    touched: list[str] = []
    try:
        for members in stale_groups:
            if stop.is_set() or stats["refetched"] >= budget:
                break
            stats["groups"] += 1
            for m in members:
                if stop.is_set() or stats["refetched"] >= budget:
                    break
                name = m["source"]
                if not config.SOURCES.get(name, {}).get("enabled"):
                    continue          # e.g. Property24 on a hosted deploy
                if name not in srcs:
                    srcs[name] = source_registry.build(name, logger=log)
                src = srcs[name]
                if src.fetcher.circuit_open:
                    continue
                stats["checked"] += 1
                # Ask the portal live — a cached copy is the staleness
                # being verified away.
                try:
                    os.remove(src.fetcher._cache_path(m["url"]))
                except OSError:
                    pass
                try:
                    listing = src.parse_detail(m["url"], m["suburb_slug"])
                except Exception as e:                  # noqa: BLE001
                    log(f"verify: [{src.label}] parse failed "
                        f"{type(e).__name__}: {m['url']}")
                    listing = None
                stats["refetched"] += 1
                if listing:
                    db.upsert_listing(conn, listing)
                    conn.commit()
                    touched.append(m["listing_key"])
                else:
                    stats["gone"] += 1
                    log(f"verify: [{src.label}] no longer served — "
                        f"{m['url']} (delisted, sold, or now under offer "
                        f"behind a parse-rejected page)")
    finally:
        for src in srcs.values():
            src.fetcher.close()

    if not touched:
        return stats

    # Re-group, then re-judge each affected property once.
    dedupe.rebuild_groups(conn)
    conn.commit()
    backends = scorer.build_backends(use_ai)
    ctx = scorer.build_ctx(conn)
    scored: set[frozenset] = set()
    for key in touched:
        fresh = scorer.group_for_listing(conn, key)
        if not fresh:
            continue
        ident = frozenset(m["listing_key"] for m in fresh)
        if ident in scored:
            continue
        scored.add(ident)
        scorer.score_members(conn, fresh, backends=backends, ctx=ctx)
        stats["rescored"] += 1
    conn.commit()
    return stats
