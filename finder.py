"""AI prospect finder: turn a plain-English brief into recommended areas
and properties.

    "2 bedroom in a quiet area under R3m, sea view would be nice"

Two model calls, both structured:

  1. parse_brief   the brief -> hard criteria (beds, price, type, suburbs)
                   plus search terms for the soft wishes ("quiet" ->
                   quiet / peaceful / cul-de-sac / ...).
  2. rank          a shortlist of listings that pass the hard criteria and
                   hit the most search terms -> ranked picks with a
                   one-line reason each, plus the areas that suit the brief.

The shortlist between the two calls is what keeps this affordable: the
database holds ~19k listings with 1.4k-char descriptions, far too much to
hand a model per question, so Python does the hard filtering and the model
only reads the ~45 that plausibly fit.

Every step has a no-credentials fallback (regex parse, keyword rank) so the
field still answers on a machine without API keys — less cleverly, but it
never errors out to "no AI".

Providers are the scoring ones (config.AI_BACKEND_ORDER: Kimi, OpenAI,
Claude) — same keys, same order, first usable wins.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from typing import Any

import config
import db
import scorer

MAX_CANDIDATES = 45        # listings the ranking model reads
MAX_PICKS = 12
MAX_AREAS = 5
DESC_CHARS = 320           # description excerpt per candidate
OPENAI_REASONING_EFFORT = "low"   # gpt-5 thinks for a minute on default

# Soft wishes -> words that carry them in portal prose. Used by the regex
# fallback and merged into whatever search terms the model produces, so a
# "quiet" brief always looks for cul-de-sacs even if the model forgot.
SYNONYMS: dict[str, list[str]] = {
    "quiet": ["quiet", "peaceful", "tranquil", "serene", "cul-de-sac",
              "cul de sac", "no through road", "secluded", "private"],
    "secure": ["secure", "security", "24-hour", "24 hour", "access control",
               "gated", "estate", "boomed", "armed response"],
    "family": ["family", "garden", "school", "kids", "children", "play"],
    "sea view": ["sea view", "ocean view", "sea views", "ocean views",
                 "views of the sea", "views of the ocean", "seafront",
                 "beachfront", "sea-facing"],
    "mountain view": ["mountain view", "mountain views", "views of the mountain"],
    "view": ["view", "views", "vista", "panoramic"],
    "beach": ["beach", "beachfront", "walk to the beach", "seafront"],
    "pool": ["pool", "swimming pool", "splash pool"],
    "garden": ["garden", "lawn", "landscaped", "yard"],
    "modern": ["modern", "contemporary", "newly renovated", "renovated",
               "brand new", "new build"],
    "lock-up-and-go": ["lock-up-and-go", "lock up and go", "low maintenance",
                       "easy living", "apartment", "flat"],
    "pet": ["pet friendly", "pet-friendly", "pets allowed", "pets welcome"],
    "retire": ["retirement", "retire", "over 50", "over-50", "frail care",
               "lifestyle village", "single level", "single-level"],
    "golf": ["golf", "fairway", "country club", "golf estate"],
    "estate": ["estate", "gated", "security estate", "lifestyle estate"],
    "office": ["study", "office", "work from home", "home office"],
    "investment": ["investment", "rental", "tenant", "airbnb", "income"],
    "space": ["spacious", "large", "generous", "sprawling", "big"],
    "character": ["character", "victorian", "heritage", "charm", "cottage",
                  "original features"],
    "water": ["lagoon", "canal", "waterfront", "river", "marina", "on the water"],
}

# Brief phrasing -> SYNONYMS keys. Only for the no-model fallback; the model
# maps wishes itself.
_WISH_PATTERNS: list[tuple[str, str]] = [
    (r"\bquiet|peaceful|tranquil|calm|secluded|away from", "quiet"),
    (r"\bsecure|safe|security|gated", "secure"),
    (r"\bfamily|kids|children|school", "family"),
    (r"\bsea ?view|ocean ?view|view of the sea|sea-?facing", "sea view"),
    (r"\bmountain ?view", "mountain view"),
    (r"\bviews?\b", "view"),
    (r"\bbeach|coast|seaside|seafront", "beach"),
    (r"\bpool", "pool"),
    (r"\bgarden|yard|lawn", "garden"),
    (r"\bmodern|contemporary|renovated|new build", "modern"),
    (r"\block[- ]?up|low[- ]maintenance|easy living", "lock-up-and-go"),
    (r"\bpets?\b|dog|cat\b", "pet"),
    (r"\bretire|over[- ]?50|elderly|pensioner", "retire"),
    (r"\bgolf", "golf"),
    (r"\bestate\b", "estate"),
    (r"\bstudy|office|work from home|wfh", "office"),
    (r"\binvest|rental|airbnb|income", "investment"),
    (r"\bspacious|big\b|large|roomy", "space"),
    (r"\bcharacter|heritage|victorian|charm|cottage", "character"),
    (r"\blagoon|canal|waterfront|marina|river", "water"),
]

_TYPE_WORDS = {
    "apartment": ["apartment", "flat", "unit", "penthouse", "studio"],
    "house": ["house", "home", "freestanding", "freehold", "residence"],
    "townhouse": ["townhouse", "duplex", "simplex", "cluster"],
    "plot": ["plot", "land", "vacant", "stand", "erf"],
    "farm": ["farm", "smallholding", "small holding"],
}

# Which listings.property_type values each canonical type covers.
_TYPE_MATCH = {
    "apartment": ("apartment", "flat", "penthouse", "studio"),
    "house": ("house", "freehold", "freestanding", "residence", "gated estate",
              "cluster", "home"),
    "townhouse": ("townhouse", "duplex", "simplex", "cluster"),
    "plot": ("vacant", "land", "plot", "stand"),
    "farm": ("farm", "smallholding", "small holding"),
}


# ----------------------------------------------------------------- models

class Models:
    """pydantic only when a model call actually happens (same as scorer)."""
    _crit = None
    _rank = None

    @classmethod
    def criteria(cls):
        if cls._crit is None:
            from pydantic import BaseModel

            class Criteria(BaseModel):
                bedrooms_min: int | None
                bedrooms_max: int | None
                bathrooms_min: int | None
                price_min_zar: int | None
                price_max_zar: int | None
                property_types: list[str]      # apartment|house|townhouse|plot|farm
                suburbs: list[str]             # from the known list only
                search_terms: list[str]        # words to look for in listing text
                avoid_terms: list[str]         # words that disqualify a listing
                wishes: list[str]              # the soft asks, in the user's words

            cls._crit = Criteria
        return cls._crit

    @classmethod
    def ranking(cls):
        if cls._rank is None:
            from pydantic import BaseModel

            class AreaPick(BaseModel):
                suburb: str
                why: str

            class Pick(BaseModel):
                listing_key: str
                fit: int
                why: str

            class Ranking(BaseModel):
                summary: str
                areas: list[AreaPick]
                picks: list[Pick]

            cls._rank = Ranking
        return cls._rank


# ------------------------------------------------------------ model calls

_PARSE_SYSTEM = """You turn a property-search brief from an estate agent into
structured search criteria. The market is the Western Cape, South Africa;
prices are rand (ZAR). "2m", "R2 mil", "2 million" all mean 2000000.

Rules:
- Only set a numeric field when the brief states or clearly implies it.
  "2 bedroom" -> bedrooms_min 2 AND bedrooms_max 2. "at least 3 bed" -> min 3.
  "2-3 bed" -> min 2, max 3. "under R3m" -> price_max_zar 3000000.
- property_types: any of apartment, house, townhouse, plot, farm. Empty
  when the brief does not say. "flat" is apartment; "home" alone is not a
  type constraint.
- suburbs: ONLY names that appear in the known-suburbs list you are given,
  spelled exactly as listed. An area the brief names that is not in the list
  is dropped (mention nothing about it). If the brief names a region
  ("Atlantic Seaboard", "West Coast") pick the listed suburbs in it.
- search_terms: 6-20 lowercase words or short phrases that a listing's
  description would contain if it satisfied the soft wishes (quiet, family,
  sea view, secure...). Include synonyms and how portals phrase it:
  "quiet" -> quiet, peaceful, tranquil, cul-de-sac, secluded, no through road.
- avoid_terms: words that would disqualify a listing given the brief
  ("no busy roads" -> main road, busy road; "no complex" -> complex, sectional).
  Usually empty.
- wishes: the soft asks restated briefly, in the user's own terms."""

_RANK_SYSTEM = """You are the prospecting assistant for a Western Cape estate
agency. An agent describes what they (or their buyer) want; you get a
shortlist of listings from the agency's own database that passed the hard
filters, each with an excerpt of its description.

Pick what genuinely fits the brief and say why in one plain sentence each,
citing something concrete from the listing (a feature, the street, the price,
the description). Rank best first. fit is 0-100: 85+ nails the brief, 60-84
fits with a compromise, below 60 is a stretch — leave those out unless
nothing better exists. Use only listing_keys you were given, never invent.

areas: up to 5 suburbs from the shortlist that suit the brief, best first,
each with a one-sentence reason grounded in the listings you saw (price
level, stock, character). summary: two sentences — what fits, and what the
brief has to give up if anything. If nothing fits, say so plainly and return
empty picks."""


def _known_suburbs(rows: list[dict]) -> list[str]:
    return sorted({str(r["suburb"]) for r in rows if r.get("suburb")})


def _ask(system: str, user: str, model_cls, max_tokens: int = 2048
         ) -> tuple[Any, str]:
    """Structured answer from the first usable scoring backend, else None.

    Mirrors scorer.Backend._call, but for an arbitrary schema. Walks the
    providers in config order and moves on when one fails — one bad key
    must not take the feature down when another provider works.
    """
    last_err: Exception | None = None
    for name in config.AI_BACKEND_ORDER:
        if scorer._is_dead(name):           # key rejected / out of credits earlier
            continue
        model = config.AI_MODEL
        extra: dict[str, Any] = {}
        try:
            if name == "anthropic":
                if not os.environ.get("ANTHROPIC_API_KEY"):
                    continue
                import anthropic
                r = anthropic.Anthropic().messages.parse(
                    model=config.AI_MODEL, max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    output_format=model_cls)
                parsed = r.parsed_output
            else:
                if name == "kimi":
                    key = (os.environ.get("MOONSHOT_API_KEY")
                           or os.environ.get("KIMI_API_KEY"))
                    if not key:
                        continue
                    from openai import OpenAI
                    client = OpenAI(api_key=key, base_url=config.KIMI_BASE_URL)
                    model = config.KIMI_MODEL
                elif name == "openai":
                    if not os.environ.get("OPENAI_API_KEY"):
                        continue
                    from openai import OpenAI
                    client, model = OpenAI(), config.OPENAI_MODEL
                    # gpt-5 family are reasoning models: left to themselves they
                    # think for a minute on the rank call and blow gunicorn's
                    # 120s timeout. Kimi's OpenAI-compatible endpoint may reject
                    # the unknown param, so it is openai-only.
                    extra["reasoning_effort"] = OPENAI_REASONING_EFFORT
                else:
                    continue
                r = client.chat.completions.parse(
                    model=model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    response_format=model_cls, **extra)
                parsed = r.choices[0].message.parsed
            if parsed is not None:
                return parsed, f"{name}:{model}"
        except Exception as e:                  # noqa: BLE001 — next provider
            last_err = e
            # A dead key stays dead for the process (same breaker the scorer
            # uses), so the next brief skips straight to a working provider
            # or the keyword fallback instead of paying two failed round-trips.
            if not scorer._trip_breaker_if_fatal(e, name, f"finder/{name}"):
                _log(f"finder: {name} failed: {type(e).__name__}: {e}")
    if last_err:
        _log(f"finder: no provider answered ({type(last_err).__name__})")
    return None, ""


def _log(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------ parse brief

# (R?)(number)(unit?) — three groups. "3" on its own is not money (it is
# "3 bed"); "R3", "3m", "3.5", "3 000 000" and "3000000" are.
_MONEY = r"(r\s*)?(\d+(?:[.,]\d+)?(?:\s\d{3})*)\s*(m\b|mil\b|million|k\b|bar\b)?"


def _rand(rand: str | None, num: str, unit: str | None) -> int | None:
    unit = (unit or "").strip().lower()
    digits = num.replace(" ", "")
    if not rand and not unit and "." not in digits and "," not in digits \
            and len(digits) < 4:
        return None
    v = float(digits.replace(",", "."))
    if unit in ("m", "mil", "million", "bar"):
        return int(v * 1_000_000)
    if unit == "k":
        return int(v * 1_000)
    # bare: 2.5 -> R2.5m, 2500000 -> as is
    return int(v * 1_000_000) if v < 1000 else int(v)


def parse_brief_heuristic(brief: str, known: list[str]) -> dict:
    """Regex parse for machines without model credentials."""
    b = " " + brief.lower().replace("’", "'") + " "
    crit: dict[str, Any] = {
        "bedrooms_min": None, "bedrooms_max": None, "bathrooms_min": None,
        "price_min_zar": None, "price_max_zar": None,
        "property_types": [], "suburbs": [], "search_terms": [],
        "avoid_terms": [], "wishes": []}

    m = re.search(r"(\d+)\s*(?:-|to|–)\s*(\d+)\s*(?:bed|br\b|bedroom)", b)
    if m:
        crit["bedrooms_min"], crit["bedrooms_max"] = int(m[1]), int(m[2])
    else:
        m = re.search(r"(?:at least|min(?:imum)?|\+)?\s*(\d+)\s*\+?\s*(?:bed|br\b|bedroom)", b)
        if m:
            n = int(m[1])
            atleast = bool(re.search(r"at least|min|\+\s*(?:bed|br)|" + m[1] + r"\s*\+", b))
            crit["bedrooms_min"] = n
            crit["bedrooms_max"] = None if atleast else n
    m = re.search(r"(\d+)\s*(?:bath|bathroom)", b)
    if m:
        crit["bathrooms_min"] = int(m[1])

    m = re.search(r"(?:under|below|max(?:imum)?|up to|less than|<)\s*" + _MONEY, b)
    if m:
        crit["price_max_zar"] = _rand(m[1], m[2], m[3])
    m = re.search(r"(?:over|above|from|min(?:imum)?|at least|more than|>)\s*" + _MONEY, b)
    if m:
        crit["price_min_zar"] = _rand(m[1], m[2], m[3])
    if not (crit["price_min_zar"] or crit["price_max_zar"]):
        # In "3-4 bed, R2.5 - 4m" the first range found is the bedrooms, which
        # is not money — keep scanning until both sides read as rands.
        for m in re.finditer(_MONEY + r"\s*(?:-|to|–|and)\s*" + _MONEY, b):
            lo, hi = _rand(m[1], m[2], m[3] or m[6]), _rand(m[4], m[5], m[6])
            if lo and hi:
                crit["price_min_zar"], crit["price_max_zar"] = lo, hi
                break
    m = re.search(r"budget(?: of| is|:)?\s*" + _MONEY, b)
    if m and not crit["price_max_zar"]:
        crit["price_max_zar"] = _rand(m[1], m[2], m[3])

    for t, words in _TYPE_WORDS.items():
        if any(re.search(r"\b" + re.escape(w) + r"s?\b", b) for w in words):
            crit["property_types"].append(t)
    if "house" in crit["property_types"] and re.search(r"\bhome\b", b) \
            and not re.search(r"\bhouse|freestanding|freehold", b):
        crit["property_types"].remove("house")

    for s in known:
        if re.search(r"\b" + re.escape(s.lower()) + r"\b", b):
            crit["suburbs"].append(s)

    terms: list[str] = []
    for pat, key in _WISH_PATTERNS:
        if re.search(pat, b):
            crit["wishes"].append(key)
            terms += SYNONYMS[key]
    crit["search_terms"] = list(dict.fromkeys(terms))
    return crit


def parse_brief(brief: str, known: list[str]) -> tuple[dict, str]:
    """-> (criteria dict, 'provider:model' or 'heuristic')."""
    user = ("Brief:\n" + brief.strip() + "\n\nKnown suburbs:\n"
            + ", ".join(known))
    parsed, who = _ask(_PARSE_SYSTEM, user, Models.criteria(), max_tokens=1024)
    if parsed is None:
        return parse_brief_heuristic(brief, known), "heuristic"
    crit = parsed.model_dump()
    crit["suburbs"] = [s for s in crit["suburbs"] if s in known]
    # Fold in the static synonyms for any wish the model named, so the
    # shortlist never misses the obvious phrasing.
    extra: list[str] = []
    for w in crit.get("wishes") or []:
        for pat, key in _WISH_PATTERNS:
            if re.search(pat, " " + w.lower() + " "):
                extra += SYNONYMS[key]
    crit["search_terms"] = list(dict.fromkeys(
        [t.lower().strip() for t in crit["search_terms"] if t.strip()] + extra))
    crit["avoid_terms"] = [t.lower().strip() for t in crit["avoid_terms"] if t.strip()]
    return crit, who


# -------------------------------------------------------------- shortlist

_WISH_OF = {w: k for k, ws in SYNONYMS.items() for w in ws}


def _wish_of(term: str) -> str:
    return _WISH_OF.get(term, term)


def _type_ok(row_type: str | None, wanted: list[str]) -> bool:
    if not wanted:
        return True
    rt = (row_type or "").lower()
    if not rt:
        return True                      # unknown type: don't exclude
    return any(any(w in rt for w in _TYPE_MATCH.get(t, (t,))) for t in wanted)


def _hard_ok(r: dict, c: dict, *, suburbs: bool = True, beds_slack: int = 0) -> bool:
    beds = r.get("bedrooms")
    if c.get("bedrooms_min") is not None and beds is not None \
            and beds < c["bedrooms_min"] - beds_slack:
        return False
    if c.get("bedrooms_max") is not None and beds is not None \
            and beds > c["bedrooms_max"] + beds_slack:
        return False
    if c.get("bathrooms_min") is not None and r.get("bathrooms") is not None \
            and r["bathrooms"] < c["bathrooms_min"]:
        return False
    p = r.get("price_zar") or 0
    if p:
        if c.get("price_max_zar") and p > c["price_max_zar"]:
            return False
        if c.get("price_min_zar") and p < c["price_min_zar"]:
            return False
    elif c.get("price_min_zar") or c.get("price_max_zar"):
        return False                     # POA can't be judged against a budget
    if not _type_ok(r.get("property_type"), c.get("property_types") or []):
        return False
    if suburbs and c.get("suburbs") and r.get("suburb") not in c["suburbs"]:
        return False
    return True


def _full_text(conn: sqlite3.Connection, keys: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        q = ("SELECT listing_key, COALESCE(title,'') || ' ' || COALESCE(description,'')"
             " FROM listings WHERE listing_key IN (%s)" % ",".join("?" * len(chunk)))
        for k, txt in conn.execute(q, chunk):
            out[k] = txt or ""
    return out


def shortlist(rows: list[dict], crit: dict, conn: sqlite3.Connection,
              limit: int = MAX_CANDIDATES) -> tuple[list[dict], bool]:
    """Listings that pass the hard criteria, best keyword coverage first.
    Returns (candidates, relaxed) — relaxed=True when the strict pass found
    too little and the suburb / bedroom constraints were loosened."""
    passes = [r for r in rows if _hard_ok(r, crit)]
    relaxed = False
    if len(passes) < 8:
        loose = [r for r in rows if _hard_ok(r, crit, suburbs=False, beds_slack=1)]
        if len(loose) > len(passes):
            seen = {r["listing_key"] for r in passes}
            passes += [r for r in loose if r["listing_key"] not in seen]
            relaxed = True
    if not passes:
        return [], relaxed

    terms = [t for t in (crit.get("search_terms") or []) if len(t) > 2]
    avoid = crit.get("avoid_terms") or []
    text = _full_text(conn, [r["listing_key"] for r in passes])

    scored = []
    for r in passes:
        t = text.get(r["listing_key"], "").lower()
        if avoid and any(a in t for a in avoid):
            continue
        hits = [w for w in terms if w in t]
        # distinct wishes covered first (quiet AND secure beats five ways of
        # saying quiet), then raw hits, then prospect score — the agent
        # wants sellable stock, not just a textual fit
        key = (len({_wish_of(h) for h in hits}), len(hits),
               r.get("prospect_score") or 0, r.get("price_zar") or 0)
        scored.append((key, r, hits, t))
    scored.sort(key=lambda x: x[0], reverse=True)

    out = []
    for _, r, hits, t in scored[:limit]:
        excerpt = _excerpt(t, hits)
        out.append({**r, "_hits": hits, "_excerpt": excerpt})
    return out, relaxed


def _excerpt(text: str, hits: list[str], n: int = DESC_CHARS) -> str:
    """Slice of the description around the first matched term, so the
    ranking model sees the sentence that earned the listing its place."""
    if not text:
        return ""
    pos = min((text.find(h) for h in hits if text.find(h) >= 0), default=0)
    start = max(0, pos - n // 3)
    piece = text[start:start + n]
    return ("…" if start else "") + piece.strip() + ("…" if start + n < len(text) else "")


# ------------------------------------------------------------------ rank

def _cand_line(r: dict) -> dict:
    return {
        "listing_key": r["listing_key"],
        "suburb": r.get("suburb"),
        "title": (r.get("title") or "")[:90],
        "type": r.get("property_type"),
        "beds": r.get("bedrooms"), "baths": r.get("bathrooms"),
        "price_zar": r.get("price_zar"),
        "floor_m2": r.get("floor_size_m2"), "erf_m2": r.get("erf_size_m2"),
        "address": r.get("street_address_raw") or r.get("official_address"),
        "days_on_market": r.get("days_on_market"),
        "prospect_score": r.get("prospect_score"), "tier": r.get("tier"),
        "mandate": r.get("mandate_verdict"),
        "matched_terms": r.get("_hits") or [],
        "excerpt": r.get("_excerpt") or "",
    }


def rank_heuristic(cands: list[dict], crit: dict) -> dict:
    picks = []
    for r in cands[:MAX_PICKS]:
        hits = r.get("_hits") or []
        groups: dict[str, list[str]] = {}
        for h in hits:
            groups.setdefault(_wish_of(h), []).append(h)
        bits = [k if k in ws else f"{k} ({', '.join(ws[:2])})" for k, ws in groups.items()]
        why = ("Mentions " + "; ".join(bits[:4])) if bits else "Meets the hard criteria"
        base = 55 + min(len(groups), 4) * 10
        picks.append({"listing_key": r["listing_key"],
                      "fit": min(95, base), "why": why + "."})
    by_sub: dict[str, list[dict]] = {}
    for r in cands:
        if r.get("suburb"):
            by_sub.setdefault(r["suburb"], []).append(r)
    areas = []
    for sub, rs in sorted(by_sub.items(),
                          key=lambda kv: (len(kv[1]), sum(len(x["_hits"]) for x in kv[1])),
                          reverse=True)[:MAX_AREAS]:
        prices = [x["price_zar"] for x in rs if x.get("price_zar")]
        med = sorted(prices)[len(prices) // 2] if prices else None
        areas.append({"suburb": sub,
                      "why": f"{len(rs)} matching listing{'s' if len(rs) != 1 else ''}"
                             + (f", typically around R{med / 1e6:.1f}m" if med else "")
                             + "."})
    wishes = crit.get("wishes") or []
    summary = (f"{len(cands)} listings pass the hard criteria"
               + (f"; ranked by how many of your wishes ({', '.join(wishes[:4])}) "
                  "each description mentions" if wishes else "")
               + ". No AI credentials are configured, so this is a keyword match, "
                 "not a judgment call.")
    return {"summary": summary, "areas": areas, "picks": picks}


def rank(brief: str, crit: dict, cands: list[dict]) -> tuple[dict, str]:
    if not cands:
        return {"summary": "Nothing in the database passes the hard criteria. "
                           "Loosen the budget, bedrooms or area, or crawl more suburbs.",
                "areas": [], "picks": []}, "none"
    user = ("Brief:\n" + brief.strip()
            + "\n\nParsed criteria:\n" + json.dumps(
                {k: v for k, v in crit.items() if v not in (None, [], "")},
                ensure_ascii=False)
            + f"\n\nShortlist ({len(cands)} listings, best keyword coverage first):\n"
            + json.dumps([_cand_line(r) for r in cands], ensure_ascii=False, default=str))
    parsed, who = _ask(_RANK_SYSTEM, user, Models.ranking(), max_tokens=3000)
    if parsed is None:
        return rank_heuristic(cands, crit), "heuristic"
    res = parsed.model_dump()
    valid = {r["listing_key"] for r in cands}
    subs = {r.get("suburb") for r in cands}
    res["picks"] = [p for p in res["picks"] if p["listing_key"] in valid][:MAX_PICKS]
    res["areas"] = [a for a in res["areas"] if a["suburb"] in subs][:MAX_AREAS]
    return res, who


# ------------------------------------------------------------ entry point

_lock = threading.Semaphore(2)        # two briefs in flight at most


def recommend(brief: str, rows: list[dict]) -> dict:
    """The whole thing: brief + the dashboard's prospect rows -> answer.

    rows is the /api/prospects payload (one row per property, listing_key
    of its best listing), so every listing_key returned is one the UI can
    show and open."""
    brief = (brief or "").strip()
    if len(brief) < 3:
        raise ValueError("Describe what you're looking for first.")
    with _lock:
        known = _known_suburbs(rows)
        crit, parsed_by = parse_brief(brief, known)
        with db.connect() as conn:
            cands, relaxed = shortlist(rows, crit, conn)
        result, ranked_by = rank(brief, crit, cands)
    return {
        "brief": brief,
        "criteria": crit,
        "candidates": len(cands),
        "relaxed": relaxed,
        "summary": result["summary"],
        "areas": result["areas"],
        "picks": result["picks"],
        "parsed_by": parsed_by,
        "ranked_by": ranked_by,
        "ai": ranked_by not in ("heuristic", "none"),
    }
