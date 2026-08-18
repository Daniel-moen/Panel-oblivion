"""Prospect scoring.

Each property *group* (one physical home, 1+ listings across 1+ portals) is
judged as a prospect for Oblivion Estates — a media-led luxury Cape Town
agency pitching cinematic property films to win mandates.

The governing rule is sellability: Oblivion can only win business on a
property whose seller has NOT granted a sole/exclusive mandate. Everything
here is organised around establishing that, in descending order of certainty:

  1. Hard facts    — two or more different agencies marketing the same home
                     proves it is open; Pam Golding publishes an explicit
                     isExclusiveMandate flag. Both are applied as overrides
                     that the model cannot argue with (`_apply_hard_rules`).
  2. Model reading — otherwise an LLM reads the full description, where SA
                     agents state mandate status in many non-literal ways.
  3. Heuristic     — a transparent fallback when no API key is available.

Confirmed sole mandates are marked sellable=0 and hidden from the report by
default. The exception is a *stale* sole mandate: SA mandates typically run
3-6 months, so one signed 5+ months ago is about to come up for renewal, which
is the single best moment to pitch. Those are surfaced with a timing note.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import config
from sources.base import canonical_agency

# A sole mandate older than this is treated as coming up for renewal.
SOLE_MANDATE_STALE_DAYS = 150

SYSTEM_PROMPT = """\
You are the prospecting analyst for Oblivion Estates, a media-led luxury real \
estate brand in Cape Town, South Africa. Oblivion wins listings by pitching \
Netflix-grade property films and organic-first marketing to sellers whose \
current agency is under-marketing their home.

Oblivion can ONLY do business on a property that is not tied up in a sole \
mandate. Deciding that is your primary job.

South African mandate types — know these cold:
- SOLE / EXCLUSIVE MANDATE: one agency holds the listing exclusively. Closed \
to Oblivion until it expires (mandates typically run 3-6 months).
- JOINT / DUAL MANDATE: two (or a few) named agencies share the mandate. The \
seller has already shown they'll appoint multiple agencies — a GOOD prospect \
signal, not an exclusivity signal.
- OPEN MANDATE: any agency may bring a buyer. The prime target.

You receive one property, aggregated from every portal it was found on \
(Property24, Private Property, Pam Golding, Seeff, RE/MAX). Read the ENTIRE \
description carefully — agents reveal mandate status in many ways: explicit \
badges ("SOLE MANDATE", "JOINT MANDATE"), soft phrasing ("proudly presented \
exclusively by...", "sole agents", "multi-listed"), or nothing at all.

Weigh the supplied evidence in this order of authority:
1. `agencies_marketing_this_property` listing 2+ DIFFERENT agencies — this is \
near-proof of an open mandate. Note that the same agency appearing on several \
portals proves nothing; only distinct agencies count.
2. `explicit_mandate_flags` — published by the portal itself, not marketing \
copy. "not_sole" means the listing agency has recorded it as non-exclusive.
3. The description text.

Judge it:

- mandate_verdict: exactly one of "open", "probably_open", "unknown", \
"probably_sole", "sole". Hard labels ONLY on conclusive evidence: the literal \
words "sole mandate"/"exclusive mandate", or a portal flag -> "sole"; the \
words "open mandate", 2+ distinct agencies, or a "not_sole" flag -> "open". \
An explicit JOINT/DUAL mandate -> "probably_open". Marketing puffery like \
"brought to you exclusively by X" without the word "mandate" is strong but \
not conclusive -> "probably_sole". Nothing to go on -> "unknown".
- luxury_fit: 0-100. Is this the calibre of home worth a film crew? Consider \
price (R15m+ is prime territory, below R8m is rarely worth it), suburb \
prestige (Clifton, Camps Bay, Bantry Bay, Fresnaye, Bishopscourt, Constantia \
are prime; City Bowl is mid), views, architecture cues in the description.
- open_mandate_confidence: 0-100. How confident are you Oblivion could get \
onto this mandate? Multiple distinct agencies is near-conclusive. Explicit \
exclusivity is near-conclusive of the opposite, EXCEPT when the mandate is \
old — a sole mandate signed 5+ months ago is nearly up for renewal, so score \
it moderately rather than zero.
- marketing_weakness: 0-100. How badly is the current listing marketed? Few \
photos (under 15), a short or generic description, no lifestyle narrative, \
price reductions, and long days-on-market all indicate weakness Oblivion can \
exploit in its pitch.
- prospect_score: 0-100 overall. Weigh: is it luxurious enough, can Oblivion \
actually get the mandate, and does its pitch have an angle? A stunning home \
on a freshly-signed sole mandate with great photos is a poor prospect \
regardless of price.
- tier: "hot" (act this week), "warm" (worth a call), "cold" (skip).
- pitch_angle: 1-2 sentences: the specific opening Oblivion's team should use.
- red_flags: anything that argues against pursuing it.

If `is_new_development` is true this is a developer's off-plan launch, not a \
homeowner's resale. There is no seller mandate for Oblivion to win and often \
no built home to film, so score it cold and say so in red_flags — however \
luxurious the copy sounds.

Market context, when present, is your pitch ammunition. \
`price_vs_suburb_median` well above 1.0 combined with long days_on_market \
means an overpriced home and a frustrated seller — prime pitch material: \
raise marketing_weakness and name that angle. `price_cut_history` means the \
seller is already losing faith in the current agency — a strong weakness and \
pitch signal. days_on_market far beyond suburb_market.median_days_on_market \
means the current marketing is demonstrably failing. If `under_offer` is \
true a sale is likely imminent: tier cold, score low, and say so in red_flags.

Evidence freshness matters. `multi_agency_proof_age_hours` is how long ago \
the multi-agency evidence was last confirmed live on the portals; treat proof \
older than ~72h as weaker — the seller may have consolidated onto one agency \
since. `mandate_expiry_date` (where a portal publishes it) is the mandate's \
own end date: a sole mandate within ~60 days of expiry is a prime renewal \
pitch, not a closed door.

Be sceptical and decisive. Most listings are cold."""

# Revealed-preference context from Oblivion's own tracker; set by score_all(),
# appended to the system prompt so scoring leans toward what the team
# actually pursues.
TASTE_CONTEXT: str = ""

_print_lock = threading.Lock()

# Per-backend circuit breaker. Out-of-credits or a bad key fails identically
# for every property, so retrying once per group just burns time and floods the
# log. The first such error retires that provider for the rest of the run and
# the next one in AI_BACKEND_ORDER takes over — only when every provider is
# retired does scoring drop to the heuristic.
_dead_backends: dict[str, str] = {}
_breaker_lock = threading.Lock()

_FATAL_AI_ERRORS = (
    "insufficient_quota", "credit_balance_exhausted", "invalid_api_key",
    "authentication", "billing", "account_deactivated", "unauthorized",
)

# Transient conditions. These say "try again", not "this model is unusable" —
# treating a 429 as model failure silently demoted properties to a weaker
# model, so identical homes were being judged by different models.
_TRANSIENT_AI_ERRORS = (
    "rate_limit", "rate limit", "429", "concurrency", "timeout", "timed out",
    "overloaded", "502", "503", "504", "connection", "temporarily",
)


def _is_transient(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(m in text for m in _FATAL_AI_ERRORS):
        return False
    return any(m in text for m in _TRANSIENT_AI_ERRORS)


def _log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def _is_dead(name: str) -> bool:
    with _breaker_lock:
        return name in _dead_backends


def _trip_breaker_if_fatal(exc: Exception, name: str, label: str) -> bool:
    """True if this error means the named provider cannot work this run."""
    text = f"{type(exc).__name__}: {exc}".lower()
    if not any(marker in text for marker in _FATAL_AI_ERRORS):
        return False
    with _breaker_lock:
        if name in _dead_backends:
            return True
        if "credit" in text or "quota" in text or "billing" in text:
            reason = "out of credits"
        else:
            reason = "key rejected"
        _dead_backends[name] = reason
    _log(f"  ! {label} unavailable ({reason}) — falling back to the next backend.")
    return True


def _configured_backends() -> list[str]:
    """Providers with credentials present, without making a network call.

    The dashboard asks for status in a process that may never have scored
    anything, so availability can't be inferred from _ACTIVE_BACKENDS alone.
    """
    import os
    env = {"kimi": ("MOONSHOT_API_KEY", "KIMI_API_KEY"),
           "openai": ("OPENAI_API_KEY",),
           "anthropic": ("ANTHROPIC_API_KEY",)}
    return [n for n in config.AI_BACKEND_ORDER
            if any(os.environ.get(k) for k in env.get(n, ()))]


def ai_status() -> tuple[bool, str]:
    """(any provider still usable, human-readable reason) — for the dashboard."""
    with _breaker_lock:
        dead = dict(_dead_backends)
    known = _ACTIVE_BACKENDS or set(_configured_backends())
    live = [n for n in config.AI_BACKEND_ORDER if n in known and n not in dead]
    if live:
        return True, ""
    if dead:
        detail = ", ".join(f"{n} ({r})" for n, r in dead.items())
        return False, f"all AI backends unavailable — {detail}"
    return False, "no AI credentials configured"


# Names of backends that had usable credentials at the start of the run.
_ACTIVE_BACKENDS: set[str] = set()


def _system_prompt() -> str:
    return SYSTEM_PROMPT + TASTE_CONTEXT


# ------------------------------------------------------------------ payload

def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%d %B %Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:len(fmt) + 4].strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value[:19])
    except ValueError:
        return None


# ----------------------------------------------------------- market context
#
# The model used to judge every property in a vacuum — its own price, photos
# and prose. But "R45m, 190 days on market" means nothing without knowing the
# suburb's median is R28m and 60 days. These helpers compute that yardstick
# once per scoring run so every payload can carry it.

# A suburb with fewer actives than this can't define a trustworthy median
# (one trophy home skews everything); such suburbs borrow the portfolio-wide
# stats instead, labelled as such so the model knows what it is comparing to.
MARKET_MIN_ACTIVES = 5


def _median(values) -> float | None:
    vals = [v for v in values if v]
    return round(statistics.median(vals), 2) if vals else None


def _market_stats(rows, now: datetime) -> dict:
    """Aggregate one cohort of listing rows into the four market yardsticks."""
    prices = [r["price_zar"] for r in rows if r["price_zar"]]
    # price_per_m2 is only stored when a portal publishes it; derive it from
    # price/floor size otherwise so the median isn't starved.
    ppm2 = []
    for r in rows:
        if r["price_per_m2"]:
            ppm2.append(r["price_per_m2"])
        elif r["price_zar"] and r["floor_size_m2"]:
            ppm2.append(r["price_zar"] / r["floor_size_m2"])
    doms = []
    for r in rows:
        d = _parse_date(r["listing_date"])
        if d:
            doms.append((now - d).days)
    return {
        "active_listings": len(rows),
        "median_price_zar": _median(prices),
        "median_price_per_m2": _median(ppm2),
        "median_days_on_market": _median(doms),
    }


def market_context(conn: sqlite3.Connection) -> dict:
    """Per-suburb_slug stats over ACTIVE listings, plus a portfolio fallback.

    Listings that lifecycle.py has marked 'delisted' in listing_lifecycle are
    excluded — a home that has left the market must not drag the "current
    market" medians. 'active' and 'relisted' rows both count as on-market.

    Returns {"suburbs": {slug: stats}, "portfolio": stats}; each stats dict is
    what _market_stats() produces. Counts are per listing row, not per property
    group — close enough for a median, and it keeps this one cheap query.
    """
    try:
        rows = conn.execute(
            """SELECT l.suburb_slug, l.price_zar, l.floor_size_m2,
                      l.price_per_m2, l.listing_date
               FROM listings l
               LEFT JOIN listing_lifecycle lc ON lc.listing_key = l.listing_key
               WHERE lc.status IS NULL OR lc.status != 'delisted'"""
        ).fetchall()
    except sqlite3.OperationalError:
        # listing_lifecycle doesn't exist yet (fresh DB, lifecycle.update()
        # never ran) — then nothing is provably delisted anyway.
        rows = conn.execute(
            """SELECT suburb_slug, price_zar, floor_size_m2, price_per_m2,
                      listing_date FROM listings"""
        ).fetchall()

    now = datetime.now()
    by_suburb: dict[str, list] = {}
    for r in rows:
        by_suburb.setdefault(r["suburb_slug"], []).append(r)
    return {
        "suburbs": {slug: _market_stats(m, now) for slug, m in by_suburb.items()},
        "portfolio": _market_stats(rows, now),
    }


def price_cut_history(conn: sqlite3.Connection) -> dict[str, dict]:
    """Per listing_key: how often the asking price moved, and the total cut.

    A price cut is the loudest "my agency's marketing is failing me" signal a
    seller can send, so this is fetched in bulk (one query for the whole DB,
    keyed by listing_key) and threaded into every payload. Only listings whose
    price actually changed appear — absence means a clean price history, and
    the payload stays clean.
    """
    out: dict[str, dict] = {}
    try:
        # COUNT(*), not COUNT(DISTINCT price_zar): since the time-series
        # migration each row is an observed change, so a price that returns
        # to an earlier value ("R20m -> R18m -> R20m") counts every move.
        rows = conn.execute(
            """SELECT ph.listing_key,
                      COUNT(*) AS n_prices,
                      (SELECT p2.price_zar FROM price_history p2
                       WHERE p2.listing_key = ph.listing_key
                       ORDER BY p2.observed_at ASC, p2.rowid ASC
                       LIMIT 1) AS first_price,
                      l.price_zar AS current_price
               FROM price_history ph
               JOIN listings l ON l.listing_key = ph.listing_key
               GROUP BY ph.listing_key
               HAVING n_prices > 1"""
        ).fetchall()
    except sqlite3.OperationalError:
        return out
    for r in rows:
        first, current = r["first_price"], r["current_price"]
        cut = 0.0  # price went UP or sideways — still a change worth noting
        if first and current and first > current:
            cut = round((first - current) / first * 100.0, 2)
        out[r["listing_key"]] = {
            "price_changes": r["n_prices"] - 1,   # moves, not price points
            "total_cut_pct": cut,                 # first observed -> current
        }
    return out


def build_ctx(conn: sqlite3.Connection) -> dict:
    """Everything build_prospect_payload wants beyond the group's own rows."""
    return {"market": market_context(conn), "price_hist": price_cut_history(conn)}


def _mandate_created(member: sqlite3.Row) -> datetime | None:
    """Pam Golding publishes the mandate start date in raw_overview."""
    try:
        raw = json.loads(member["raw_overview"] or "{}")
    except (ValueError, TypeError):
        return None
    if isinstance(raw, dict):
        return _parse_date(raw.get("mandateCreated"))
    return None


def _mandate_expiry(member: sqlite3.Row) -> datetime | None:
    """RE/MAX publishes its CRM record's end date in raw_overview.

    On a "Sole" listing that is the mandate's likely expiry — the exact
    pitch window the stale-sole heuristic otherwise has to guess at.
    """
    try:
        raw = json.loads(member["raw_overview"] or "{}")
    except (ValueError, TypeError):
        return None
    if isinstance(raw, dict):
        return _parse_date(raw.get("expiryDate"))
    return None


def _utcnow() -> datetime:
    """Naive UTC now, comparable to SQLite's datetime('now') text."""
    from datetime import timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _proof_age_hours(members: list[sqlite3.Row], brands: list[str]) -> float | None:
    """Age of the multi-agency proof: the STALEST brand's freshest sighting.

    Two brands prove an open mandate only while both listings are actually
    live. Each brand's evidence is as fresh as its most recently seen
    listing; the proof as a whole is as fresh as the weakest brand.
    """
    from sources.base import canonical_agency
    freshest: dict[str, datetime] = {}
    for m in members:
        brand = canonical_agency(m["agency"])
        if not brand:
            continue
        seen = _parse_date(m["last_seen"])
        if seen and (brand not in freshest or seen > freshest[brand]):
            freshest[brand] = seen
    if not all(b in freshest for b in brands):
        return None
    now = _utcnow()
    return max((now - freshest[b]).total_seconds() / 3600.0 for b in brands)


def build_prospect_payload(members: list[sqlite3.Row], ctx: dict | None = None) -> dict:
    """Collapse a property group (1+ listings of the same home) into one payload.

    `ctx` is build_ctx()'s {market, price_hist} — market yardsticks and price
    -cut history computed once per run. Optional so old call sites keep
    working; without it the payload simply lacks the market fields.
    """
    # The listing with the most photos usually has the fullest record.
    primary = max(members, key=lambda m: (m["photo_count"] or 0,
                                          len(m["description"] or "")))
    # Display names, plus the brand-level set that decides "multiple agencies".
    # "Pam Golding Properties - Atlantic Seaboard" and "Pam Golding (Atlantic
    # Seaboard)" are one agency, not proof of an open mandate.
    agencies = sorted({m["agency"].strip() for m in members
                       if m["agency"] and m["agency"].strip()})
    brands = sorted({b for b in (canonical_agency(m["agency"]) for m in members) if b})
    portals = sorted({m["source"] for m in members})

    listed = None
    for m in members:
        d = _parse_date(m["listing_date"])
        if d and (listed is None or d < listed):
            listed = d
    days = (datetime.now() - listed).days if listed else None

    flags = {m["source"]: m["mandate_explicit"] for m in members
             if m["mandate_explicit"]}

    # Longest description across portals — different agents write different copy.
    description = max((m["description"] or "" for m in members), key=len)

    mandate_age = None
    for m in members:
        created = _mandate_created(m)
        if created:
            mandate_age = (datetime.now() - created).days
            break

    mandate_expiry = None
    for m in members:
        expiry = _mandate_expiry(m)
        if expiry:
            mandate_expiry = expiry
            break

    payload = {
        "title": primary["title"],
        "suburb": primary["suburb"],
        "price_zar": primary["price_zar"],
        "property_type": primary["property_type"],
        "bedrooms": primary["bedrooms"],
        "bathrooms": primary["bathrooms"],
        "floor_size_m2": primary["floor_size_m2"],
        "erf_size_m2": primary["erf_size_m2"],
        # the readable form, so the model sees "18 Casos Road, Calypso Beach"
        # rather than the matching key "18 casos rd"
        "street_address": (primary["street_address_raw"]
                           or primary["street_address"]),
        "listing_date": primary["listing_date"],
        "days_on_market": days,
        "photo_count": max((m["photo_count"] or 0) for m in members),
        "price_reduced": any(m["price_reduced"] for m in members),
        "under_offer": any(m["under_offer"] for m in members),
        "is_new_development": bool(any(m["is_development"] for m in members)),
        "agencies_marketing_this_property": agencies,
        "distinct_agency_brands": brands,
        "agency_count": len(brands),
        "portals_carrying_this_property": portals,
        "explicit_mandate_flags": flags,
        "mandate_age_days": mandate_age,
        "description": description[:8000],
        "_proof_age_hours": (_proof_age_hours(members, brands)
                             if len(brands) > 1 else None),
        "_mandate_regex_hint": primary["mandate_text"],
        "_members": [m["listing_key"] for m in members],
        "primary_listing_key": primary["listing_key"],
    }

    # Fields below are added only when the data exists — a payload full of
    # nulls just teaches the model to ignore the keys.

    if payload["_proof_age_hours"] is not None:
        payload["multi_agency_proof_age_hours"] = round(
            payload["_proof_age_hours"], 1)
    if mandate_expiry:
        payload["mandate_expiry_date"] = mandate_expiry.strftime("%Y-%m-%d")
        payload["mandate_days_to_expiry"] = (mandate_expiry
                                             - datetime.now()).days

    # price_per_m2: portal-published where available, else derived.
    ppm2 = primary["price_per_m2"]
    if not ppm2 and primary["price_zar"] and primary["floor_size_m2"]:
        ppm2 = primary["price_zar"] / primary["floor_size_m2"]
    if ppm2:
        payload["price_per_m2"] = round(ppm2, 2)

    if ctx:
        market = ctx.get("market") or {}
        stats = (market.get("suburbs") or {}).get(primary["suburb_slug"])
        if not stats or stats["active_listings"] < MARKET_MIN_ACTIVES:
            # Too few actives to trust a local median — borrow the portfolio-
            # wide stats, labelled so the model knows the comparison basis.
            portfolio = market.get("portfolio")
            if portfolio and portfolio["active_listings"] >= MARKET_MIN_ACTIVES:
                stats = {**portfolio,
                         "basis": "portfolio-wide (too few actives in this "
                                  "suburb for local stats)"}
        if stats:
            payload["suburb_market"] = stats
            if primary["price_zar"] and stats.get("median_price_zar"):
                payload["price_vs_suburb_median"] = round(
                    primary["price_zar"] / stats["median_price_zar"], 2)

        # Any member listing that cut its price condemns the whole property's
        # current marketing — take the loudest signal across the group.
        hist = ctx.get("price_hist") or {}
        cuts = [hist[m["listing_key"]] for m in members
                if m["listing_key"] in hist]
        if cuts:
            payload["price_cut_history"] = {
                "price_changes": max(c["price_changes"] for c in cuts),
                "total_cut_pct": max(c["total_cut_pct"] for c in cuts),
            }

    return payload


# -------------------------------------------------------------- hard rules

def _apply_hard_rules(payload: dict, result: dict) -> dict:
    """Override the model where we have facts rather than inference.

    This is what guarantees the engine never recommends a property Oblivion
    cannot actually sell, and never discards one it provably can.
    """
    flags = set((payload.get("explicit_mandate_flags") or {}).values())
    agency_count = payload.get("agency_count") or 0
    age = payload.get("mandate_age_days")
    note = ""

    if agency_count > 1:
        # Two different agencies on one home: the seller has not granted
        # exclusivity to either. Nothing the model says outranks this —
        # but the proof is only as fresh as its stalest brand. If one of
        # the proving listings hasn't been seen for days the seller may
        # have since consolidated onto a sole mandate with the other
        # agency, so stale proof degrades rather than asserting "open".
        proof_age = payload.get("_proof_age_hours")
        if proof_age is None or proof_age <= config.PROOF_FRESH_HOURS:
            result["mandate_verdict"] = "open"
            result["open_mandate_confidence"] = max(
                result.get("open_mandate_confidence", 0), 92)
            note = (f"{agency_count} different agencies are marketing this "
                    f"property — the mandate cannot be exclusive.")
            if proof_age is not None:
                note += (f" Every brand confirmed live within the last "
                         f"{max(1, int(proof_age))}h.")
        else:
            result["mandate_verdict"] = "probably_open"
            result["open_mandate_confidence"] = max(
                min(result.get("open_mandate_confidence", 0), 80), 70)
            note = (f"{agency_count} agencies were marketing this property, "
                    f"but the stalest brand was last confirmed "
                    f"{proof_age / 24.0:.1f} days ago — re-verify the "
                    f"listing is still live before pitching.")
    elif "sole" in flags:
        result["mandate_verdict"] = "sole"
        result["open_mandate_confidence"] = min(
            result.get("open_mandate_confidence", 100), 12)
        note = "Portal publishes this as an exclusive mandate."
    elif "not_sole" in flags and result.get("mandate_verdict") in (
            None, "unknown", "probably_sole", "sole"):
        result["mandate_verdict"] = "probably_open"
        result["open_mandate_confidence"] = max(
            result.get("open_mandate_confidence", 0), 75)
        note = "Portal publishes this as a non-exclusive mandate."

    verdict = result.get("mandate_verdict") or "unknown"

    # A sole mandate near the end of its term is the best pitch window there
    # is. Prefer the portal's own end date (RE/MAX publishes one) over the
    # signed-N-days-ago guess, which assumes a 180-day term.
    stale_sole = False
    days_to_expiry = payload.get("mandate_days_to_expiry")
    if verdict in ("sole", "probably_sole") and days_to_expiry is not None \
            and days_to_expiry <= 60:
        stale_sole = True
        note = (f"Sole mandate runs to {payload.get('mandate_expiry_date')} "
                f"(the portal's own end date"
                + (", already past" if days_to_expiry < 0
                   else f", {days_to_expiry} days out")
                + "). Pitch now to be first in line for the renewal.")
        result["open_mandate_confidence"] = max(
            result.get("open_mandate_confidence", 0), 45)
    elif verdict in ("sole", "probably_sole") and age and age >= SOLE_MANDATE_STALE_DAYS:
        stale_sole = True
        expiry = datetime.now() + timedelta(days=max(0, 180 - age))
        note = (f"Sole mandate signed {age} days ago — SA mandates run 3-6 "
                f"months, so it is due for renewal around "
                f"{expiry:%b %Y}. Pitch now to be first in line.")
        result["open_mandate_confidence"] = max(
            result.get("open_mandate_confidence", 0), 45)

    # sellable: can Oblivion actually win business here?
    result["sellable"] = 0 if (verdict == "sole" and not stale_sole) else 1
    if verdict == "probably_sole" and not stale_sole:
        result["sellable"] = 0

    # A developer's off-plan launch has no homeowner mandate to compete for,
    # regardless of what the mandate evidence says.
    if payload.get("is_new_development"):
        result["sellable"] = 0
        result["tier"] = "cold"
        result["prospect_score"] = min(result.get("prospect_score", 0), 20)
        note = note or "New/off-plan development — a developer launch, not a mandate Oblivion can win."
        if "development" not in (result.get("red_flags") or "").lower():
            result["red_flags"] = ((result.get("red_flags") or "") +
                                   " New/off-plan development.").strip()

    # Under offer: a buyer is already at the table, so this listing is likely
    # days from disappearing — chasing it now wastes the call. NOT a mandate
    # fact though: sellable stays whatever the mandate logic decided, so if
    # the deal falls through the property resurfaces with its verdict intact.
    # Composes with the development/sole caps because all three only ever
    # lower the score (min) and force tier "cold".
    if payload.get("under_offer"):
        result["tier"] = "cold"
        result["prospect_score"] = min(result.get("prospect_score", 0), 25)
        if "under offer" not in (result.get("red_flags") or "").lower():
            result["red_flags"] = ((result.get("red_flags") or "") +
                                   " Under offer — sale likely imminent.").strip()

    result["mandate_expiry_note"] = note
    if verdict == "sole" and not stale_sole:
        result["tier"] = "cold"
        result["prospect_score"] = min(result.get("prospect_score", 0), 25)
    return result


# ---------------------------------------------------------------- AI scoring

class ProspectScoreModel:
    """Lazy holder so pydantic is only imported when AI scoring runs."""
    _model = None

    @classmethod
    def get(cls):
        if cls._model is None:
            from pydantic import BaseModel

            class ProspectScore(BaseModel):
                mandate_verdict: str
                prospect_score: int
                luxury_fit: int
                open_mandate_confidence: int
                marketing_weakness: int
                tier: str
                reasoning: str
                pitch_angle: str
                red_flags: str

            cls._model = ProspectScore
        return cls._model


def _ai_payload(payload: dict) -> dict:
    """What the model sees — no regex pre-label to bias its own judgment."""
    return {k: v for k, v in payload.items() if not k.startswith("_")}


def _user_message(payload: dict) -> str:
    return ("Score this property as a prospect:\n\n"
            + json.dumps(_ai_payload(payload), ensure_ascii=False,
                         indent=2, sort_keys=True, default=str))


class Backend:
    """One scoring provider. Providers are tried in config.AI_BACKEND_ORDER;
    a provider that dies mid-run hands over to the next one."""

    def __init__(self, name: str, label: str, client, model: str,
                 fallback_model: str | None = None, kind: str = "openai"):
        self.name = name
        self.label = label
        self.client = client
        self.model = model
        self.fallback_model = fallback_model
        self.kind = kind
        limit = config.MAX_CONCURRENCY.get(name, 4)
        self.slots = threading.Semaphore(limit)

    def score(self, payload: dict, model: str | None = None) -> dict | None:
        """Score with this provider, retrying transient failures in place."""
        if _is_dead(self.name):
            return None
        model = model or self.model
        for attempt in range(config.AI_TRANSIENT_RETRIES):
            result, retry = self._attempt(payload, model)
            if not retry:
                return result
            delay = config.AI_RETRY_BASE_DELAY * (2 ** attempt)
            time.sleep(min(delay, 30.0))
        _log(f"    ! {self.label} still rate-limited after "
             f"{config.AI_TRANSIENT_RETRIES} attempts")
        return None

    def _attempt(self, payload: dict, model: str) -> tuple[dict | None, bool]:
        """Returns (result, should_retry_same_model)."""
        try:
            with self.slots:
                return self._call(payload, model), False
        except Exception as e:
            if _trip_breaker_if_fatal(e, self.name, self.label):
                return None, False
            if _is_transient(e):
                return None, True
            if self.fallback_model and model != self.fallback_model:
                _log(f"    ! {model} failed ({type(e).__name__}); "
                     f"trying {self.fallback_model}")
                return self.score(payload, self.fallback_model), False
            _log(f"    ! {self.label} scoring failed: {type(e).__name__}: {e}")
            return None, False

    def _call(self, payload: dict, model: str) -> dict | None:
        if True:  # keeps the provider bodies at one indent level
            if self.kind == "anthropic":
                response = self.client.messages.parse(
                    model=model,
                    max_tokens=config.AI_MAX_TOKENS,
                    thinking={"type": "adaptive"},
                    system=_system_prompt(),
                    messages=[{"role": "user", "content": _user_message(payload)}],
                    output_format=ProspectScoreModel.get(),
                )
                parsed = response.parsed_output
            else:
                # Kimi and OpenAI share the OpenAI SDK surface; both support
                # schema-enforced structured output via .parse().
                response = self.client.chat.completions.parse(
                    model=model,
                    messages=[
                        {"role": "system", "content": _system_prompt()},
                        {"role": "user", "content": _user_message(payload)},
                    ],
                    response_format=ProspectScoreModel.get(),
                )
                parsed = response.choices[0].message.parsed
        if parsed is None:
            return None
        return {**parsed.model_dump(), "scored_by": f"ai:{model}"}


def _kimi_backend():
    import os
    key = os.environ.get("MOONSHOT_API_KEY") or os.environ.get("KIMI_API_KEY")
    if not key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=config.KIMI_BASE_URL)
        return Backend("kimi", f"Kimi ({config.KIMI_MODEL})", client,
                       config.KIMI_MODEL, config.KIMI_FALLBACK_MODEL)
    except Exception:
        return None


def _openai_backend():
    import os
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    try:
        from openai import OpenAI
        return Backend("openai", f"OpenAI ({config.OPENAI_MODEL})", OpenAI(),
                       config.OPENAI_MODEL, config.OPENAI_FALLBACK_MODEL)
    except Exception:
        return None


def _anthropic_backend():
    try:
        import anthropic
        client = anthropic.Anthropic()
        client.messages.count_tokens(
            model=config.AI_MODEL, messages=[{"role": "user", "content": "ping"}]
        )
        return Backend("anthropic", f"Claude ({config.AI_MODEL})", client,
                       config.AI_MODEL, kind="anthropic")
    except Exception:
        return None


_BUILDERS = {"kimi": _kimi_backend, "openai": _openai_backend,
             "anthropic": _anthropic_backend}


def build_backends(use_ai: bool = True) -> list[Backend]:
    """Every usable provider, in preference order."""
    if not use_ai:
        return []
    out = []
    for name in config.AI_BACKEND_ORDER:
        builder = _BUILDERS.get(name)
        if not builder:
            continue
        backend = builder()
        if backend:
            out.append(backend)
    return out


# --------------------------------------------------------- heuristic fallback

def score_heuristic(payload: dict) -> dict:
    price = payload["price_zar"] or 0
    prime = {"Clifton", "Camps Bay", "Bantry Bay", "Fresnaye", "Bishopscourt",
             "Constantia", "Mouille Point", "Llandudno", "Bakoven"}

    if price >= 30_000_000:
        luxury = 90
    elif price >= 15_000_000:
        luxury = 75
    elif price >= config.MIN_PRICE_ZAR:
        luxury = 55
    else:
        luxury = 25
    if payload["suburb"] in prime:
        luxury = min(100, luxury + 10)

    mandate = payload["_mandate_regex_hint"]
    flags = set((payload.get("explicit_mandate_flags") or {}).values())
    if payload["agency_count"] > 1:
        open_conf, verdict = 92, "open"
    elif "sole" in flags:
        open_conf, verdict = 10, "sole"
    elif "not_sole" in flags:
        open_conf, verdict = 75, "probably_open"
    elif mandate == "open":
        open_conf, verdict = 85, "open"
    elif mandate == "dual":
        open_conf, verdict = 70, "probably_open"
    elif mandate == "sole":
        open_conf, verdict = 10, "sole"
    else:
        open_conf, verdict = 45, "unknown"

    weakness = 0
    photos = payload["photo_count"] or 0
    if photos < 15:
        weakness += 35
    elif photos < 25:
        weakness += 15
    desc_len = len(payload["description"] or "")
    if desc_len < 500:
        weakness += 25
    elif desc_len < 1000:
        weakness += 10
    days = payload["days_on_market"]
    if days and days > 120:
        weakness += 30
    elif days and days > 60:
        weakness += 15
    if payload.get("price_reduced"):
        weakness += 15
    # Market-context signals (present only when build_ctx() fed the payload).
    # A tracked cut over 5% is a seller visibly losing faith in their agency.
    cut_pct = (payload.get("price_cut_history") or {}).get("total_cut_pct") or 0
    if cut_pct > 5:
        weakness += 20
    # Priced 25%+ over the suburb median AND sitting longer than the suburb's
    # median DOM: overpriced and stalling — exactly Oblivion's pitch material.
    ratio = payload.get("price_vs_suburb_median")
    suburb_dom = (payload.get("suburb_market") or {}).get("median_days_on_market")
    overpriced_stale = bool(ratio and ratio >= 1.25 and days and suburb_dom
                            and days > suburb_dom)
    if overpriced_stale:
        weakness += 15
    weakness = min(100, weakness)

    score = int(0.40 * luxury + 0.40 * open_conf + 0.20 * weakness)
    if luxury < 40 or open_conf < 15:
        score = min(score, 30)
    if payload.get("is_new_development"):
        score = min(score, 20)      # developer launch, no mandate to win
    if payload.get("under_offer"):
        score = min(score, 25)      # sale likely imminent (hard rule agrees)

    tier = "hot" if score >= 70 else "warm" if score >= 50 else "cold"
    reasons = (
        f"{payload['agency_count']} agency(ies) across "
        f"{len(payload['portals_carrying_this_property'])} portal(s); "
        f"mandate stated: {mandate}; {photos} photos; "
        f"{days if days is not None else '?'} days on market; "
        f"R{price:,.0f} in {payload['suburb']}"
    )
    if cut_pct > 5:
        reasons += f"; asking price cut {cut_pct:.1f}% since first seen"
    if overpriced_stale:
        reasons += (f"; asking {ratio:.2f}x suburb median with DOM above the "
                    f"suburb's {suburb_dom:.0f}d median — overpriced and stalling")
    if payload.get("under_offer"):
        reasons += "; under offer — sale likely imminent"
    return {
        "mandate_verdict": verdict,
        "prospect_score": score,
        "luxury_fit": luxury,
        "open_mandate_confidence": open_conf,
        "marketing_weakness": weakness,
        "tier": tier,
        "reasoning": reasons,
        "pitch_angle": "",
        "red_flags": ("new/off-plan development — no seller mandate to win"
                      if payload.get("is_new_development")
                      else "sole mandate stated" if verdict == "sole" else ""),
        "scored_by": "heuristic",
    }


# ------------------------------------------------------------------- driver

def get_backend(use_ai: bool = True):
    """Back-compat shim: (backends, label) for callers that just want a name."""
    backends = build_backends(use_ai)
    return backends, (backends[0].label if backends else "heuristic")


def evaluate(payload: dict, backends: list | None = None) -> dict:
    """Score one payload (no DB access) — safe to call from worker threads.

    Walks the backend chain; the first provider that returns a result wins.
    A provider retired by the circuit breaker is skipped without a request.
    """
    result = None
    for backend in (backends or []):
        result = backend.score(payload)
        if result is not None:
            break
    if result is None:
        result = score_heuristic(payload)
    return _apply_hard_rules(payload, result)


def persist(conn: sqlite3.Connection, members: list[sqlite3.Row],
            result: dict) -> None:
    for m in members:
        conn.execute(
            """INSERT OR REPLACE INTO scores (
                   listing_key, scored_by, mandate_verdict, sellable,
                   prospect_score, luxury_fit, open_mandate_confidence,
                   marketing_weakness, tier, reasoning, pitch_angle,
                   red_flags, mandate_expiry_note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (m["listing_key"], result["scored_by"],
             result.get("mandate_verdict", "unknown"),
             result.get("sellable", 1),
             result["prospect_score"], result["luxury_fit"],
             result["open_mandate_confidence"], result["marketing_weakness"],
             result["tier"], result["reasoning"], result["pitch_angle"],
             result["red_flags"], result.get("mandate_expiry_note", "")),
        )


def score_members(conn: sqlite3.Connection, members: list[sqlite3.Row],
                  backends: list | None = None, ctx: dict | None = None) -> dict:
    """Score one property group and persist it.

    Builds the market context itself when the caller doesn't supply one —
    fine for a single group; bulk callers should build_ctx() once and pass it.
    """
    payload = build_prospect_payload(members, ctx or build_ctx(conn))
    result = evaluate(payload, backends)
    persist(conn, members, result)
    return result


def group_for_listing(conn: sqlite3.Connection, listing_key: str) -> list[sqlite3.Row]:
    """All listings sharing the given listing's property group."""
    return conn.execute(
        """SELECT l.*, g.group_id, g.agency_count, g.source_count
           FROM listings l
           JOIN property_groups g ON g.listing_key = l.listing_key
           WHERE g.group_id = (SELECT group_id FROM property_groups
                               WHERE listing_key = ?)""",
        (listing_key,),
    ).fetchall()


def score_all(conn: sqlite3.Connection, use_ai: bool = True,
              limit: int | None = None, logger=None,
              only_stale: bool = False) -> int:
    """Score every qualifying property group, in parallel.

    only_stale=True scores just the groups that need it — never scored, or
    re-scraped since they were last scored. A reasoning model spends real time
    per property, so on a nightly run this is the difference between a couple
    of minutes and re-judging the whole database.
    """
    global TASTE_CONTEXT
    import tracker
    log = logger or _log
    TASTE_CONTEXT = tracker.taste_profile(conn) or ""

    rows = conn.execute(
        """SELECT l.*, g.group_id, g.agency_count, g.source_count,
                  s.scored_at, s.listing_key AS scored_key
           FROM listings l
           JOIN property_groups g ON g.listing_key = l.listing_key
           LEFT JOIN scores s ON s.listing_key = l.listing_key
           WHERE l.price_zar >= ? OR l.price_zar IS NULL""",
        (config.MIN_PRICE_ZAR,),
    ).fetchall()

    groups: dict[int, list] = {}
    for r in rows:
        groups.setdefault(r["group_id"], []).append(r)

    # Drop groups whose every listing is below the price floor.
    qualifying = [m for m in groups.values()
                  if any((x["price_zar"] or 0) >= config.MIN_PRICE_ZAR for x in m)]

    if only_stale:
        def needs_scoring(members) -> bool:
            for m in members:
                if m["scored_key"] is None or m["scored_at"] is None:
                    return True                      # never scored
                if (m["last_seen"] or "") > (m["scored_at"] or ""):
                    return True                      # re-scraped since scoring
            return False
        before = len(qualifying)
        qualifying = [m for m in qualifying if needs_scoring(m)]
        log(f"  {before - len(qualifying)} groups already up to date, "
            f"{len(qualifying)} need scoring")

    if limit:
        qualifying = qualifying[:limit]
    if not qualifying:
        return 0

    # Fresh chance for every provider on each run.
    with _breaker_lock:
        _dead_backends.clear()
    backends = build_backends(use_ai)
    _ACTIVE_BACKENDS.clear()
    _ACTIVE_BACKENDS.update(b.name for b in backends)

    if backends:
        chain = " -> ".join(b.label for b in backends) + " -> heuristic"
    else:
        chain = "heuristic (no AI credentials)"
    log(f"  scoring {len(qualifying)} property groups using {chain}")

    # Market yardsticks + price-cut history: computed once, shared by every
    # payload, so per-group cost stays flat however large the run is.
    ctx = build_ctx(conn)
    payloads = [build_prospect_payload(m, ctx) for m in qualifying]
    workers = config.SCORE_WORKERS if backends else 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda p: evaluate(p, backends), payloads))

    for members, result in zip(qualifying, results):
        persist(conn, members, result)

    used = sorted({(r.get("scored_by") or "?") for r in results})
    log(f"  scored by: {', '.join(used)}")
    ok, reason = ai_status()
    if not ok and backends:
        log(f"  NOTE: {reason}. Mandate verdicts still honour hard evidence "
            f"(multi-agency listings and portal mandate flags), but "
            f"descriptions were not read by a model.")
    return len(qualifying)
