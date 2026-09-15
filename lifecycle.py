"""Listing lifecycle / sold-proxy tracking.

We have no licensed sold-price feed (Lightstone/LOOM), so this module builds
the engine's own "sold comps" proxy from crawl history: when a listing
disappears from its portal we record the delisting, and if it vanished while
marked under offer we treat the last asking price as a *likely sold price* —
explicitly a proxy (asking-at-disappearance), not a deeds record. Over weeks
of crawling, `listing_lifecycle` becomes a private market-history dataset that
cma.py reads for days-on-market and recent-sale comparables.

Detection is deliberately conservative — a false delisting poisons the comps
feed, so a listing is only considered "missing" relative to a demonstrably
FRESHER crawl of its own (source, suburb_slug) cohort:

  * cohort_max = MAX(last_seen) over that (source, suburb_slug). The listing
    is delisted only when cohort_max - listing.last_seen > 48 hours, i.e. the
    crawler revisited that suburb on that portal at least two days after the
    listing was last seen and the listing wasn't there. A cohort crawled only
    once can therefore never produce a delisting.
  * Sources disabled in config.SOURCES are skipped entirely: a disabled
    portal never refreshes its cohorts, and comparing its stale rows against
    anything would mass-delist them (e.g. property24 on a hosted deploy).
  * Cohorts with fewer than 3 listings are skipped — too thin to distinguish
    "listing gone" from "crawl variance".

Known limitation: crawls are page-limited (config.MAX_PAGES_PER_SUBURB, ~20
listings/page), so a listing sitting deep in a portal's search results can
miss a shallow re-crawl without having been removed. The 48-hour grace window
plus the per-cohort comparison is the mitigation: one missed crawl inside the
window never delists, and a listing must stay absent across everything the
crawler saw of that cohort for 48+ hours. With MAX_PAGES_PER_SUBURB=3 and the
luxury price floor, target suburbs fit comfortably within the crawl depth.

Relisting: a delisted listing that reappears (last_seen back within 48h of
cohort_max) flips to 'relisted' with the off-market gap noted — a juicy
prospecting signal, often a failed mandate — and its likely_sold flag is
cleared (it plainly didn't sell).

Integration: call update(conn) after each crawl completes (post-upsert,
before scoring). It is a full-sweep and idempotent, so running it more often
is harmless.

Stdlib only. Owns exactly one table: listing_lifecycle.
"""

from __future__ import annotations

import statistics
from datetime import datetime

import config

DELIST_GAP_HOURS = 48.0   # cohort must be this much fresher than the listing
MIN_COHORT_SIZE = 3       # cohorts thinner than this are never trusted

DDL = """
CREATE TABLE IF NOT EXISTS listing_lifecycle (
    listing_key           TEXT PRIMARY KEY,
    status                TEXT,     -- 'active' | 'delisted' | 'relisted'
    first_seen            TEXT,
    delisted_at           TEXT,     -- last_seen when it vanished (last proof it was listed)
    relisted_at           TEXT,
    days_on_market        REAL,     -- running for active/relisted, frozen at delist
    last_price            INTEGER,  -- asking price at last sighting
    under_offer_at_delist INTEGER,
    likely_sold           INTEGER,  -- 1 = disappeared while under offer
    likely_sold_price     INTEGER,  -- asking-at-disappearance proxy, NOT a deeds price
    price_at_first_seen   INTEGER,  -- earliest price_history row (fallback price_zar)
    total_cut_pct         REAL,     -- (first - last) / first * 100, only when positive
    note                  TEXT,
    updated_at            TEXT
);
CREATE INDEX IF NOT EXISTS idx_lifecycle_status ON listing_lifecycle(status);
"""


def ensure_table(conn) -> None:
    conn.executescript(DDL)


# ------------------------------------------------------------------ helpers

def _parse_ts(ts: str | None) -> datetime | None:
    """Parse SQLite datetime('now') text ('YYYY-MM-DD HH:MM:SS', UTC)."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _hours_between(older: str | None, newer: str | None) -> float | None:
    a, b = _parse_ts(older), _parse_ts(newer)
    if a is None or b is None:
        return None
    return (b - a).total_seconds() / 3600.0


def _days_between(older: str | None, newer: str | None) -> float | None:
    h = _hours_between(older, newer)
    return None if h is None else round(h / 24.0, 2)


def _first_price(conn, listing_key: str, fallback: int | None) -> int | None:
    """Earliest observed asking price: first price_history row, else price_zar."""
    row = conn.execute(
        "SELECT price_zar FROM price_history WHERE listing_key = ?"
        " ORDER BY observed_at ASC, rowid ASC LIMIT 1",
        (listing_key,),
    ).fetchone()
    if row and row[0]:
        return row[0]
    return fallback


def _cut_pct(first_price: int | None, last_price: int | None) -> float | None:
    if first_price and last_price and first_price > last_price:
        return round((first_price - last_price) / first_price * 100.0, 2)
    return None


_UPSERT = """
INSERT INTO listing_lifecycle (
    listing_key, status, first_seen, delisted_at, relisted_at,
    days_on_market, last_price, under_offer_at_delist, likely_sold,
    likely_sold_price, price_at_first_seen, total_cut_pct, note, updated_at
) VALUES (
    :listing_key, :status, :first_seen, :delisted_at, :relisted_at,
    :days_on_market, :last_price, :under_offer_at_delist, :likely_sold,
    :likely_sold_price, :price_at_first_seen, :total_cut_pct, :note,
    datetime('now')
)
ON CONFLICT(listing_key) DO UPDATE SET
    status                = excluded.status,
    first_seen            = excluded.first_seen,
    delisted_at           = excluded.delisted_at,
    relisted_at           = excluded.relisted_at,
    days_on_market        = excluded.days_on_market,
    last_price            = excluded.last_price,
    under_offer_at_delist = excluded.under_offer_at_delist,
    likely_sold           = excluded.likely_sold,
    likely_sold_price     = excluded.likely_sold_price,
    price_at_first_seen   = excluded.price_at_first_seen,
    total_cut_pct         = excluded.total_cut_pct,
    note                  = excluded.note,
    updated_at            = datetime('now')
"""


# ------------------------------------------------------------------- update

def update(conn, exclude_sources=frozenset()) -> dict:
    """Full lifecycle sweep. Idempotent — safe to run after every crawl.

    exclude_sources: sources whose current crawl looked suspicious (the
    pipeline's yield canary) — their listings are treated like a disabled
    source's for this sweep, so a broken parser can never mass-delist.

    Returns {active, newly_delisted, newly_relisted, delisted_total,
    likely_sold_total}.
    """
    ensure_table(conn)
    enabled = set(config.enabled_sources()) - set(exclude_sources)
    now = conn.execute("SELECT datetime('now')").fetchone()[0]

    # Cohort freshness: how recently the crawler last covered each
    # (source, suburb_slug), and how many listings that cohort holds.
    # For-sale stock only. The whole point of this table is the sold proxy —
    # "vanished while under offer" means a sale went through — and a rental
    # that disappears simply means a tenant signed. Letting rentals in would
    # feed cma.py phantom sold comps at rental prices.
    cohorts = {
        (r[0], r[1]): (r[2], r[3])
        for r in conn.execute(
            "SELECT source, suburb_slug, COUNT(*), MAX(last_seen)"
            " FROM listings WHERE listing_type = 'sale'"
            " GROUP BY source, suburb_slug")
    }
    prev_rows = {
        r["listing_key"]: dict(r)
        for r in conn.execute("SELECT * FROM listing_lifecycle")
    }

    newly_delisted = newly_relisted = 0

    for lst in conn.execute(
            "SELECT listing_key, source, suburb_slug, first_seen, last_seen,"
            " price_zar, under_offer FROM listings"
            " WHERE listing_type = 'sale'").fetchall():
        key = lst["listing_key"]
        prev = prev_rows.get(key)
        size, cohort_max = cohorts[(lst["source"], lst["suburb_slug"])]

        # Guard rails: only a fresh-enough crawl of a trusted cohort on an
        # enabled source can ever declare a listing missing.
        eligible = lst["source"] in enabled and size >= MIN_COHORT_SIZE
        gap_h = _hours_between(lst["last_seen"], cohort_max)
        missing = eligible and gap_h is not None and gap_h > DELIST_GAP_HOURS

        if missing:
            assert gap_h is not None  # `missing` already guarantees this
            if prev and prev["status"] == "delisted":
                continue  # already recorded; keep the snapshot stable
            # Delist (fresh, or a relisted row vanishing again).
            last_price = lst["price_zar"]
            under_offer = 1 if lst["under_offer"] else 0
            first_price = _first_price(conn, key, last_price)
            delisted_at = lst["last_seen"]  # last proof it was on the portal
            note = (
                f"missing from {lst['source']}/{lst['suburb_slug']}: cohort of "
                f"{size} refreshed {cohort_max}, listing last seen "
                f"{lst['last_seen']} ({gap_h / 24.0:.1f}d stale)")
            if under_offer:
                note += ("; likely sold — was under offer; likely_sold_price "
                         "is asking-at-disappearance (proxy, not a deeds record)")
            if prev and prev["status"] == "relisted":
                note += (f"; delisted again after relisting "
                         f"{prev.get('relisted_at') or '?'}")
            conn.execute(_UPSERT, {
                "listing_key": key,
                "status": "delisted",
                "first_seen": lst["first_seen"],
                "delisted_at": delisted_at,
                "relisted_at": prev.get("relisted_at") if prev else None,
                "days_on_market": _days_between(lst["first_seen"], delisted_at),
                "last_price": last_price,
                "under_offer_at_delist": under_offer,
                "likely_sold": under_offer,
                "likely_sold_price": last_price if under_offer else None,
                "price_at_first_seen": first_price,
                "total_cut_pct": _cut_pct(first_price, last_price),
                "note": note,
            })
            newly_delisted += 1
            continue

        # Present (or not provably missing) --------------------------------
        first_price = _first_price(conn, key, lst["price_zar"])
        if prev and prev["status"] == "delisted":
            # Back on the portal: relisted. Clearly didn't sell.
            off_days = _days_between(prev.get("delisted_at"), lst["last_seen"])
            note = (f"relisted after {off_days if off_days is not None else '?'}"
                    f" days off market (delisted {prev.get('delisted_at')})"
                    " — possible failed mandate")
            conn.execute(_UPSERT, {
                "listing_key": key,
                "status": "relisted",
                "first_seen": lst["first_seen"],
                "delisted_at": prev.get("delisted_at"),
                "relisted_at": lst["last_seen"],
                "days_on_market": _days_between(lst["first_seen"], now),
                "last_price": lst["price_zar"],
                "under_offer_at_delist": prev.get("under_offer_at_delist"),
                "likely_sold": 0,
                "likely_sold_price": None,
                "price_at_first_seen": first_price,
                "total_cut_pct": _cut_pct(first_price, lst["price_zar"]),
                "note": note,
            })
            newly_relisted += 1
        else:
            # Active row (or still-listed relisted row): refresh running DOM
            # so cma.py can read days_on_market uniformly.
            status = "relisted" if prev and prev["status"] == "relisted" else "active"
            conn.execute(_UPSERT, {
                "listing_key": key,
                "status": status,
                "first_seen": lst["first_seen"],
                "delisted_at": prev.get("delisted_at") if prev else None,
                "relisted_at": prev.get("relisted_at") if prev else None,
                "days_on_market": _days_between(lst["first_seen"], now),
                "last_price": lst["price_zar"],
                "under_offer_at_delist": prev.get("under_offer_at_delist") if prev else None,
                "likely_sold": 0,
                "likely_sold_price": None,
                "price_at_first_seen": first_price,
                "total_cut_pct": _cut_pct(first_price, lst["price_zar"]),
                "note": prev.get("note") if status == "relisted" and prev else None,
            })

    counts = {
        s: n for s, n in conn.execute(
            "SELECT status, COUNT(*) FROM listing_lifecycle GROUP BY status")
    }
    likely_sold_total = conn.execute(
        "SELECT COUNT(*) FROM listing_lifecycle WHERE likely_sold = 1"
    ).fetchone()[0]
    return {
        "active": counts.get("active", 0),
        "newly_delisted": newly_delisted,
        "newly_relisted": newly_relisted,
        "delisted_total": counts.get("delisted", 0),
        "likely_sold_total": likely_sold_total,
    }


# -------------------------------------------------------------------- stats

def stats(conn, suburb_slug: str | None = None) -> dict:
    """Lifecycle summary, optionally for one suburb (joined via listings)."""
    ensure_table(conn)
    where, params = "", ()
    if suburb_slug:
        where, params = " WHERE x.suburb_slug = ?", (suburb_slug,)
    rows = conn.execute(
        "SELECT lc.status, lc.days_on_market, lc.total_cut_pct, lc.likely_sold"
        " FROM listing_lifecycle lc JOIN listings x ON x.listing_key = lc.listing_key"
        " WHERE x.listing_type = 'sale'"
        + where.replace(" WHERE ", " AND ", 1), params).fetchall()

    dom_active = [r["days_on_market"] for r in rows
                  if r["status"] in ("active", "relisted")
                  and r["days_on_market"] is not None]
    dom_delisted = [r["days_on_market"] for r in rows
                    if r["status"] == "delisted"
                    and r["days_on_market"] is not None]
    cuts = [r["total_cut_pct"] for r in rows if r["total_cut_pct"]]
    return {
        "suburb_slug": suburb_slug,
        "listings": len(rows),
        "active": sum(1 for r in rows if r["status"] == "active"),
        "delisted": sum(1 for r in rows if r["status"] == "delisted"),
        "relisted": sum(1 for r in rows if r["status"] == "relisted"),
        "likely_sold": sum(1 for r in rows if r["likely_sold"]),
        "median_dom_active": round(statistics.median(dom_active), 1) if dom_active else None,
        "median_dom_delisted": round(statistics.median(dom_delisted), 1) if dom_delisted else None,
        "median_cut_pct": round(statistics.median(cuts), 2) if cuts else None,
    }


def history_comps(conn, suburb_slug: str, limit: int = 20) -> list[dict]:
    """Recent delisted / likely-sold rows for a suburb — the CMA comps feed.

    likely_sold_price is asking-at-disappearance: our best proxy without a
    licensed deeds feed, and labelled as such in `note`.
    """
    ensure_table(conn)
    rows = conn.execute(
        """SELECT lc.listing_key, x.title, x.suburb, x.url,
                  x.property_type, x.bedrooms, x.bathrooms,
                  x.floor_size_m2, x.erf_size_m2,
                  lc.last_price AS price_zar, lc.likely_sold,
                  lc.likely_sold_price, lc.delisted_at, lc.days_on_market,
                  lc.total_cut_pct, lc.under_offer_at_delist, lc.note
           FROM listing_lifecycle lc
           JOIN listings x ON x.listing_key = lc.listing_key
           WHERE x.suburb_slug = ? AND x.listing_type = 'sale'
             AND lc.status = 'delisted'
           ORDER BY lc.likely_sold DESC, lc.delisted_at DESC
           LIMIT ?""",
        (suburb_slug, limit)).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------- main

if __name__ == "__main__":
    import db

    with db.connect() as conn:
        result = update(conn)
        conn.commit()
        print("update():", result)
        print("\noverall:", stats(conn))
        busiest = [r[0] for r in conn.execute(
            "SELECT suburb_slug, COUNT(*) n FROM listings"
            " GROUP BY suburb_slug ORDER BY n DESC LIMIT 3")]
        for slug in busiest:
            print(f"{slug}:", stats(conn, slug))
