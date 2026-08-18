"""Cross-portal duplicate detection — the core open-mandate signal.

One physical home marketed by two or more *different agencies* is the
strongest evidence available that the seller has not granted a sole mandate.
Before this engine crawled multiple portals that could only be spotted when
two agencies both listed on Property24; now the same house showing up under
Seeff on seeff.com, Pam Golding on pamgolding.co.za and a third agency on
Property24 is caught directly.

Matching accumulates evidence rather than applying one rule, because each
portal publishes a different subset of facts (Seeff gives no coordinates,
Private Property gives no agency, RE/MAX gives everything). A pair merges at
config.MATCH_THRESHOLD.

Precision is deliberately favoured over recall: a false merge would tell the
team "this is an open mandate" when it isn't, wasting a pitch. A missed merge
only costs a signal the AI scorer may still catch from the description.
"""

from __future__ import annotations

import json
import math
import sqlite3
from itertools import combinations

import config
from sources.base import canonical_agency

# Evidence weights. A confirmed street-address match is decisive on its own;
# everything else has to combine.
W_ADDRESS = 1.00
# Deliberately below the threshold even when combined with beds+baths+type
# (0.70+0.12+0.08+0.05 = 0.95): every apartment in one block shares a single
# coordinate, so proximity must be corroborated by a size or price match
# before two listings are called the same home.
W_GEO = 0.70
W_ERF = 0.45
# Floor size must corroborate, never identify: it is agent-measured, rounded,
# and near-identical across every 3-bed in a cookie-cutter estate. At 0.45,
# floor+price+beds+baths+type = 1.05 cleared the threshold and chained 93
# Langebaan Country Estate homes into one "93-agency" property. At 0.25 that
# combination stops at 0.85; floor still tips a geo or erf match over the line.
W_FLOOR = 0.25
W_PRICE = 0.35
W_BEDS = 0.12
W_BATHS = 0.08
W_TYPE = 0.05


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _within(x, y, tol) -> bool | None:
    """True/False if both known, None if either is missing."""
    if x is None or y is None:
        return None
    x, y = float(x), float(y)
    if max(abs(x), abs(y)) == 0:
        return x == y
    return abs(x - y) / max(abs(x), abs(y)) <= tol


def match_score(a: sqlite3.Row, b: sqlite3.Row) -> tuple[float, list[str]]:
    """Evidence score that a and b are the same physical property."""
    if a["suburb_slug"] != b["suburb_slug"]:
        return 0.0, []

    evidence: list[str] = []

    # ---- hard disqualifiers ------------------------------------------
    if a["bedrooms"] is not None and b["bedrooms"] is not None:
        if abs(a["bedrooms"] - b["bedrooms"]) > 0.01:
            return 0.0, []
    if a["bathrooms"] is not None and b["bathrooms"] is not None:
        # portals round differently (6 vs 6.5), but not by more than one
        if abs(a["bathrooms"] - b["bathrooms"]) > 1.0:
            return 0.0, []

    # Two known, different addresses are different homes — this is what keeps
    # separate units in one apartment block (identical coordinates, same beds
    # and baths) from being merged into a single "multi-agency" property.
    if a["street_address"] and b["street_address"] \
            and a["street_address"] != b["street_address"]:
        return 0.0, []

    addr_match = bool(a["street_address"] and b["street_address"]
                      and a["street_address"] == b["street_address"])

    if not addr_match and a["price_zar"] and b["price_zar"]:
        hi = max(a["price_zar"], b["price_zar"])
        lo = min(a["price_zar"], b["price_zar"])
        if lo / hi < 0.70:      # >30% apart: different homes, or stale beyond use
            return 0.0, []

    # ---- accumulate evidence -----------------------------------------
    score = 0.0
    if addr_match:
        score += W_ADDRESS
        evidence.append(f"same address ({a['street_address']})")

    if (a["latitude"] is not None and b["latitude"] is not None
            and a["longitude"] is not None and b["longitude"] is not None):
        metres = _haversine_m(a["latitude"], a["longitude"],
                              b["latitude"], b["longitude"])
        if metres <= config.GEO_MATCH_METRES:
            score += W_GEO
            evidence.append(f"coordinates {metres:.0f}m apart")

    if _within(a["erf_size_m2"], b["erf_size_m2"], config.SIZE_TOLERANCE):
        score += W_ERF
        evidence.append(f"erf {a['erf_size_m2']:.0f}m²")
    if _within(a["floor_size_m2"], b["floor_size_m2"], config.SIZE_TOLERANCE):
        score += W_FLOOR
        evidence.append(f"floor {a['floor_size_m2']:.0f}m²")
    if _within(a["price_zar"], b["price_zar"], config.PRICE_TOLERANCE):
        score += W_PRICE
        evidence.append("price within 7%")
    if a["bedrooms"] is not None and b["bedrooms"] is not None:
        score += W_BEDS
    if a["bathrooms"] is not None and b["bathrooms"] is not None \
            and abs(a["bathrooms"] - b["bathrooms"]) < 0.01:
        score += W_BATHS
    if a["property_type"] and b["property_type"] \
            and a["property_type"].split("/")[0].strip().lower() == \
            b["property_type"].split("/")[0].strip().lower():
        score += W_TYPE

    return score, evidence


def rebuild_groups(conn: sqlite3.Connection) -> dict:
    """Union-find over all listings; rewrites property_groups. Returns stats."""
    rows = conn.execute("SELECT * FROM listings").fetchall()
    parent = {r["listing_key"]: r["listing_key"] for r in rows}
    evidence_log: dict[str, list[str]] = {}
    # Known street addresses per component. The pairwise rule "two different
    # addresses are different homes" is worthless under transitive union: in a
    # cookie-cutter estate, 1482 St Laurent and 1547 Le Juille each match the
    # same addressless portal rows on erf+price and end up chained into one
    # group anyway. So the veto is enforced per component: a union that would
    # put two different known addresses in one group is refused.
    addrs = {r["listing_key"]:
             ({r["street_address"]} if r["street_address"] else set())
             for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y, why) -> bool:
        rx, ry = find(x), find(y)
        if rx == ry:
            return True
        ax, ay = addrs[rx], addrs[ry]
        if ax and ay and not (ax & ay):
            return False    # would bridge two different known addresses
        parent[ry] = rx
        addrs[rx] = ax | ay
        evidence_log.setdefault(rx, []).extend(
            evidence_log.pop(ry, []) + why)
        return True

    by_suburb: dict[str, list] = {}
    for r in rows:
        by_suburb.setdefault(r["suburb_slug"], []).append(r)

    # Strongest evidence unions first, so address-confirmed merges claim their
    # component's address before fuzzy erf/price pairs get a chance to bridge.
    scored_pairs = []
    for suburb_rows in by_suburb.values():
        for a, b in combinations(suburb_rows, 2):
            score, why = match_score(a, b)
            if score >= config.MATCH_THRESHOLD:
                scored_pairs.append((score, a, b, why))
    scored_pairs.sort(key=lambda p: -p[0])

    pairs_matched = 0
    for score, a, b, why in scored_pairs:
        if union(a["listing_key"], b["listing_key"],
                 [f"{a['source']}+{b['source']}: " + ", ".join(why)]):
            pairs_matched += 1

    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(find(r["listing_key"]), []).append(r)

    conn.execute("DELETE FROM property_groups")
    multi_agency = multi_source = 0
    for gid, (root, members) in enumerate(groups.items()):
        agencies = {a for a in (canonical_agency(m["agency"]) for m in members)
                    if a}
        sources = {m["source"] for m in members}
        agency_count = max(len(agencies), 1)
        if agency_count > 1:
            multi_agency += 1
        if len(sources) > 1:
            multi_source += 1
        why = json.dumps(evidence_log.get(root, [])[:6], ensure_ascii=False)
        for m in members:
            conn.execute(
                "INSERT INTO property_groups (group_id, listing_key,"
                " agency_count, source_count, match_evidence)"
                " VALUES (?, ?, ?, ?, ?)",
                (gid, m["listing_key"], agency_count, len(sources), why),
            )
    return {
        "listings": len(rows),
        "groups": len(groups),
        "pairs_matched": pairs_matched,
        "multi_agency_groups": multi_agency,
        "multi_source_groups": multi_source,
    }
