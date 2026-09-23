"""Call brief: the one screen an agent reads in the minute before dialling.

The CMA answers "what is it worth"; this answers "what do I say". It merges
the facts the engine already holds — the group's listings, the score, the erf
and its municipal value, the price history, the suburb's own numbers — into
hard facts, talking points, cool facts, discovery questions, objection
handling and a short list of things not to say.

Two layers, deliberately separable:

- The deterministic brief needs no API key and no network. It is the one the
  dashboard always shows, so an agent on a machine with no credentials is
  never left with an empty screen.
- The AI pass (finder._ask, same provider order as scoring) rewrites the same
  facts into spoken language and adds an opener. It lives under brief["ai"]
  next to the deterministic sections, never instead of them.

The pitch matches caller.py's voice agent on purpose — the two are the same
conversation, one held by a person and one by a machine: Oblivion markets
homes with cinematic films, an open mandate means adding Oblivion costs the
owner nothing, the ask is a free no-obligation film consultation and
valuation, and the current agent is never disparaged. POPIA: only facts the
owner's own listing already publishes.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any

import cma
import config
import scorer
import valuations

DDL = """
-- One cached brief per property id. `fingerprint` is the hash of the facts
-- the brief is built from, so a crawl that changes the price or adds an
-- agency invalidates it without anything having to remember to.
CREATE TABLE IF NOT EXISTS call_briefs (
    gid         TEXT PRIMARY KEY,
    fingerprint TEXT,
    built_at    TEXT,
    backend     TEXT,     -- 'kimi:...' when the AI pass wrote it, else NULL
    body        TEXT      -- the whole brief as JSON
);
"""

MAX_TALKING_POINTS = 8
MAX_COOL_FACTS = 6
MAX_AREA_FACTS = 2
MAX_QUESTIONS = 5
COOL_FACT_CHARS = 160
SUBURB_STATS_TTL = 300.0       # seconds; suburb_stats walks the whole suburb


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)


# ------------------------------------------------------------------ helpers

def _is_group_id(gid: str) -> bool:
    return gid.isdigit()


def _rget(row, key, default=None):
    """sqlite3.Row lookup that tolerates a column this DB doesn't have yet."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def _pct(part: float | None, whole: float | None) -> int | None:
    """part vs whole as a signed percentage: 1.24 against 1.0 -> +24."""
    if not part or not whole:
        return None
    return int(round((part / whole - 1) * 100))


def _fmt_r(v) -> str:
    return "POA" if not v else "R" + f"{int(v):,}".replace(",", " ")


def _fmt_m(v) -> str:
    """R28.5m — how an agent says a price out loud."""
    if not v:
        return "POA"
    if v < 1_000_000:
        return _fmt_r(v)
    s = f"{v / 1e6:.2f}".rstrip("0").rstrip(".")
    return f"R{s}m"


def _fmt_area(v) -> str:
    if not v:
        return "—"
    if v >= 10_000:
        return f"{v / 10_000:.1f}".rstrip("0").rstrip(".") + " ha"
    return f"{int(round(v)):,}".replace(",", " ") + " m²"


def _plural(n: int, word: str) -> str:
    if n == 1:
        return f"{n} {word}"
    return f"{n} " + (word[:-1] + "ies" if word.endswith("y") else word + "s")


# ---------------------------------------------------------------- the group

def _members(conn: sqlite3.Connection, gid: str) -> list[sqlite3.Row]:
    """Every listing row behind this id — the group's members, or the one
    listing behind a 'solo-<key>' id."""
    if gid.startswith("solo-"):
        return conn.execute("SELECT * FROM listings WHERE listing_key = ?",
                            (gid[5:],)).fetchall()
    if _is_group_id(gid):
        return conn.execute(
            """SELECT l.* FROM property_groups g
               JOIN listings l ON l.listing_key = g.listing_key
               WHERE CAST(g.group_id AS TEXT) = ?""", (gid,)).fetchall()
    return []


def _erf_row(conn: sqlite3.Connection, keys: list[str]) -> sqlite3.Row | None:
    q = ",".join("?" * len(keys))
    return conn.execute(
        f"""SELECT erf_number, COALESCE(portion, '') AS portion,
                   official_address, official_suburb, parcel_area_m2, status,
                   latitude, longitude
            FROM erf_lookup
            WHERE listing_key IN ({q})
              AND status IN ('confirmed', 'ok', 'check')
              AND erf_number IS NOT NULL
            ORDER BY status = 'confirmed' DESC LIMIT 1""", keys).fetchone()


def _solo_subject(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """cma._subject's shape for an ungrouped listing. The merge logic there
    is all about reconciling members; with one member it collapses to the
    row itself, so only the erf/GV/price-history joins are worth repeating."""
    key = row["listing_key"]
    erf = _erf_row(conn, [key])
    history = [{"price_zar": r["price_zar"], "observed_at": r["observed_at"],
                "listing_key": r["listing_key"]}
               for r in conn.execute(
                   """SELECT listing_key, price_zar, observed_at
                      FROM price_history WHERE listing_key = ?
                      ORDER BY observed_at""", (key,))]
    dom, basis = cma._days_on_market([row])
    return {
        "group_id": None,
        "listing_key": key,
        "title": row["title"],
        "suburb": row["suburb"],
        "suburb_slug": row["suburb_slug"],
        "price_zar": row["price_zar"],
        "beds": row["bedrooms"],
        "baths": row["bathrooms"],
        "floor_size_m2": row["floor_size_m2"],
        "erf_size_m2": row["erf_size_m2"],
        "property_type": row["property_type"],
        "bucket": cma._bucket(row["property_type"]),
        "erf_number": erf["erf_number"] if erf else None,
        "official_address": erf["official_address"] if erf else None,
        "official_suburb": erf["official_suburb"] if erf else None,
        "erf_status": erf["status"] if erf else None,
        "agencies": [row["agency"].strip()] if (row["agency"] or "").strip() else [],
        "urls": [row["url"]],
        "photo_url": row["photo_url"],
        "under_offer": row["under_offer"] or 0,
        "first_seen": row["first_seen"],
        "days_on_market": dom,
        "days_on_market_basis": basis,
        "price_history": history,
        "price_cut": cma._price_cut(conn, [key]),
        "gv_value": None,
    }


def _subject(conn: sqlite3.Connection, gid: str,
             members: list[sqlite3.Row]) -> dict:
    if _is_group_id(gid):
        subj = cma._subject(conn, int(gid))
    else:
        subj = _solo_subject(conn, members[0])
    subj["gid"] = gid
    return subj


def _augment(conn: sqlite3.Connection, subj: dict,
             members: list[sqlite3.Row]) -> None:
    """The fields a phone call needs that a comps engine doesn't: the full
    description (never the 300-char table excerpt), who is marketing it on
    which portal with how many photos, and where it physically is."""
    from sources.base import canonical_agency

    ranked = cma._rank_members(members)
    best = ranked[0]
    subj["description"] = next(
        (m["description"] for m in ranked if (m["description"] or "").strip()), "")
    subj["street_address_raw"] = next(
        (m["street_address_raw"] for m in ranked
         if (m["street_address_raw"] or "").strip()), None)
    subj["property_type"] = subj.get("property_type") or best["property_type"]
    for field in ("garages", "parking", "levies", "rates", "pool",
                  "listing_date", "mandate_text", "mandate_explicit"):
        subj[field] = next((m[field] for m in ranked if m[field] not in (None, "", "-")),
                           None)
    subj["is_development"] = max((m["is_development"] or 0) for m in members)
    subj["price_reduced"] = max((m["price_reduced"] or 0) for m in members)
    subj["under_offer"] = max((m["under_offer"] or 0) for m in members)
    subj["last_seen"] = max((m["last_seen"] or "") for m in members) or None
    subj["listing_type"] = _rget(best, "listing_type", "sale")
    subj["agent_names"] = sorted({(m["agent_name"] or "").strip()
                                  for m in members if (m["agent_name"] or "").strip()})
    # canonical_agency collapses "Pam Golding (Atlantic Seaboard)" and "Pam
    # Golding Properties - Atlantic Seaboard" to one brand — that is what
    # counts mandates. For reading aloud, keep the shortest name each brand
    # actually publishes rather than the lowercase slug.
    by_brand: dict[str, str] = {}
    for m in members:
        brand = canonical_agency(m["agency"])
        name = (m["agency"] or "").strip()
        if not brand or not name:
            continue
        if brand not in by_brand or len(name) < len(by_brand[brand]):
            by_brand[brand] = name
    subj["brands"] = sorted(by_brand)
    subj["brand_names"] = [by_brand[b] for b in sorted(by_brand)]
    subj["listings"] = [{
        "source": m["source"],
        "url": m["url"],
        "agency": m["agency"],
        "agent_name": m["agent_name"],
        "price_zar": m["price_zar"],
        "photo_count": m["photo_count"],
        "listing_date": m["listing_date"],
        "last_seen": m["last_seen"],
    } for m in sorted(members, key=lambda m: -(m["photo_count"] or 0))]
    subj["photo_count"] = max((m["photo_count"] or 0) for m in members) or None
    subj["source_count"] = len({m["source"] for m in members})
    subj["listing_count"] = len(members)
    # Map position: the resolved parcel centroid first (a cadastre fact),
    # then any portal pin — same order the dashboard trusts them in.
    erf = _erf_row(conn, [m["listing_key"] for m in members])
    subj["erf_portion"] = erf["portion"] if erf else ""
    subj["parcel_area_m2"] = erf["parcel_area_m2"] if erf else None
    lat = lng = None
    if erf and erf["latitude"] and erf["longitude"]:
        lat, lng = erf["latitude"], erf["longitude"]
    else:
        pin = next((m for m in members if m["latitude"] and m["longitude"]), None)
        if pin:
            lat, lng = pin["latitude"], pin["longitude"]
    subj["latitude"], subj["longitude"] = lat, lng


def _score(conn: sqlite3.Connection, members: list[sqlite3.Row]) -> dict:
    """The group's loudest score row — the member the scorer actually judged
    (several members can carry one each; the most recent wins)."""
    keys = [m["listing_key"] for m in members]
    q = ",".join("?" * len(keys))
    row = conn.execute(
        f"""SELECT * FROM scores WHERE listing_key IN ({q})
            ORDER BY scored_at DESC LIMIT 1""", keys).fetchone()
    return dict(row) if row else {}


def _lifecycle(conn: sqlite3.Connection, keys: list[str]) -> dict:
    """relisted / days off market from lifecycle.py's table, {} if it never ran."""
    q = ",".join("?" * len(keys))
    try:
        rows = conn.execute(
            f"""SELECT status, delisted_at, relisted_at, days_on_market
                FROM listing_lifecycle WHERE listing_key IN ({q})""", keys).fetchall()
    except sqlite3.OperationalError:
        return {}
    out: dict[str, Any] = {"relisted": False, "days_off_market": None}
    off = []
    for r in rows:
        if r["status"] != "relisted":
            continue
        out["relisted"] = True
        gone, back = cma._parse_date(r["delisted_at"]), cma._parse_date(r["relisted_at"])
        if gone and back and back > gone:
            off.append((back - gone).days)
    out["days_off_market"] = max(off) if off else None
    return out


def _gv(conn: sqlite3.Connection, subj: dict) -> dict:
    """Municipal valuation for the resolved erf, with its roll year.

    Erf numbers repeat per town, and valuations.get() keys on erf + portion
    alone, so the row is only accepted when its own suburb agrees with the
    property's — a Langebaan erf 800 must never price a Camps Bay house.
    """
    erf_no = subj.get("erf_number")
    if not erf_no:
        return {}
    try:
        row = valuations.get(conn, str(erf_no), subj.get("erf_portion") or "")
    except sqlite3.OperationalError:
        return {}
    if not row or not row.get("market_value") or row["market_value"] < 50_000:
        return {}
    hints = {cma._slugish(h) for h in (subj.get("official_suburb"),
                                       subj.get("suburb"),
                                       subj.get("suburb_slug")) if h}
    got = cma._slugish(row.get("suburb"))
    if got and hints and not any(got in h or h in got for h in hints):
        return {}                       # same erf number, wrong town
    return {"gv_value": int(row["market_value"]), "gv_roll": row.get("roll")}


# ------------------------------------------------------------ suburb stats
#
# suburb_stats walks every group in the suburb and reads each one's price
# history; that is fine once, and wasteful when three agents open three
# briefs for the same road. It only moves when a crawl writes, so a short
# process-local cache costs nothing in freshness.

_stats_cache: dict[str, tuple[float, dict]] = {}
_stats_lock = threading.Lock()


def _suburb_stats(conn: sqlite3.Connection, slug: str | None) -> dict:
    if not slug:
        return {}
    now = time.monotonic()
    with _stats_lock:
        hit = _stats_cache.get(slug)
        if hit and now - hit[0] < SUBURB_STATS_TTL:
            return hit[1]
    stats = cma.suburb_stats(conn, slug)
    with _stats_lock:
        _stats_cache[slug] = (time.monotonic(), stats)
    return stats


# ----------------------------------------------------------------- numbers

def _price_moves(conn: sqlite3.Connection, keys: list[str]) -> dict:
    """Cuts across the group's own histories: how many downward moves, the
    deepest first-to-latest move, and when the last cut landed. Two portals
    quoting different prices is not a cut — only a listing's own chronology
    counts, the same rule cma.py applies."""
    cuts, last_cut_at = 0, None
    for k in keys:
        prices = [(r["price_zar"], r["observed_at"]) for r in conn.execute(
            """SELECT price_zar, observed_at FROM price_history
               WHERE listing_key = ? AND price_zar IS NOT NULL
               ORDER BY observed_at""", (k,))]
        for (prev, _), (cur, at) in zip(prices, prices[1:]):
            if cur < prev:
                cuts += 1
                if last_cut_at is None or (at or "") > last_cut_at:
                    last_cut_at = at
    return {"count": cuts, "last_cut_at": last_cut_at}


def _numbers(conn: sqlite3.Connection, subj: dict, score: dict,
             members: list[sqlite3.Row], stats: dict) -> dict:
    keys = [m["listing_key"] for m in members]
    price = subj.get("price_zar")
    floor, erf_m2 = subj.get("floor_size_m2"), subj.get("erf_size_m2")
    gv = _gv(conn, subj)
    cut = subj.get("price_cut") or {}
    moves = _price_moves(conn, keys)
    life = _lifecycle(conn, keys)
    proof = (scorer._proof_age_hours(members, subj["brands"])
             if len(subj["brands"]) > 1 else None)

    n: dict[str, Any] = {
        "asking_zar": price,
        "beds": subj.get("beds"),
        "baths": subj.get("baths"),
        "property_type": subj.get("property_type"),
        "floor_size_m2": floor,
        "erf_size_m2": erf_m2,
        "r_per_m2_floor": round(price / floor) if price and floor else None,
        "r_per_m2_erf": (round(price / erf_m2)
                         if price and erf_m2 and subj.get("bucket") == "house"
                         else None),
        "coverage_pct": (int(round(floor / erf_m2 * 100))
                         if floor and erf_m2 and erf_m2 >= floor else None),
        "gv_value": gv.get("gv_value") or subj.get("gv_value"),
        "gv_roll": gv.get("gv_roll"),
        "days_on_market": subj.get("days_on_market"),
        "days_on_market_basis": subj.get("days_on_market_basis"),
        "listed_on": subj.get("listing_date"),
        "price_first_zar": cut.get("first_price"),
        "price_latest_zar": cut.get("latest_price"),
        "cut_pct": cut.get("cut_pct"),
        "cut_count": moves["count"],
        "last_cut_at": (moves["last_cut_at"] or "")[:10] or None,
        "under_offer": bool(subj.get("under_offer")),
        "price_reduced_badge": bool(subj.get("price_reduced")),
        "relisted": bool(life.get("relisted")),
        "days_off_market": life.get("days_off_market"),
        "brand_count": len(subj["brands"]),
        "agency_count": len(subj.get("agencies") or []),
        "source_count": subj.get("source_count"),
        "listing_count": subj.get("listing_count"),
        "photo_count": subj.get("photo_count"),
        "proof_age_hours": round(proof, 1) if proof is not None else None,
        "proof_fresh": (None if proof is None
                        else proof <= getattr(config, "PROOF_FRESH_HOURS", 72)),
        "mandate_verdict": score.get("mandate_verdict"),
        "mandate_expiry_note": score.get("mandate_expiry_note"),
        "sellable": score.get("sellable"),
        "prospect_score": score.get("prospect_score"),
        "tier": score.get("tier"),
        "luxury_fit": score.get("luxury_fit"),
        "open_mandate_confidence": score.get("open_mandate_confidence"),
        "marketing_weakness": score.get("marketing_weakness"),
        "erf_number": subj.get("erf_number"),
        "erf_status": subj.get("erf_status"),
        "parcel_area_m2": subj.get("parcel_area_m2"),
        "official_address": subj.get("official_address"),
        "is_development": bool(subj.get("is_development")),
    }
    n["price_vs_gv"] = (round(price / n["gv_value"], 2)
                        if price and n["gv_value"] else None)
    # Suburb yardsticks: the same comparison the report makes, said in the
    # direction an agent would say it ("24% above the suburb median").
    n["suburb_median_zar"] = stats.get("median_asking_zar")
    n["suburb_r_per_m2"] = stats.get("median_r_per_m2_floor")
    n["suburb_median_dom"] = stats.get("median_days_on_market")
    n["suburb_active_count"] = stats.get("active_count")
    n["suburb_cut_share"] = stats.get("price_cut_share")
    n["vs_median_pct"] = _pct(price, n["suburb_median_zar"])
    n["vs_median_ppm2_pct"] = _pct(n["r_per_m2_floor"], n["suburb_r_per_m2"])
    n["dom_vs_median_x"] = (round(n["days_on_market"] / n["suburb_median_dom"], 1)
                            if n["days_on_market"] and n["suburb_median_dom"] else None)
    return n


# ---------------------------------------------------------- talking points

def _talking_points(subj: dict, n: dict, score: dict) -> list[str]:
    """Plain sentences an agent can say, most compelling first. Every one is
    emitted only when the fact behind it exists — a brief that invents a
    talking point is worse than a short one."""
    suburb = subj.get("suburb") or "the suburb"
    out: list[tuple[int, str]] = []

    if n["brand_count"] > 1:
        where = (f" on {_plural(n['source_count'], 'portal')}"
                 if n["source_count"] and n["source_count"] > 1 else "")
        out.append((0, f"Listed with {_plural(n['brand_count'], 'agency')}"
                       f"{where} — the mandate is open, so adding Oblivion "
                       f"costs them nothing."))
        if n["proof_fresh"] is False:
            out.append((9, f"That multi-agency proof is "
                           f"{int(n['proof_age_hours'] // 24)} days old — worth "
                           f"checking both listings are still live before you dial."))
    elif n["mandate_verdict"] in ("open", "probably_open"):
        out.append((0, "The engine reads this mandate as "
                       f"{n['mandate_verdict'].replace('_', ' ')} — marketing "
                       "alongside the current agent should cost them nothing."))

    if n["cut_count"] and n["price_first_zar"] and n["price_latest_zar"]:
        times = "once" if n["cut_count"] == 1 else f"{n['cut_count']} times"
        pct = f" ({n['cut_pct']:+.0f}%)".replace("+", "−") if n.get("cut_pct") else ""
        out.append((1, f"Price already cut {times}, {_fmt_m(n['price_first_zar'])} → "
                       f"{_fmt_m(n['price_latest_zar'])}{pct}."))
    elif n["price_reduced_badge"]:
        out.append((1, "The portal is carrying a price-reduced badge — the "
                       "asking price has already moved once."))

    if n["days_on_market"]:
        if n["dom_vs_median_x"] and n["dom_vs_median_x"] >= 1.3:
            out.append((2, f"On the market {n['days_on_market']} days; the typical "
                           f"live {suburb} listing has been up "
                           f"{int(n['suburb_median_dom'])} — the current marketing "
                           f"isn't converting."))
        elif n["days_on_market"] >= 120:
            out.append((2, f"On the market {n['days_on_market']} days — long enough "
                           f"that the owner is open to a second opinion."))

    if n["relisted"]:
        gap = (f", off the market for {n['days_off_market']} days"
               if n["days_off_market"] else "")
        out.append((3, f"This listing was pulled and relisted{gap} — usually a "
                       f"mandate that ran out without a sale."))

    # The scorer writes its mandate note into this column whatever the verdict,
    # so on a multi-agency property it simply re-tells the first point above —
    # and its "confirmed live 3h ago" is frozen at scoring time, which can
    # contradict the proof age computed a fortnight later.
    note = str(n["mandate_expiry_note"] or "").strip()
    if note and not (n["brand_count"] > 1 and "agenc" in note.lower()):
        out.append((4, note.rstrip(".") + "."))

    if n["photo_count"] is not None and n["photo_count"] <= 12:
        portal = (subj["listings"][0]["source"].replace("privateproperty",
                                                        "Private Property")
                  if subj.get("listings") else "the portal")
        out.append((5, f"Only {_plural(n['photo_count'], 'photo')} on "
                       f"{portal.title() if portal.islower() else portal} and no "
                       f"video — exactly the gap a film fills."))

    if n["price_vs_gv"] and n["price_vs_gv"] >= 1.6:
        roll = n["gv_roll"] or "municipal"
        out.append((6, f"Asking is {n['price_vs_gv']}× the {roll} valuation of "
                       f"{_fmt_m(n['gv_value'])} — worth a conversation about "
                       f"where that number came from."))

    if n["vs_median_pct"] is not None and abs(n["vs_median_pct"]) >= 15:
        way = "above" if n["vs_median_pct"] > 0 else "below"
        out.append((7, f"Asking {_fmt_m(n['asking_zar'])} is "
                       f"{abs(n['vs_median_pct'])}% {way} the {suburb} median of "
                       f"{_fmt_m(n['suburb_median_zar'])}."))

    if n["erf_number"] and n["parcel_area_m2"]:
        cover = (f", house covers {n['coverage_pct']}% of it"
                 if n["coverage_pct"] else "")
        out.append((8, f"Erf {n['erf_number']} "
                       f"{subj.get('official_suburb') or suburb}, "
                       f"{_fmt_area(n['parcel_area_m2'])} parcel{cover}."))

    pitch = str(score.get("pitch_angle") or "").strip()
    # The scorer's own angle, unless it re-tells the multi-agency story: that
    # is already the first point above, and its copy is a snapshot that can
    # contradict today's proof age ("confirmed within 3h" written a fortnight
    # ago).
    if pitch and not (n["brand_count"] > 1 and "agenc" in pitch.lower()):
        out.append((10, pitch))

    out.sort(key=lambda t: t[0])
    return [t for _, t in out][:MAX_TALKING_POINTS]


# -------------------------------------------------------------- cool facts

_FACT_WORDS = (
    "view", "views", "sea", "ocean", "mountain", "sunset", "architect",
    "designed", "heritage", "built in", "year", "award", "wine cellar",
    "cinema", "pool", "lift", "solar", "borehole", "off-grid", "security",
    "estate", "beach", "walk", "golf", "vineyard", "private", "gate",
    "north-facing", "penthouse", "rooftop", "jacuzzi", "gym", "staff",
    "self-contained", "flatlet", "subdivid", "zoning", "development potential",
)

# Agent boilerplate: true of the advert, not of the house.
_BOILERPLATE = re.compile(
    r"call now|call me|contact (me|us|the agent)|don't miss|dont miss|do not miss"
    r"|viewing by appointment|by appointment only|whatsapp|e-?mail|@|www\.|http"
    r"|sole mandate|exclusive mandate|joint mandate|register|pre-?approv"
    r"|\+?27\s?\d|\b0\d{2}[\s-]?\d{3}[\s-]?\d{4}\b|\bref(erence)?\s*[:#]"
    r"|price on application|bond originat|transfer (cost|duty)",
    re.I)


def _sentences(text: str) -> list[str]:
    # Portals publish prose, bullet lists and hard line breaks in one field;
    # a line break is a sentence boundary as often as a full stop is.
    text = re.sub(r"[ \t]+", " ", (text or "").replace("|", "\n"))
    parts = re.split(r"(?<=[.!?])\s+|[\r\n]+|\s*[•·]\s*|\s+-\s+", text)
    return [p.strip(" -–—*•\t") for p in parts if p and p.strip(" -–—*•\t")]


def _desentence(s: str) -> str:
    """SHOUTED PROSE back to sentence case; agents type in caps lock and a
    brief read at arm's length shouldn't."""
    letters = [c for c in s if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        s = s.lower()
        s = re.sub(r"(^|(?<=[.!?]\s))([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)
    return s[:1].upper() + s[1:] if s else s


def _cool_facts(subj: dict) -> list[dict]:
    """Sentences from the advert worth repeating, plus what is true of the
    area itself. Nothing is invented: the listing text is the owner's own
    marketing and the area lore is hand-written per suburb below."""
    out, seen = [], set()
    for raw in _sentences(subj.get("description") or ""):
        if len(raw) < 25 or _BOILERPLATE.search(raw):
            continue
        low = raw.lower()
        if not any(w in low for w in _FACT_WORDS):
            continue
        s = _desentence(raw).rstrip(" .,;") + "."
        if len(s) > COOL_FACT_CHARS:
            s = s[:COOL_FACT_CHARS].rsplit(" ", 1)[0].rstrip(" .,;") + "…"
        key = re.sub(r"[^a-z0-9]", "", s.lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append({"text": s, "source": "listing"})
        if len(out) >= MAX_COOL_FACTS:
            break
    out.extend({"text": t, "source": "area"}
               for t in _area_facts(subj.get("suburb_slug"))[:MAX_AREA_FACTS])
    return out


# Hand-written, and only where it is safely true — an agent repeating this on
# a call is staking the agency's credibility on it. Phrased as the aside it is
# meant to be, not as a fact sheet.
AREA_LORE: dict[str, list[str]] = {
    "clifton": ["Clifton's four beaches are numbered rather than named, and the "
                "granite boulders between them are what keep the south-easter off.",
                "Fourth Beach carries Blue Flag status — one of very few in the city."],
    "camps-bay": ["The Twelve Apostles ridge behind Camps Bay takes the last light "
                  "of the day, which is half of what buyers are paying for."],
    "bantry-bay": ["Bantry Bay sits in the lee of Lion's Head, which is why it has "
                   "the reputation as the least windy address on the Seaboard."],
    "fresnaye": ["Fresnaye faces north-west off the slope of Lion's Head — afternoon "
                 "sun and the sunset straight ahead."],
    "bakoven": ["Bakoven is the quiet end of Camps Bay: a handful of houses around "
                "a little boulder cove."],
    "llandudno": ["Llandudno has no shops and no streetlights, and the residents "
                  "have gone to some trouble to keep it that way."],
    "sea-point": ["The Sea Point promenade runs about three kilometres and works as "
                  "the city's outdoor living room."],
    "green-point": ["Green Point has the Urban Park and the stadium on its doorstep, "
                    "and the promenade from there into Sea Point."],
    "mouille-point": ["The candy-striped lighthouse at Mouille Point has been working "
                      "since 1824 — the oldest one still operating in the country."],
    "waterfront": ["The V&A is still a working harbour as well as an address, with "
                   "Table Mountain across the basin."],
    "de-waterkant": ["De Waterkant is the cobbled quarter of painted cottages just "
                     "above the city centre."],
    "cape-town-city-centre": ["The City Bowl grid runs from the Company's Garden, the "
                              "oldest cultivated ground in the country, down to the harbour."],
    "gardens": ["Gardens runs up to the Company's Garden — the oldest cultivated "
                "ground in South Africa."],
    "higgovale": ["Higgovale sits right up against the Table Mountain contour path: "
                  "city below, forest above."],
    "oranjezicht": ["The Oranjezicht City Farm market is a Saturday fixture, and the "
                    "suburb sits under the Table Mountain slopes."],
    "tamboerskloof": ["Tamboerskloof sits under Lion's Head with Kloof Nek over the "
                      "top to the Atlantic in a few minutes."],
    "vredehoek": ["Vredehoek is high under Devil's Peak, so the whole city bowl lies "
                  "below it at night."],
    "constantia": ["Constantia is the oldest wine-growing area in the country — Groot "
                   "Constantia dates to 1685.",
                   "Big treed erven and the greenbelt walks are what people move here for."],
    "nova-constantia": ["Nova Constantia sits in the old Constantia wine valley, the "
                        "country's oldest."],
    "high-constantia": ["High Constantia looks over the oldest wine valley in the "
                        "country, settled in 1685."],
    "bishopscourt": ["Bishopscourt has some of the largest erven in Cape Town, right "
                     "on Kirstenbosch's doorstep."],
    "newlands": ["Newlands is the wettest suburb in the city, which is exactly why "
                 "it is the greenest."],
    "rondebosch": ["Rondebosch lives around UCT's upper campus and the Rondebosch "
                   "Common."],
    "tokai": ["Tokai has the forest and the fynbos walks on its doorstep."],
    "steenberg": ["Steenberg is a wine estate and golf course at the top of the "
                  "Constantia valley."],
    "hout-bay": ["Hout Bay is a working fishing harbour with mountain on three sides "
                 "and Chapman's Peak out the back."],
    "noordhoek": ["Noordhoek's Long Beach runs for about eight uninterrupted "
                  "kilometres — horses and all."],
    "kommetjie": ["Kommetjie is built around the Slangkop lighthouse, the tallest "
                  "cast-iron tower on the South African coast."],
    "simons-town": ["Simon's Town is the navy's home port, with the Boulders penguins "
                    "around the corner."],
    "kalk-bay": ["Kalk Bay still lands fish off the harbour wall, and the main road "
                 "is antiques and coffee."],
    "st-james": ["St James is the one with the row of painted Victorian bathing boxes "
                 "and the tidal pool."],
    "scarborough": ["Scarborough sits inside a conservation village line, so very "
                    "little new gets built there."],
    "chapmans-peak": ["Chapman's Peak Drive is cut into the cliff below — one of the "
                      "great coastal roads anywhere."],
    "bloubergstrand": ["Blouberg is where the postcard view of Table Mountain across "
                       "the bay is taken from."],
    "big-bay": ["Big Bay is the kitesurfing end of Blouberg, and the wind is the point."],
    "sunset-beach": ["Sunset Beach looks straight back at Table Mountain across "
                     "Table Bay."],
    "melkbosstrand": ["Melkbos keeps the long west-facing beach and the sunsets "
                      "without the city."],
    "stellenbosch": ["Stellenbosch is the country's second-oldest town — oaks, Cape "
                     "Dutch gables and the university in the middle of it."],
    "mostertsdrift": ["Mostertsdrift is walking distance from Stellenbosch's oak-lined "
                      "centre."],
    "dalsig": ["Dalsig looks over Stellenbosch to the Simonsberg."],
    "paradyskloof": ["Paradyskloof sits under the Stellenbosch mountain on the "
                     "Helshoogte side of town."],
    "die-boord": ["Die Boord is the quiet family side of Stellenbosch, minutes from "
                  "the centre."],
    "stellenbosch-farms": ["The Stellenbosch farm belt is the heart of South African "
                           "wine country."],
    "franschhoek": ["Franschhoek was settled by French Huguenots in 1688, and the "
                    "valley still carries their farm names."],
    "paarl": ["The granite domes above Paarl are among the largest granite outcrops "
              "in the world."],
    "val-de-vie-estate": ["Val de Vie is the polo estate in the Paarl–Franschhoek "
                          "valley, with the Berg River through it."],
    "pearl-valley-golf-and-country-estate": ["Pearl Valley is the Jack Nicklaus "
                                             "signature course inside Val de Vie."],
    "de-zalze-winelands-golf-estate": ["De Zalze wraps its golf course around the old "
                                       "Kleine Zalze vineyards outside Stellenbosch."],
    "somerset-west": ["Somerset West sits under the Helderberg with False Bay below it."],
    "erinvale-golf-estate": ["Erinvale's course was designed by Gary Player, under "
                             "the Helderberg."],
    "hermanus": ["Hermanus has a cliff path running the length of the town, and the "
                 "southern rights come into Walker Bay in season."],
    "voelklip": ["Voëlklip is the beach end of Hermanus, with Grotto Beach along it."],
    "hemel-en-aarde-valley": ["The Hemel-en-Aarde valley behind Hermanus is the "
                              "country's pinot noir country."],
    "onrus": ["Onrus is the quieter lagoon-and-beach side of Hermanus."],
    "pringle-bay": ["Pringle Bay is a small village under the Kogelberg, which is a "
                    "UNESCO biosphere reserve."],
    "bettys-bay": ["Betty's Bay has the Harold Porter botanical garden and the penguin "
                   "colony at Stony Point."],
    "langebaan": ["The Langebaan lagoon is the turquoise one, with the West Coast "
                  "National Park running down its far side.",
                  "It is one of the best kitesurfing spots in the country."],
    "paternoster": ["Paternoster is whitewashed fishermen's cottages, crayfish and "
                    "very little else — which is the appeal."],
    "yzerfontein": ["Sixteen Mile Beach runs north out of Yzerfontein into the West "
                    "Coast National Park."],
    "jacobsbaai": ["Jacobsbaai is a small cove village on the west coast between "
                   "Saldanha and Paternoster."],
    "saldanha": ["Saldanha Bay is the deepest natural harbour on the South African "
                 "coast."],
    "st-helena-bay": ["St Helena Bay is one of the few bays on this coast that faces "
                      "north, so the water is unusually calm."],
    "velddrif": ["Velddrif sits on the Berg River mouth — flamingos, salt pans and "
                 "bokkoms drying on the racks."],
    "knysna": ["Knysna's lagoon opens to the sea between the two sandstone Heads."],
    "plettenberg-bay": ["The Robberg peninsula at Plett is a nature reserve with a "
                        "circuit walk and seals below it."],
}

# Sub-suburbs that share their parent's lore rather than repeating it.
_LORE_ALIAS = {
    "hout-bay-central": "hout-bay", "hout-bay-beachfront": "hout-bay",
    "hout-bay-heights": "hout-bay", "scott-estate": "hout-bay",
    "eastcliff": "hermanus", "kwaaiwater": "hermanus",
    "hermanus-heights": "hermanus",
    "somerset-west-central": "somerset-west", "parel-vallei": "somerset-west",
    "heldervue": "somerset-west",
    "brandwacht": "stellenbosch", "devonvallei": "stellenbosch",
    "three-anchor-bay": "sea-point",
}


def _area_facts(slug: str | None) -> list[str]:
    if not slug:
        return []
    return AREA_LORE.get(slug) or AREA_LORE.get(_LORE_ALIAS.get(slug, ""), [])


# --------------------------------------------------------------- questions

def _questions(n: dict) -> list[str]:
    """Open questions that make the owner do the talking. Tailored to what
    this property's own facts already say, so the agent never asks something
    the listing answered."""
    qs: list[str] = []
    if n["brand_count"] > 1:
        qs.append("Which of the agents is bringing you the most viewings?")
    if n["cut_count"]:
        qs.append("What made you decide to move the price?")
    if n["days_on_market"] and n["days_on_market"] >= 90:
        qs.append("What's the feedback been from viewings so far?")
    if n["mandate_verdict"] in ("sole", "probably_sole") or n["mandate_expiry_note"]:
        qs.append("When does the current mandate run to?")
    qs += ["What's the timeline you're working to?", "Where are you moving to?"]
    # A quiet listing triggers none of the conditions above, and an agent
    # holding two questions runs out of call before the owner opens up.
    for filler in ("What made you decide to sell?",
                   "Has anyone come close to an offer?",
                   "How many viewings have you had?"):
        if len(qs) >= MAX_QUESTIONS:
            break
        qs.append(filler)
    return qs[:MAX_QUESTIONS]


# -------------------------------------------------------------- objections
#
# The human half of caller.system_prompt's objection list — same answers, said
# the way a person says them, plus the two that only ever come up on a call a
# person is making.

BASE_OBJECTIONS = [
    {"objection": "I already have an agent.",
     "response": "Keep them — that's the point. With an open mandate we market "
                 "alongside, same asking price, and you only pay whoever "
                 "actually brings the buyer."},
    {"objection": "I'm on a sole mandate.",
     "response": "Then I won't touch it. When does it run to? I'd rather call "
                 "you a couple of weeks before it ends than talk you out of "
                 "something you signed."},
    {"objection": "I don't want another agent.",
     "response": "It isn't another agent in the house — it's one film and the "
                 "audience it reaches. Your agent keeps running the sale."},
    {"objection": "The market's dead / the price is the problem.",
     "response": "That's the frustration we hear most. The consultation "
                 "includes a current valuation, no strings — at worst you get "
                 "an honest number."},
    {"objection": "Is this a scam? How did you get my number?",
     "response": "Fair question — your home is publicly advertised, that's all "
                 "I've got. Look Oblivion up, and Duane will confirm "
                 "everything in person."},
    {"objection": "What do you charge?",
     "response": "That's for the meeting — the film consultation and the "
                 "valuation are free either way."},
]


def _objections(n: dict) -> list[dict]:
    out = [dict(o) for o in BASE_OBJECTIONS]
    if n["brand_count"] > 1:
        out[0]["response"] += (f" You're already running "
                               f"{_plural(n['brand_count'], 'agency')} — this is "
                               f"the same arrangement.")
    return out


# ------------------------------------------------------------------- avoid

def _avoid(subj: dict, n: dict, score: dict) -> list[str]:
    out: list[str] = []
    for flag in re.split(r"[;\n•]+", str(score.get("red_flags") or "")):
        flag = flag.strip(" -–—.")
        if flag:
            out.append(flag[:1].upper() + flag[1:] + ".")
    # The scorer's own red flags often say these two already; repeating them
    # two lines apart just makes the list longer to read under pressure.
    said = " ".join(out).lower()
    if n["is_development"] and "development" not in said:
        out.append("This reads as a new development or off-plan launch — there "
                   "is no owner mandate to win here.")
    if n["under_offer"] and "under offer" not in said:
        out.append("A portal has it under offer — confirm it is still on the "
                   "market before you pitch anything.")
    if n["mandate_verdict"] in ("sole", "probably_sole"):
        out.append("Ground truth says sole mandate — never ask them to break "
                   "it; ask when it ends and book the follow-up.")
    out += [
        "Don't quote a valuation on the phone — the number comes out of the "
        "meeting, not the call.",
        "Don't use the owner's name until they've confirmed who they are, and "
        "say nothing about the property to anyone else.",
        "Never name or knock the current agency — the pitch adds to what they "
        "are doing, it doesn't replace it.",
        "Stick to what their own advert publishes; that is the only "
        "information you're entitled to have.",
    ]
    return out


# --------------------------------------------------------- tracked context

def _tracked(conn: sqlite3.Connection, gid: str) -> dict | None:
    """The lead-management side, when this property is being worked: who to
    ask for, what was said last, and whether a mandate is already recorded."""
    try:
        row = conn.execute(
            "SELECT stage, priority, assigned_to FROM tracked_property"
            " WHERE group_id = ?", (gid,)).fetchone()
    except sqlite3.OperationalError:
        return None                       # panel.ensure_schema never ran here
    if not row:
        return None
    out = dict(row)
    contact = conn.execute(
        "SELECT name, phone, email, role FROM contacts WHERE group_id = ?"
        " ORDER BY id LIMIT 1", (gid,)).fetchone()
    out["contact"] = dict(contact) if contact else None
    out["interactions"] = [dict(r) for r in conn.execute(
        """SELECT occurred_at, channel, outcome, summary FROM interactions
           WHERE group_id = ? ORDER BY id DESC LIMIT 3""", (gid,))]
    mandate = conn.execute(
        """SELECT type, signed_at, expires_at, listing_price, lost_to
           FROM mandates WHERE group_id = ? ORDER BY id DESC LIMIT 1""",
        (gid,)).fetchone()
    out["mandate"] = dict(mandate) if mandate else None
    out["open_tasks"] = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE group_id = ? AND done_at IS NULL",
        (gid,)).fetchone()[0]
    return out


# ------------------------------------------------------------------- cache

def _fingerprint(conn: sqlite3.Connection, members: list[sqlite3.Row]) -> str:
    """What the brief is built from, hashed. Changes when the price moves, an
    agency joins or leaves, the scorer re-judges it, or a crawl sees it
    again with new content."""
    keys = [m["listing_key"] for m in members]
    q = ",".join("?" * len(keys))
    scored_at = conn.execute(
        f"SELECT MAX(scored_at) FROM scores WHERE listing_key IN ({q})",
        keys).fetchone()[0]
    cuts = conn.execute(
        f"SELECT COUNT(*) FROM price_history WHERE listing_key IN ({q})",
        keys).fetchone()[0]
    payload = json.dumps([
        sorted(str(m["price_zar"]) for m in members),
        sorted((m["agency"] or "").strip() for m in members),
        len(members), scored_at, cuts,
        # The DATE of the last sighting, not the timestamp: the brief talks in
        # days ("proof is 3 days stale"), and hashing the full timestamp would
        # throw away a paid AI rewrite every time a crawl merely saw the
        # listing again.
        max((m["last_seen"] or "") for m in members)[:10],
        max((m["content_changed"] or "") for m in members),
    ], sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def _cached(conn: sqlite3.Connection, gid: str) -> tuple[str, dict] | None:
    row = conn.execute(
        "SELECT fingerprint, body FROM call_briefs WHERE gid = ?", (gid,)).fetchone()
    if not row:
        return None
    try:
        return row["fingerprint"], json.loads(row["body"] or "{}")
    except ValueError:
        return None


def _store(conn: sqlite3.Connection, gid: str, fingerprint: str, body: dict) -> None:
    conn.execute(
        """INSERT INTO call_briefs (gid, fingerprint, built_at, backend, body)
           VALUES (?, ?, datetime('now'), ?, ?)
           ON CONFLICT(gid) DO UPDATE SET
               fingerprint = excluded.fingerprint,
               built_at    = excluded.built_at,
               backend     = excluded.backend,
               body        = excluded.body""",
        (gid, fingerprint, (body.get("ai") or {}).get("backend"),
         json.dumps(body)))


# ------------------------------------------------------------------- build

def build(conn: sqlite3.Connection, gid: str, *, want_ai: bool = False,
          refresh: bool = False) -> dict | None:
    """The whole brief for one property id, or None if the id resolves to
    nothing. Deterministic throughout unless want_ai and a provider answers."""
    ensure_schema(conn)
    gid = str(gid)
    members = _members(conn, gid)
    if not members:
        return None

    fingerprint = _fingerprint(conn, members)
    cached = None if refresh else _cached(conn, gid)
    fresh_cache = bool(cached and cached[0] == fingerprint)
    if fresh_cache and (not want_ai or cached[1].get("ai")):
        return cached[1]                  # nothing changed and nothing to add

    subj = _subject(conn, gid, members)
    _augment(conn, subj, members)
    score = _score(conn, members)
    stats = _suburb_stats(conn, subj.get("suburb_slug"))
    n = _numbers(conn, subj, score, members, stats)

    body = {
        "gid": gid,
        "listing_key": subj.get("listing_key"),
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "fingerprint": fingerprint,
        "property": {
            "title": subj.get("title"),
            "address": (subj.get("official_address")
                        or subj.get("street_address_raw")),
            "suburb": subj.get("suburb"),
            "suburb_slug": subj.get("suburb_slug"),
            "region": config.SUBURBS.get(subj.get("suburb_slug") or "", {}).get("region"),
            "property_type": subj.get("property_type"),
            "agencies": subj.get("agencies") or [],
            "brands": subj.get("brands") or [],
            "brand_names": subj.get("brand_names") or [],
            "agent_names": subj.get("agent_names") or [],
            "listings": subj.get("listings") or [],
            "url": (subj.get("urls") or [None])[0],
            "photo_url": subj.get("photo_url"),
            "latitude": subj.get("latitude"),
            "longitude": subj.get("longitude"),
            "description": subj.get("description") or "",
            "cma_url": f"/cma/{gid}" if _is_group_id(gid) else None,
        },
        "numbers": n,
        "suburb_stats": stats,
        "talking_points": _talking_points(subj, n, score),
        "cool_facts": _cool_facts(subj),
        "questions": _questions(n),
        "objections": _objections(n),
        "avoid": _avoid(subj, n, score),
        "tracked": _tracked(conn, gid),
        "score_notes": {"reasoning": score.get("reasoning"),
                        "pitch_angle": score.get("pitch_angle"),
                        "scored_by": score.get("scored_by")},
        # An AI paragraph is only carried over when the facts behind it are
        # unchanged; otherwise it is dropped rather than shown next to
        # numbers it now contradicts.
        "ai": cached[1].get("ai") if fresh_cache else None,
    }

    if want_ai and not body.get("ai"):
        ok, _reason = scorer.ai_status()
        if ok:
            body["ai"] = enrich(body)

    _store(conn, gid, fingerprint, body)
    return body


# ---------------------------------------------------------------- AI layer

class Models:
    """pydantic only when a model call actually happens (same as finder)."""
    _brief = None

    @classmethod
    def call_brief(cls):
        if cls._brief is None:
            from pydantic import BaseModel

            class Objection(BaseModel):
                objection: str
                response: str

            class CallBrief(BaseModel):
                opener: str                 # two spoken sentences
                talking_points: list[str]
                cool_facts: list[str]       # area ones marked '(area)'
                questions: list[str]
                objections: list[Objection]
                avoid: list[str]
                one_liner: str              # the whole property in one line

            cls._brief = CallBrief
        return cls._brief


AI_SYSTEM = """You write the one-page brief a South African estate agent reads
in the minute before phoning a homeowner whose house is already on the market
with another agency.

The caller is {caller} of {agency} Estates (Cape Town / West Coast), an
agency that markets luxury homes with cinematic property films and the reach
that comes with them.
The call has one goal: a free, no-obligation film consultation and market
valuation at the house. Nothing is sold on the phone.

SA mandate glossary — get this right:
- sole (exclusive) mandate: one agency only, for a fixed term. Do not pitch
  against a live one; ask when it ends.
- open mandate: any number of agencies, the one who sells is the one who is
  paid. Adding {agency} costs the owner nothing.
- joint mandate: two agencies sharing one mandate and the commission.
- dual mandate: two agencies each mandated separately.

RULES:
- Use ONLY the facts in the brief you are given. Never invent buyers, offers,
  viewings, statistics, commissions or timelines.
- For cool facts you may add well-known public facts about the suburb. Mark
  ONLY those with '(area)' at the end and leave the rest unmarked. Everything
  else must trace to the brief.
- POPIA: the only information the agent is entitled to is what the owner's own
  advert publishes. Never suggest referencing anything else.
- Never disparage the current agent or agency, and never suggest breaking a
  mandate.
- South African English, spoken register, no exclamation marks, no
  salesy-breathless copy. Each item 200 characters or less.
- Prices in South African style: R100 000 000, or R100m in a sentence. Never
  American comma grouping.
- The opener is exactly two sentences the agent says out loud immediately
  after the owner confirms who they are: who is calling, and the one reason
  this house is worth a film. Warm, unhurried, no pitch yet. The agent says
  their own name, so write it as "{caller}" and never leave a placeholder
  like [your name].
- one_liner: this property and the reason to call, in one line under 120
  characters."""


def enrich(body: dict) -> dict | None:
    """Rewrite the deterministic brief in spoken language. Returns None when
    no provider answers — the caller keeps the deterministic sections."""
    import caller                         # same identity the voice agent uses
    import finder                         # deferred: pulls pydantic/openai

    system = AI_SYSTEM.format(caller=caller.HUMAN_NAME, agency=caller.AGENCY_NAME)

    facts = {k: body[k] for k in ("property", "numbers", "suburb_stats",
                                  "talking_points", "cool_facts", "questions",
                                  "objections", "avoid", "score_notes")}
    facts["property"] = {k: v for k, v in facts["property"].items()
                         if k != "description"}
    user = (f"BRIEF FACTS (JSON):\n{json.dumps(facts, default=str)[:14000]}\n\n"
            f"THE AGENT'S OWN ADVERT COPY:\n"
            f"{(body['property'].get('description') or '')[:4000]}")
    parsed, backend = finder._ask(system, user, Models.call_brief(),
                                  max_tokens=2600)
    if parsed is None:
        return None
    out = parsed.model_dump()
    # Models like to label every fact, not just the area ones. The '(area)'
    # tag earns its place; '(listing)' just repeats where everything came from.
    out["cool_facts"] = [re.sub(r"\s*\((listing|advert|brief)\)\s*$", "", c)
                         for c in out.get("cool_facts") or []]
    out["backend"] = backend
    out["generated_at"] = datetime.now().isoformat(timespec="seconds")
    return out


# -------------------------------------------------------------------- text

def _head_lines(body: dict) -> list[str]:
    p, n = body["property"], body["numbers"]
    where = " · ".join(x for x in (p.get("address"), p.get("suburb")) if x)
    bits = []
    if n.get("asking_zar"):
        bits.append(_fmt_r(n["asking_zar"]))
    if n.get("beds"):
        bits.append(f"{int(n['beds'])} bed / {int(n['baths'] or 0)} bath")
    if p.get("property_type"):
        bits.append(str(p["property_type"]))
    if n.get("erf_number"):
        bits.append(f"Erf {n['erf_number']}")
    # One name per brand, three at most: a franchise writes itself three ways
    # across three portals, and a header listing all of them reads as three
    # agencies on a screen nobody has time to parse.
    names = p.get("brand_names") or p.get("agencies") or []
    marketed = ", ".join(names[:3]) or "agency unknown"
    if len(names) > 3:
        marketed += f" and {len(names) - 3} more"
    seen = f" · {_plural(n['source_count'] or 1, 'portal')}" if n.get("source_count") else ""
    dom = f" · {n['days_on_market']} days on market" if n.get("days_on_market") else ""
    return [f"CALL BRIEF — {where or p.get('title') or body['gid']}",
            " · ".join(bits),
            f"Listed by {marketed}{seen}{dom}"]


def _fact_rows(n: dict, long: bool = False) -> list[tuple[str, str]]:
    """The key-numbers grid, shared by the text and HTML renderings. `long`
    folds the comparisons into the same cell for a text-only reader; the page
    has room for them side by side."""
    gv = cut = median = erf = None
    if n.get("gv_value"):
        gv = _fmt_m(n["gv_value"]) + " · " + str(n.get("gv_roll") or "roll")
        if long and n.get("price_vs_gv"):
            gv += f" · asking is {n['price_vs_gv']}×"
    if n.get("cut_count"):
        # A price that fell and climbed back is a move without a net cut, so
        # cma's first->latest figure is absent while the count is not.
        cut = str(n["cut_count"])
        if n.get("price_first_zar") and n.get("price_latest_zar"):
            cut += (f" · {_fmt_m(n['price_first_zar'])} → "
                    f"{_fmt_m(n['price_latest_zar'])}")
        else:
            cut += " moves, no net cut"
    if n.get("suburb_median_zar"):
        median = _fmt_m(n["suburb_median_zar"])
        if long and n.get("vs_median_pct") is not None:
            median += f" ({n['vs_median_pct']:+}%)"
    if n.get("erf_number"):
        erf = f"{n['erf_number']} · {_fmt_area(n.get('parcel_area_m2'))}"
        if n.get("coverage_pct"):
            erf += f" · {n['coverage_pct']}% covered"
    rows = [
        ("Asking", _fmt_r(n.get("asking_zar")) if n.get("asking_zar") else None),
        ("R/m² floor", _fmt_r(n["r_per_m2_floor"]) if n.get("r_per_m2_floor") else None),
        ("Municipal GV", gv),
        ("Asking vs GV", (f"{n['price_vs_gv']}×"
                          if n.get("price_vs_gv") and not long else None)),
        ("Days on market", str(n["days_on_market"]) if n.get("days_on_market") else None),
        ("Suburb median", median),
        ("Price cuts", cut),
        ("Agencies / portals", f"{n.get('brand_count')} / {n.get('source_count')}"),
        ("Mandate", (n.get("mandate_verdict") or "unknown").replace("_", " ")),
        ("Erf", erf),
        ("Photos", str(n["photo_count"]) if n.get("photo_count") else None),
        ("Score", (f"{n['prospect_score']} ({n.get('tier') or '—'})"
                   if n.get("prospect_score") is not None else None)),
    ]
    return [(k, v) for k, v in rows if v]


def to_text(body: dict) -> str:
    """Plain text for WhatsApp, a notes app, or a printed page."""
    ai = body.get("ai") or {}
    lines = _head_lines(body)
    n = body["numbers"]

    opener = ai.get("opener") or (body["talking_points"] or [None])[0]
    if opener:
        lines += ["", "OPENER", opener]

    lines += ["", "KEY NUMBERS"]
    lines += [f"• {k}: {v}" for k, v in _fact_rows(n, long=True)]

    def block(title: str, items: list[str]) -> None:
        if items:
            lines.extend(["", title] + [f"• {i}" for i in items])

    block("TALKING POINTS", ai.get("talking_points") or body["talking_points"])
    if ai.get("cool_facts"):
        block("COOL FACTS", ai["cool_facts"])
    else:
        block("COOL FACTS", [f["text"] + (" (area)" if f["source"] == "area" else "")
                             for f in body["cool_facts"]])
    block("ASK", ai.get("questions") or body["questions"])

    objs = ai.get("objections") or body["objections"]
    if objs:
        lines += ["", "IF THEY SAY…"]
        for o in objs:
            lines += [f"• \"{o['objection']}\"", f"  → {o['response']}"]

    block("AVOID", ai.get("avoid") or body["avoid"])

    t = body.get("tracked")
    if t:
        before = [f"Stage: {str(t['stage']).replace('_', ' ')}"]
        c = t.get("contact") or {}
        if c.get("name") or c.get("phone"):
            before.append(f"Ask for {c.get('name') or '—'}"
                          + (f" · {c['phone']}" if c.get("phone") else ""))
        for i in t.get("interactions") or []:
            before.append(f"{(i['occurred_at'] or '')[:10]} {i['channel']}: "
                          f"{(i.get('outcome') or '').replace('_', ' ')}"
                          f"{' — ' + i['summary'] if i.get('summary') else ''}")
        if t.get("mandate"):
            m = t["mandate"]
            before.append(f"Mandate on file: {m['type']}"
                          + (f", expires {m['expires_at']}" if m.get("expires_at") else ""))
        if t.get("open_tasks"):
            before.append(f"{_plural(t['open_tasks'], 'open task')}")
        block("BEFORE YOU DIAL", before)

    portals = [f"{l['source']} · {l.get('agency') or '—'} · {l['url']}"
               for l in body["property"].get("listings") or []]
    block("LISTINGS", portals)
    if ai:
        lines += ["", f"(AI pass: {ai.get('backend') or 'unknown'})"]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- HTML page

def render_page(body: dict) -> str:
    """The call sheet, for the phone in the agent's other hand.

    Studio Glass: one frosted pane over the graphite scene, sections as
    glass-soft cards, big legible type, and a floating action row pinned to
    the bottom of the screen where a thumb already is. No JavaScript beyond
    the copy button — it has to work on a bad signal in a parked car, so the
    plain-text rendering is baked into the page rather than fetched.
    """
    import html as _html

    import cma_web                        # one stylesheet, one chrome

    e = _html.escape
    ai = body.get("ai") or {}
    p, n = body["property"], body["numbers"]
    gid = body["gid"]

    def ul(items, cls="list") -> str:
        return (f'<ul class="{cls}">' +
                "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>") if items else ""

    def tinted(items, tone: str) -> str:
        """The avoid-list and the questions read as tinted rows rather than a
        bullet list: one tone, one line each, wrapping like prose."""
        return ("".join(f'<div class="tint {tone}">{e(i)}</div>' for i in items)
                if items else "")

    head = _head_lines(body)
    opener = ai.get("opener") or (body["talking_points"] or [None])[0]

    facts = _fact_rows(n)

    cool = ([e(c) for c in ai["cool_facts"]] if ai.get("cool_facts")
            else [e(c["text"]) + (' <span class="mg-chip">area</span>'
                                  if c["source"] == "area" else "")
                  for c in body["cool_facts"]])
    objs = ai.get("objections") or body["objections"]
    questions = ai.get("questions") or body["questions"]
    avoid = ai.get("avoid") or body["avoid"]

    tracked = ""
    phone = ""
    t = body.get("tracked")
    if t:
        c = t.get("contact") or {}
        bits = [f'<span class="mg-chip">Stage: '
                f'{e(str(t["stage"]).replace("_", " "))}</span>']
        if c.get("phone"):
            phone = c["phone"]
            bits.append(f'<a class="mg-chip ok" href="tel:{e(c["phone"])}">'
                        f'{e(c.get("name") or c["phone"])}</a>')
        for i in t.get("interactions") or []:
            bits.append('<span class="mg-chip">' + e(
                f"{(i['occurred_at'] or '')[:10]} {i['channel']}: "
                f"{(i.get('outcome') or '').replace('_', ' ')}") + '</span>')
        tracked = ('<section class="mg-card"><h2>Before you dial</h2>'
                   '<div class="mg-chips">' + "".join(bits) + '</div></section>')

    badge = (f'<span class="mg-chip mgr">AI-written · {e(ai["backend"])}</span>'
             if ai.get("backend") else '<span class="mg-chip">From the data</span>')

    body_html = f"""{cma_web._topbar("Call brief")}
<main class="mg-wrap">
<section class="mg-glass pane mg-fadeup"><div class="mg-page sheet">
  <div class="mg-row">
    <div style="min-width:220px">
      <h1>{e(head[0].replace('CALL BRIEF — ', ''))}</h1>
      <p class="sub">{e(head[1])}</p>
      <p class="sub">{e(head[2])}</p>
    </div>
    <div class="mg-actions">{badge}</div>
  </div>

  {f'<section class="mg-card opener"><h2>Opener</h2><p>{e(opener)}</p></section>' if opener else ''}

  <section class="mg-card"><h2>Key numbers</h2>
    <div class="facts">
      {''.join(f'<div class="fact"><span class="mg-label">{e(k)}</span>'
                f'<b class="mg-tnum">{e(v)}</b></div>' for k, v in facts)}
    </div>
  </section>

  <section class="mg-card"><h2>Talking points</h2>
    {ul(ai.get("talking_points") or body["talking_points"])}</section>

  {f'<section class="mg-card"><h2>Cool facts</h2><ul class="list">' + ''.join(f'<li>{c}</li>' for c in cool) + '</ul></section>' if cool else ''}

  {f'<section class="mg-card"><h2>Ask</h2>{tinted(questions, "warn")}</section>' if questions else ''}

  {f'<section class="mg-card"><h2>If they say…</h2>' + ''.join(f'<div class="obj"><b>{e(o["objection"])}</b><span>{e(o["response"])}</span></div>' for o in objs) + '</section>' if objs else ''}

  {f'<section class="mg-card"><h2>Avoid</h2>{tinted(avoid, "crit")}</section>' if avoid else ''}

  {tracked}
  <p class="foot">Built {e(body.get('built_at') or '')} from Oblivion's own crawl.
     Municipal values are the general valuation roll, not a valuation.</p>
</div></section>
</main>
<div class="actbar noprint">
  <div class="mg-glass-strong bar">
    {f'<a class="mg-btn accent" href="tel:{e(phone)}">Call</a>' if phone else ''}
    <button class="mg-btn primary" id="copy" onclick="obCopy()">Copy as text</button>
    <a class="mg-btn secondary" href="/leads/properties/{e(gid)}">Lead</a>
    {f'<a class="mg-btn secondary" href="{e(p["cma_url"])}">CMA</a>' if p.get("cma_url") else ''}
    {f'<a class="mg-btn secondary" href="{e(p["url"])}" target="_blank" rel="noopener">Listing ↗</a>' if p.get("url") else ''}
  </div>
</div>"""

    extra_css = """
 /* The call sheet reads at arm's length: 16px body, 20px section heads, and
    nothing narrower than a thumb. The pane clears the floating action row. */
 .mg-wrap { max-width:760px; }
 .sheet { padding-bottom:112px; font-size:16px; }
 .sheet h1 { font-size:22px; }
 .sheet .sub { margin:2px 0; color:var(--mg-i2); font-size:13.5px; }
 .sheet .mg-card { margin-top:12px; padding:16px 18px; }
 .sheet .mg-card h2 { margin:0 0 10px; font-size:20px; }
 .sheet .list { margin:0; padding-left:20px; }
 .sheet .list li { font-size:16px; line-height:1.55; margin-bottom:8px; }
 .sheet .list li:last-child { margin-bottom:0; }
 .opener { background:rgba(62,207,142,.1) !important; border-color:rgba(62,207,142,.3) !important; }
 .opener p { margin:0; font-size:17px; line-height:1.6; color:var(--mg-i); }
 .facts { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px 20px; }
 .fact b { display:block; font-weight:600; font-size:16px; margin-top:2px; }
 /* .tint — a state-toned row: amber for what to ask, red for what to avoid. */
 .tint { border-radius:var(--mg-r-in); padding:10px 14px; margin-bottom:8px;
         font-size:15.5px; line-height:1.5; }
 .tint:last-child { margin-bottom:0; }
 .tint.warn { background:rgba(240,180,41,.12); border:1px solid rgba(240,180,41,.3);
              color:var(--mg-warn); }
 .tint.crit { background:rgba(242,109,100,.12); border:1px solid rgba(242,109,100,.3);
              color:var(--mg-crit); }
 .obj { padding:10px 0; border-top:1px solid var(--mg-line); }
 .obj:first-of-type { border-top:0; padding-top:0; }
 .obj b { display:block; font-size:15.5px; font-weight:600; }
 .obj span { font-size:15px; color:var(--mg-i2); }
 .foot { margin:20px 0 0; font-size:12.5px; color:var(--mg-i3); }
 /* The action row floats above the sheet, centred, clear of the safe area. */
 .actbar { position:fixed; left:0; right:0; bottom:0; z-index:40;
           display:flex; justify-content:center; pointer-events:none;
           padding:0 16px calc(16px + var(--mg-sab)); }
 .actbar .bar { pointer-events:auto; display:flex; gap:8px; flex-wrap:wrap;
                justify-content:center; padding:6px; border-radius:9999px; }
 @media (max-width:420px) {
   .actbar .bar { width:100%; border-radius:var(--mg-r); }
   .actbar .mg-btn { flex:1 1 auto; padding:0 14px; }
 }
 @media print {
   .actbar { display:none !important; }
   .sheet { padding-bottom:0; }
   .mg-card, .tint { break-inside:avoid; }
 }
"""
    script = ("window.obCopy=function(){var t=document.getElementById('brieftext')"
              ".textContent;navigator.clipboard.writeText(t).then(function(){"
              "var b=document.getElementById('copy');b.textContent='Copied';"
              "setTimeout(function(){b.textContent='Copy as text';},1500);});};")
    hidden = (f'<pre id="brieftext" style="display:none">'
              f'{_html.escape(to_text(body))}</pre>')
    return cma_web._page(f"Call brief — {p.get('suburb') or gid}",
                         body_html + hidden, extra_css, script)


# -------------------------------------------------------------------- CLI

if __name__ == "__main__":
    import sys

    import db
    with db.connect() as conn:
        b = build(conn, sys.argv[1] if len(sys.argv) > 1 else "1")
        print(to_text(b) if b else "no such property")
