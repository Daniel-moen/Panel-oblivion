"""Comparative-market-analysis (comps) engine over the engine's own data.

Replaces the comps core of a Lightstone/LOOM CMA report: given a deduped
property group, find comparable listings among the OTHER property groups and
derive a defensible price-guidance band.

Non-obvious constraints this module lives with:

- Comps are asking prices from the same five-portal crawl, not transfer
  prices. Under-offer listings and delisted-likely-sold rows (from the
  optional `listing_lifecycle` table) are the closest thing to sale evidence,
  so they are weighted up in the price band and flagged in the notes.
- One comp per property group, never per listing — the same house carried by
  four portals is one data point, not four.
- `valuations` (municipal GV2022 per erf) and `listing_lifecycle` are built
  by sibling modules and MAY NOT EXIST in a given database. Everything that
  touches them feature-detects columns via PRAGMA and degrades to "no signal".
- Roughly half the rows lack floor_size_m2, so houses fall back to erf size
  for the R/m² arithmetic, and comps that cannot be size-compared at all are
  kept with a similarity penalty rather than discarded — the pool is small.
- A "price cut" is only counted within a single listing's own price_history;
  two portals quoting different prices for the same property is not a cut.
- Suburb slugs outside config.SUBURBS (stray crawl areas) have no region, so
  the region-widening step silently skips for them.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from datetime import datetime

import config

GOOD_ERF_STATUS = ("ok", "confirmed", "check")
MIN_COMPS_BEFORE_WIDENING = 5
SIZE_WINDOW = 0.30            # comp size within ±30% of the subject
ACTIVE_WINDOW_DAYS = 21       # last_seen this recent counts as active stock

_LAND_WORDS = ("vacant", "plot", "stand", " land")
_FLAT_WORDS = ("apartment", "flat", "penthouse", "studio", "sectional")
_HOUSE_WORDS = ("house", "villa", "townhouse", "farm", "cluster", "freehold",
                "cottage", "bungalow", "duplex")


# ------------------------------------------------------------------ helpers

def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return set()


def _bucket(property_type: str | None) -> str | None:
    """house | apartment | land — comps must share a bucket."""
    t = " " + (property_type or "").lower()
    for words, name in ((_LAND_WORDS, "land"), (_FLAT_WORDS, "apartment"),
                        (_HOUSE_WORDS, "house")):
        if any(w in t for w in words):
            return name
    return None


def _parse_date(s) -> datetime | None:
    """Portal listing dates arrive as '22 May 2026', '2023-04-25', ...;
    first_seen/last_seen as '2026-07-23 17:51:54'."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            d = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if 2000 <= d.year <= 2100:
            return d
    return None


def _slugish(s) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _round_zar(v: float | None) -> int | None:
    return None if v is None else int(round(v / 100_000.0) * 100_000)


def _median(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


def _region_of(suburb_slug: str | None) -> str | None:
    info = config.SUBURBS.get(suburb_slug or "")
    return info.get("region") if info else None


def _region_slugs(region: str | None) -> set[str]:
    if not region:
        return set()
    return {slug for slug, info in config.SUBURBS.items()
            if info.get("region") == region}


# ------------------------------------------- optional sibling-module tables

def _lifecycle_map(conn: sqlite3.Connection) -> dict[str, dict]:
    """{listing_key: {...}} from listing_lifecycle, {} if the table isn't
    built yet (a sibling agent owns it)."""
    cols = _columns(conn, "listing_lifecycle")
    if "listing_key" not in cols:
        return {}
    want = [c for c in ("status", "delisted_at", "likely_sold",
                        "likely_sold_price") if c in cols]
    try:
        rows = conn.execute(
            f"SELECT listing_key, {', '.join(want)} FROM listing_lifecycle"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {r["listing_key"]: {c: r[c] for c in want} for r in rows}


def _gv_value(conn: sqlite3.Connection, erf_number,
              suburb_hints: list) -> int | None:
    """Municipal GV2022 market value for this erf, if the valuations table
    exists and yields an unambiguous match (erf numbers repeat per suburb)."""
    if not erf_number:
        return None
    cols = _columns(conn, "valuations")
    erf_col = next((c for c in ("erf_number", "erf", "erf_no") if c in cols),
                   None)
    val_col = next((c for c in ("market_value", "gv_value", "gv2022_value",
                                "value") if c in cols), None)
    if not erf_col or not val_col:
        return None
    sub_col = next((c for c in ("suburb", "suburb_slug", "official_suburb",
                                "suburb_name") if c in cols), None)
    sub_sel = f", {sub_col} AS s" if sub_col else ", NULL AS s"
    try:
        rows = conn.execute(
            f"SELECT {val_col} AS v{sub_sel} FROM valuations"
            f" WHERE CAST({erf_col} AS TEXT) = ?",
            (str(erf_number),)).fetchall()
    except sqlite3.OperationalError:
        return None
    if not rows:
        return None
    if sub_col:
        hints = {_slugish(h) for h in suburb_hints if h}
        matched = [r for r in rows if _slugish(r["s"]) and any(
            _slugish(r["s"]) in h or h in _slugish(r["s"]) for h in hints)]
        if matched:
            rows = matched
        elif len(rows) > 1:
            return None          # same erf number in several suburbs
    if len(rows) > 1 and not sub_col:
        return None
    v = rows[0]["v"]
    # sub-R50k values are municipal-nominal (open space at R1,000), not anchors
    return int(v) if v and v >= 50000 else None


# ------------------------------------------------------------ group merging

def _members(conn: sqlite3.Connection, group_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT l.*, g.group_id, g.agency_count, g.source_count
           FROM property_groups g
           JOIN listings l ON l.listing_key = g.listing_key
           WHERE g.group_id = ?""", (group_id,)).fetchall()


def _rank_members(members: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """Most-complete member first; its fields win the merge."""
    return sorted(members, key=lambda m: (
        m["price_zar"] is not None,
        (m["floor_size_m2"] is not None) + (m["erf_size_m2"] is not None),
        m["photo_count"] or 0,
        len(m["description"] or "")), reverse=True)


def _pick_price(members: list[sqlite3.Row]) -> int | None:
    """Group asking price = the modal price across members; ties go to the
    price carried by the most recently seen member (portals lag each other
    after a reduction, so recency breaks the tie toward the current ask)."""
    seen: dict[int, tuple[int, str]] = {}
    for m in members:
        p = m["price_zar"]
        if not p:
            continue
        count, last = seen.get(p, (0, ""))
        seen[p] = (count + 1, max(last, m["last_seen"] or ""))
    if not seen:
        return None
    return max(seen.items(), key=lambda kv: kv[1])[0]


def _price_cut(conn: sqlite3.Connection, keys: list[str]) -> dict | None:
    """Deepest first-vs-latest price move among the members' own histories.
    cut_pct > 0 means a reduction."""
    best = None
    for k in keys:
        prices = [r["price_zar"] for r in conn.execute(
            "SELECT price_zar FROM price_history WHERE listing_key = ?"
            " ORDER BY observed_at", (k,)) if r["price_zar"]]
        if len(set(prices)) < 2 or prices[-1] == prices[0]:
            continue
        pct = round((prices[0] - prices[-1]) / prices[0] * 100, 1)
        if best is None or abs(pct) > abs(best["cut_pct"]):
            best = {"first_price": prices[0], "latest_price": prices[-1],
                    "cut_pct": pct}
    return best


def _days_on_market(members: list[sqlite3.Row]) -> tuple[int | None, str]:
    """Earliest portal listing_date wins (first_seen only reaches back to the
    crawl's start, so it undercounts); returns (days, which basis)."""
    listed = [d for d in (_parse_date(m["listing_date"]) for m in members) if d]
    if listed:
        return max(0, (datetime.now() - min(listed)).days), "listing_date"
    seen = [d for d in (_parse_date(m["first_seen"]) for m in members) if d]
    if seen:
        return max(0, (datetime.now() - min(seen)).days), "first_seen"
    return None, "unknown"


def _best_lifecycle(keys: list[str], lifecycle: dict) -> dict | None:
    """The most informative lifecycle row across a group's members —
    likely-sold beats delisted beats active."""
    rows = [lifecycle[k] for k in keys if k in lifecycle]
    if not rows:
        return None
    return max(rows, key=lambda r: (
        1 if r.get("likely_sold") or r.get("likely_sold_price") else 0,
        1 if r.get("status") == "delisted" else 0))


def _subject(conn: sqlite3.Connection, group_id: int) -> dict | None:
    """Merged best-of-group view: most-complete member wins per field."""
    members = _members(conn, group_id)
    if not members:
        return None
    ranked = _rank_members(members)
    best = ranked[0]

    def first(field, disallow=("", "-")):
        for m in ranked:
            v = m[field]
            if v is not None and v not in disallow:
                return v
        return None

    keys = [m["listing_key"] for m in members]
    erf = conn.execute(
        f"""SELECT erf_number, official_address, official_suburb,
                   parcel_area_m2, status
            FROM erf_lookup
            WHERE listing_key IN ({','.join('?' * len(keys))})
              AND status IN ({','.join('?' * len(GOOD_ERF_STATUS))})
              AND erf_number IS NOT NULL
            LIMIT 1""", (*keys, *GOOD_ERF_STATUS)).fetchone()

    history = [{"price_zar": r["price_zar"], "observed_at": r["observed_at"],
                "listing_key": r["listing_key"]}
               for r in conn.execute(
                   f"""SELECT listing_key, price_zar, observed_at
                       FROM price_history
                       WHERE listing_key IN ({','.join('?' * len(keys))})
                       ORDER BY observed_at""", keys)]

    dom, dom_basis = _days_on_market(members)
    gv_hints = [erf["official_suburb"] if erf else None,
                first("suburb"), first("suburb_slug")]
    gv = _gv_value(conn, erf["erf_number"] if erf else None, gv_hints)

    return {
        "group_id": group_id,
        "listing_key": best["listing_key"],
        "title": first("title"),
        "suburb": first("suburb"),
        "suburb_slug": first("suburb_slug"),
        "price_zar": _pick_price(members),
        "beds": first("bedrooms"),
        "baths": first("bathrooms"),
        "floor_size_m2": first("floor_size_m2"),
        "erf_size_m2": first("erf_size_m2"),
        "property_type": first("property_type"),
        "bucket": _bucket(first("property_type")),
        "erf_number": erf["erf_number"] if erf else None,
        "official_address": erf["official_address"] if erf else None,
        "official_suburb": erf["official_suburb"] if erf else None,
        "erf_status": erf["status"] if erf else None,
        "agencies": sorted({m["agency"].strip() for m in members
                            if m["agency"] and m["agency"].strip()}),
        "urls": [m["url"] for m in members],
        "photo_url": first("photo_url"),
        "under_offer": max((m["under_offer"] or 0) for m in members),
        "first_seen": min((m["first_seen"] or "") for m in members) or None,
        "days_on_market": dom,
        "days_on_market_basis": dom_basis,
        "price_history": history,
        "price_cut": _price_cut(conn, keys),
        "gv_value": gv,
    }


# ------------------------------------------------------------------- comps

def _candidates(conn: sqlite3.Connection, exclude_group: int,
                lifecycle: dict) -> list[dict]:
    """One representative per OTHER property group. Development launches are
    marketing exercises, not market evidence — a group with any development
    member is out."""
    by_group: dict[int, list[sqlite3.Row]] = {}
    for r in conn.execute(
            """SELECT l.*, g.group_id, g.agency_count
               FROM property_groups g
               JOIN listings l ON l.listing_key = g.listing_key
               WHERE g.group_id != ?""", (exclude_group,)):
        by_group.setdefault(r["group_id"], []).append(r)

    out = []
    for gid, members in by_group.items():
        if any(m["is_development"] for m in members):
            continue
        ranked = _rank_members(members)
        rep = ranked[0]

        def first(field, disallow=("", "-")):
            for m in ranked:
                v = m[field]
                if v is not None and v not in disallow:
                    return v
            return None

        keys = [m["listing_key"] for m in members]
        out.append({
            "group_id": gid,
            "listing_key": rep["listing_key"],
            "keys": keys,
            "title": first("title"),
            "suburb": first("suburb"),
            "suburb_slug": first("suburb_slug"),
            "price_zar": _pick_price(members),
            "beds": first("bedrooms"),
            "floor_size_m2": first("floor_size_m2"),
            "erf_size_m2": first("erf_size_m2"),
            "bucket": _bucket(first("property_type")),
            "url": first("url"),
            "agency_count": max((m["agency_count"] or 1) for m in members),
            "under_offer": max((m["under_offer"] or 0) for m in members),
            "last_seen": max((m["last_seen"] or "") for m in members) or None,
            "lifecycle": _best_lifecycle(keys, lifecycle),
        })
    return out


def _size_ratio(subject: dict, cand: dict) -> tuple[float | None, str | None]:
    """(cand_size / subject_size, metric) on a like-for-like metric: floor
    against floor, else erf against erf for house-bucket pairs."""
    sf, cf = subject.get("floor_size_m2"), cand.get("floor_size_m2")
    if sf and cf:
        return cf / sf, "floor"
    if subject.get("bucket") == "house":
        se, ce = subject.get("erf_size_m2"), cand.get("erf_size_m2")
        if se and ce:
            return ce / se, "erf"
    return None, None


def _passes(subject: dict, cand: dict) -> bool:
    if not cand["price_zar"]:
        return False
    if subject.get("bucket") and cand["bucket"] != subject["bucket"]:
        return False
    if subject.get("beds") and cand["beds"] \
            and abs(subject["beds"] - cand["beds"]) > 1:
        return False
    ratio, _ = _size_ratio(subject, cand)
    if ratio is not None and not (1 - SIZE_WINDOW <= ratio <= 1 + SIZE_WINDOW):
        return False
    return True


def _similarity(subject: dict, cand: dict, same_suburb: bool) -> int:
    """0-100: size proximity 40, beds 20, location 25, recency 15. Comps that
    cannot be size-compared score a flat 15 on size, so size-matched comps
    always outrank them."""
    score = 0.0
    ratio, _ = _size_ratio(subject, cand)
    if ratio is not None:
        score += 40 * max(0.0, 1 - abs(ratio - 1) / SIZE_WINDOW)
    else:
        score += 15
    sb, cb = subject.get("beds"), cand["beds"]
    if sb and cb:
        diff = abs(sb - cb)
        score += 20 if diff == 0 else (12 if diff <= 1 else 4)
    else:
        score += 8
    score += 25 if same_suburb else 12
    seen = _parse_date(cand["last_seen"])
    if seen:
        days = max(0, (datetime.now() - seen).days)
        score += 15 * max(0.0, 1 - days / 120)
    return round(min(100.0, score))


def _comp_dict(conn: sqlite3.Connection, subject: dict, cand: dict,
               same_suburb: bool) -> dict:
    price = cand["price_zar"]
    lc = cand["lifecycle"] or {}
    return {
        "group_id": cand["group_id"],
        "listing_key": cand["listing_key"],
        "title": cand["title"],
        "suburb": cand["suburb"],
        "price_zar": price,
        "beds": cand["beds"],
        "floor_size_m2": cand["floor_size_m2"],
        "erf_size_m2": cand["erf_size_m2"],
        "r_per_m2_floor": round(price / cand["floor_size_m2"])
        if price and cand["floor_size_m2"] else None,
        "r_per_m2_erf": round(price / cand["erf_size_m2"])
        if price and cand["erf_size_m2"] else None,
        "url": cand["url"],
        "agency_count": cand["agency_count"],
        "under_offer": cand["under_offer"],
        "price_cut": _price_cut(conn, cand["keys"]),
        "lifecycle_status": lc.get("status"),
        "likely_sold_price": lc.get("likely_sold_price"),
        "distance": "same suburb" if same_suburb else "same region",
        "similarity": _similarity(subject, cand, same_suburb),
    }


def _find_comps(conn: sqlite3.Connection, subject: dict,
                limit: int) -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    lifecycle = _lifecycle_map(conn)
    pool = _candidates(conn, subject["group_id"], lifecycle)

    if not subject.get("bucket"):
        notes.append("subject property type unknown — comps not filtered "
                     "by house/apartment bucket")
    if not subject.get("floor_size_m2") and not (
            subject.get("bucket") == "house" and subject.get("erf_size_m2")):
        notes.append("subject size unknown — comps not filtered by size")

    slug = subject.get("suburb_slug")
    local = [c for c in pool if c["suburb_slug"] == slug and _passes(subject, c)]
    comps = [_comp_dict(conn, subject, c, True) for c in local]

    if len(comps) < MIN_COMPS_BEFORE_WIDENING:
        region = _region_of(slug)
        widened = _region_slugs(region) - {slug}
        regional = [c for c in pool if c["suburb_slug"] in widened
                    and _passes(subject, c)]
        if regional:
            comps += [_comp_dict(conn, subject, c, False) for c in regional]
            plural = "comp" if len(local) == 1 else "comps"
            notes.append(f"only {len(local)} {plural} in {slug} — widened to "
                         f"{region} ({len(regional)} added)")
        elif region is None and slug:
            notes.append(f"'{slug}' is not a configured suburb — cannot "
                         "widen to a region")

    comps.sort(key=lambda c: (-c["similarity"], -(c["price_zar"] or 0)))
    comps = comps[:limit]
    if len(comps) < MIN_COMPS_BEFORE_WIDENING:
        plural = "comp" if len(comps) == 1 else "comps"
        notes.append(f"only {len(comps)} {plural} — treat the range as "
                     "indicative, not evidence")
    return comps, notes


def comps_for(conn: sqlite3.Connection, group_id: int,
              limit: int = 12) -> list[dict]:
    subject = _subject(conn, group_id)
    if subject is None:
        return []
    comps, _ = _find_comps(conn, subject, limit)
    return comps


# ------------------------------------------------------------- price range

def _comp_weight(comp: dict) -> int:
    """Sale-evidence weighting: likely-sold 3×, under-offer 2×, plain ask 1×."""
    if comp.get("likely_sold_price"):
        return 3
    if comp.get("under_offer"):
        return 2
    return 1


def _effective_price(comp: dict) -> int | None:
    return comp.get("likely_sold_price") or comp.get("price_zar")


def _price_range(subject: dict, comps: list[dict],
                 stats: dict | None = None) -> tuple[dict, list[str]]:
    notes: list[str] = []
    stats = stats or {}
    slug = subject.get("suburb_slug") or "?"
    if any(c["distance"] == "same region" for c in comps):
        slug += " + region"

    # subject's size metric: floor preferred; erf for houses missing floor
    metric, size = None, None
    if subject.get("floor_size_m2"):
        metric, size = "floor_size_m2", subject["floor_size_m2"]
    elif subject.get("bucket") == "house" and subject.get("erf_size_m2"):
        metric, size = "erf_size_m2", subject["erf_size_m2"]

    weighted_prices, weighted_ppm2, ppm2_n = [], [], 0
    for c in comps:
        price = _effective_price(c)
        if not price:
            continue
        w = _comp_weight(c)
        weighted_prices += [price] * w
        if metric and c.get(metric):
            weighted_ppm2 += [price / c[metric]] * w
            ppm2_n += 1
    if any(_comp_weight(c) > 1 for c in comps):
        notes.append("under-offer / likely-sold comps weighted up — the "
                     "closest thing to sale evidence in the pool")

    if metric and size and ppm2_n >= 3:
        q1, q2, q3 = statistics.quantiles(weighted_ppm2, n=4,
                                          method="inclusive")
        low, high = q1 * size, q3 * size
        price_med = statistics.median(weighted_prices)
        mid = (q2 * size + price_med) / 2   # sanity blend vs straight prices
        if not (low <= mid <= high):
            mid = min(max(mid, low), high)
            notes.append("comp median price sits outside the R/m² band — "
                         "mid clamped to the band")
        label = "floor" if metric == "floor_size_m2" else "erf"
        basis = (f"IQR of R/m² ({label}) across {ppm2_n} comps in {slug}, "
                 f"mid blended with comp median price")
    elif len([c for c in comps if _effective_price(c)]) >= 3:
        n = len([c for c in comps if _effective_price(c)])
        q1, mid, q3 = statistics.quantiles(weighted_prices, n=4,
                                           method="inclusive")
        low, high = q1, q3
        why = ("subject size unknown" if not (metric and size)
               else "too few size-comparable comps")
        basis = f"quartiles of comp prices across {n} comps in {slug} ({why})"
        # Straight price quartiles get skewed by bigger/smaller units. When
        # the subject's own size IS known, anchor the band on the suburb's
        # median R/m² × subject size.
        anchor = None
        if metric == "floor_size_m2" and size \
                and stats.get("median_r_per_m2_floor"):
            anchor = stats["median_r_per_m2_floor"] * size
        elif metric == "erf_size_m2" and size \
                and stats.get("median_r_per_m2_erf_houses"):
            anchor = stats["median_r_per_m2_erf_houses"] * size
        if anchor:
            low = (low + anchor * 0.85) / 2
            mid = (mid + anchor) / 2
            high = (high + anchor * 1.15) / 2
            basis = (f"comp price quartiles across {n} comps in {slug}, "
                     f"blended with suburb median R/m² x subject size")
        notes.append(f"R/m² band unavailable ({why}) — fell back to "
                     "comp price quartiles"
                     + (" anchored on suburb median R/m²" if anchor else ""))
    elif weighted_prices:
        n = len([c for c in comps if _effective_price(c)])
        low, mid, high = (min(weighted_prices),
                          statistics.median(weighted_prices),
                          max(weighted_prices))
        basis = f"span of {n} comp price(s) in {slug} — too few for quartiles"
        notes.append("fewer than 3 priced comps — range is the raw span, "
                     "low confidence")
    else:
        return ({"low": None, "mid": None, "high": None,
                 "basis": "no usable comps"},
                notes + ["no priced comps found — no price guidance possible"])

    return ({"low": _round_zar(low), "mid": _round_zar(mid),
             "high": _round_zar(high), "basis": basis}, notes)


# ------------------------------------------------------------ suburb stats

def suburb_stats(conn: sqlite3.Connection, suburb_slug: str) -> dict:
    """Market snapshot for one suburb, at property-group level (developments
    excluded). "Active" = seen in the last ACTIVE_WINDOW_DAYS and not marked
    delisted by listing_lifecycle (when that table exists)."""
    lifecycle = _lifecycle_map(conn)
    by_group: dict[int, list[sqlite3.Row]] = {}
    for r in conn.execute(
            """SELECT l.*, g.group_id, g.agency_count
               FROM listings l
               JOIN property_groups g ON g.listing_key = l.listing_key
               WHERE l.suburb_slug = ?""", (suburb_slug,)):
        by_group.setdefault(r["group_id"], []).append(r)

    now = datetime.now()
    active_groups, asking, ppm2_floor, ppm2_erf_houses = [], [], [], []
    doms_listed, doms_seen, cut_pcts = [], [], []
    cut_count = 0

    for gid, members in by_group.items():
        if any(m["is_development"] for m in members):
            continue
        keys = [m["listing_key"] for m in members]
        lc = _best_lifecycle(keys, lifecycle)
        last = _parse_date(max((m["last_seen"] or "") for m in members))
        stale = last is None or (now - last).days > ACTIVE_WINDOW_DAYS
        delisted = bool(lc and lc.get("status") == "delisted")
        if stale or delisted:
            continue
        active_groups.append(gid)

        ranked = _rank_members(members)
        price = _pick_price(members)
        floor = next((m["floor_size_m2"] for m in ranked
                      if m["floor_size_m2"]), None)
        erf = next((m["erf_size_m2"] for m in ranked if m["erf_size_m2"]), None)
        bucket = _bucket(next((m["property_type"] for m in ranked
                               if m["property_type"]), None))
        if price:
            asking.append(price)
            if floor:
                ppm2_floor.append(price / floor)
            if erf and bucket == "house":
                ppm2_erf_houses.append(price / erf)
        dom, dom_basis = _days_on_market(members)
        if dom is not None:
            (doms_listed if dom_basis == "listing_date" else doms_seen).append(dom)
        cut = _price_cut(conn, keys)
        if cut:
            cut_count += 1
            if cut["cut_pct"] > 0:
                cut_pcts.append(cut["cut_pct"])

    n = len(active_groups)
    med_floor = _median(ppm2_floor)
    med_erf = _median(ppm2_erf_houses)
    # first_seen only reaches back to the crawl's start, so it massively
    # under-counts DOM — prefer groups with a real portal listing_date.
    doms = doms_listed or doms_seen
    return {
        "suburb_slug": suburb_slug,
        "active_count": n,
        "median_asking_zar": _median(asking),
        "median_r_per_m2_floor": round(med_floor) if med_floor else None,
        "median_r_per_m2_erf_houses": round(med_erf) if med_erf else None,
        "median_days_on_market": _median(doms),
        "days_on_market_basis": ("listing_date" if doms_listed
                                 else "first_seen" if doms_seen else None),
        "days_on_market_sample": len(doms),
        "price_cut_share": round(cut_count / n, 2) if n else None,
        "median_cut_pct": _median(cut_pcts),
    }


# ---------------------------------------------------------------- analysis

def analyse(conn: sqlite3.Connection, group_id: int) -> dict | None:
    """Full CMA for one property group. JSON-serializable; None when the
    group doesn't exist."""
    subject = _subject(conn, group_id)
    if subject is None:
        return None

    comps, notes = _find_comps(conn, subject, limit=12)
    stats = suburb_stats(conn, subject["suburb_slug"]) \
        if subject.get("suburb_slug") else {}
    price_range, range_notes = _price_range(subject, comps, stats)
    notes += range_notes

    if subject.get("gv_value") and subject.get("price_zar"):
        ratio = subject["price_zar"] / subject["gv_value"]
        notes.append(f"asking is {ratio:.2f}x the municipal GV2022 value "
                     f"(R {subject['gv_value']:,})")
    if subject.get("price_cut"):
        cut = subject["price_cut"]
        notes.append(f"subject already moved from R {cut['first_price']:,} "
                     f"to R {cut['latest_price']:,} ({cut['cut_pct']}%)")
    if subject.get("price_zar") and price_range.get("high") \
            and subject["price_zar"] > price_range["high"] * 1.15:
        local = sum(1 for c in comps if c["distance"] == "same suburb")
        if comps and local >= len(comps) / 2:
            notes.append("asking price sits well above the comp band — "
                         "overpricing is the pitch angle")
        else:
            notes.append("asking price sits well above the comp band, but "
                         "the band leans on out-of-suburb comps — verify "
                         "before pitching overpricing")

    return {
        "group_id": group_id,
        "subject": subject,
        "comps": comps,
        "suburb_stats": stats,
        "price_range": price_range,
        "notes": notes,
    }


# --------------------------------------------------------------------- CLI

if __name__ == "__main__":
    import db

    with db.connect() as conn:
        if len(sys.argv) > 1:
            gid = int(sys.argv[1])
        else:
            row = conn.execute(
                f"""SELECT g.group_id FROM property_groups g
                    JOIN scores s ON s.listing_key = g.listing_key
                    JOIN erf_lookup e ON e.listing_key = g.listing_key
                    WHERE s.sellable = 1
                      AND e.status IN ({','.join('?' * len(GOOD_ERF_STATUS))})
                      AND e.erf_number IS NOT NULL
                    ORDER BY g.group_id LIMIT 1""",
                GOOD_ERF_STATUS).fetchone()
            if row is None:
                sys.exit("no sellable group with a resolved erf — "
                         "pass a group_id")
            gid = row["group_id"]
        result = analyse(conn, gid)
        if result is None:
            sys.exit(f"group {gid} not found")
        print(json.dumps(result, indent=2, ensure_ascii=False))
