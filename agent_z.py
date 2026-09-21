"""Agent Z — the finder, as a conversation.

The one-shot finder (finder.py, /api/find) takes a brief and answers once.
Agent Z takes a thread:

    you   find me a lock-up-and-go in Blouberg under R1.8m
    Z     Six of these read as proper lock-up-and-gos…
    you   cheaper
    Z     Dropping to R1.4m thins it out, but these four still fit…
    you   what about Parklands instead?

Same machinery underneath, one turn at a time:

  1. read intent   the WHOLE conversation -> the current search, as the same
                   structured criteria finder.parse_brief produces, plus
                   whether this thread is a sale or a rental hunt. A
                   refinement ("cheaper", "Parklands instead") is read
                   against what was already on the table, not in isolation.
  2. reply         finder's shortlist (unchanged: Python does the hard
                   filtering, the model never sees more than ~45 listings)
                   -> ranked picks with a reason each, and a short
                   conversational line to say above the cards.

Two model calls a turn, the same budget finder.py established, through the
same providers in the same order (config.AI_BACKEND_ORDER via finder._ask).

With no credentials on the box it still answers: intent falls back to
finder's regex parse, applied message by message and merged so refinements
still land, and the reply falls back to finder's keyword ranking with a
canned-but-honest line. It never errors out to "no AI".

The server holds no thread state — the client posts the history every turn.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any, Callable

import db
import finder

MAX_TURNS = 14             # messages of history handed to the model
MAX_MSG_CHARS = 700        # per message, trimmed before it is sent
NUDGE_STEP = 0.8           # "cheaper" without a number: 20% off the budget

# Two turns in flight at most, same as the finder — each one is two model
# calls and a full scan of the book.
_lock = threading.Semaphore(2)


# ------------------------------------------------------------ conversation

def _clean(messages: list[dict]) -> list[dict]:
    """The posted history, trimmed to what the model needs to see."""
    out: list[dict] = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = "assistant" if str(m.get("role")) == "assistant" else "user"
        text = str(m.get("content") or "").strip()
        if text:
            out.append({"role": role, "content": text[:MAX_MSG_CHARS]})
    return out[-MAX_TURNS:]


def _latest_user(msgs: list[dict]) -> str:
    for m in reversed(msgs):
        if m["role"] == "user":
            return m["content"]
    return ""


def _render(msgs: list[dict]) -> str:
    return "\n".join(
        ("them: " if m["role"] == "user" else "you: ") + m["content"]
        for m in msgs)


# Which book the thread is about, before any model has spoken. The model
# decides for itself when there are credentials; this is the fallback's
# answer and the guess that picks which book's suburbs the model is shown.
_RENT_RE = re.compile(
    r"\b(to rent|for rent|rent(?:ing|al|als)?|tenant|letting|to let|lease|"
    r"p\.?\s?m\b|per month|a month|pcm|occupation)\b")
_SALE_RE = re.compile(
    r"\b(buy|buying|buyer|purchase|for sale|to sell|selling|seller|bond|"
    r"transfer duty)\b")


def guess_book(msgs: list[dict]) -> str:
    """'rent' or 'sale' from the words in the thread."""
    text = " ".join(m["content"] for m in msgs).lower()
    rent, sale = bool(_RENT_RE.search(text)), bool(_SALE_RE.search(text))
    return "rent" if rent and not sale else "sale"


# ------------------------------------------------------------ intent model

class Models:
    """pydantic only when a model call actually happens (same as finder)."""
    _intent = None

    @classmethod
    def intent(cls):
        if cls._intent is None:
            from pydantic import BaseModel

            class Intent(BaseModel):
                listing_type: str              # 'sale' | 'rent'
                brief: str                     # the search as one standalone line
                bedrooms_min: int | None
                bedrooms_max: int | None
                bathrooms_min: int | None
                price_min_zar: int | None      # monthly rent when listing_type='rent'
                price_max_zar: int | None
                property_types: list[str]      # apartment|house|townhouse|plot|farm
                furnished: str | None          # 'yes' | 'no' | null (rent only)
                suburbs: list[str]             # from the known list only
                search_terms: list[str]
                avoid_terms: list[str]
                wishes: list[str]

            cls._intent = Intent
        return cls._intent


# The parsing rules are finder's, verbatim — one set of rules for both
# surfaces, so "under 3m" means the same thing in the chat and in the
# one-shot finder. What is added here is the conversation: the criteria
# describe the search as it stands NOW, after every refinement.
_INTENT_SYSTEM = f"""You are Agent Z, the property finder for a Western Cape
estate agency. You are reading a conversation between an agent (or their
buyer or tenant) and yourself, and working out what they are looking for
RIGHT NOW — not what they first asked for.

The latest message refines the thread: carry everything still standing and
change only what it changes.
- "cheaper" / "too expensive" -> lower the budget in play by roughly 20%.
- "what about Parklands instead?" -> same search, different suburb; the old
  suburb is dropped.
- "bigger", "one more bedroom" -> raise the bedroom ask, keep the rest.
- a brand new ask ("actually, a plot in Yzerfontein") replaces the old one:
  drop the wishes and limits that clearly belonged to the old search.

First decide the book:
- listing_type: "rent" when they are looking to rent or let (tenant, lease,
  "per month", "pm", "to let"), otherwise "sale". Once a thread is a rental
  hunt it stays one unless they plainly switch.

brief: one line restating the current search as a standalone brief, as an
agent would write it.

Agents name areas loosely, and the list holds whatever the portals printed.
When they name an area that is not in the known-suburbs list word for word,
take every listed suburb that plainly means the same place — match in either
direction, and ignore a trailing s: "Blouberg" -> Bloubergstrand, Blouberg
Rise, Blouberg Sands; "Somerset" -> Somerset West; "Parklands" -> Parkland.
Only leave suburbs empty when nothing listed plausibly matches.

Then the criteria. FOR A SALE THREAD:
{finder._PARSE_SYSTEM}

FOR A RENTAL THREAD, these rules instead:
{finder._PARSE_SYSTEM_RENT}

furnished is only ever set on a rental thread; leave it null on a sale."""


def read_intent(msgs: list[dict], known: list[str], book: str
                ) -> tuple[dict, str, str, str]:
    """The conversation -> (criteria, listing_type, brief, who).

    `known` is the suburb list of the `book` we guessed; when the model reads
    the thread as the other book the caller reloads and revalidates.
    """
    user = ("Conversation (oldest first; 'them' is the agent, 'you' is your "
            "own earlier reply):\n" + _render(msgs)
            + "\n\nKnown suburbs:\n" + ", ".join(known))
    parsed, who = _ask_intent(user)
    if parsed is None:
        crit = intent_heuristic(msgs, known, book == "rent")
        return crit, book, _latest_user(msgs), "heuristic"

    d = parsed.model_dump()
    got = "rent" if str(d.pop("listing_type", "")).strip().lower() == "rent" else "sale"
    brief = (d.pop("brief", "") or "").strip() or _latest_user(msgs)
    rent = got == "rent"
    d["suburbs"] = [s for s in d["suburbs"] if s in known]
    f = (d.get("furnished") or "").strip().lower()
    d["furnished"] = ("yes" if f.startswith("y") else
                      "no" if f.startswith("n") else None)
    if not rent:
        d.pop("furnished", None)
    # Same widening finder.parse_brief does: a wish the model named pulls in
    # the static synonyms, so the shortlist never misses the obvious phrasing.
    syn, extra = finder._syn_for(rent), []
    for w in d.get("wishes") or []:
        for pat, key in finder._wishes_for(rent):
            if re.search(pat, " " + w.lower() + " "):
                extra += syn[key]
    d["search_terms"] = list(dict.fromkeys(
        [t.lower().strip() for t in d["search_terms"] if t.strip()] + extra))
    d["avoid_terms"] = [t.lower().strip() for t in d["avoid_terms"] if t.strip()]
    return d, got, brief, who


def _ask_intent(user: str):
    return finder._ask(_INTENT_SYSTEM, user, Models.intent(), max_tokens=1024)


def revalidate(crit: dict, known: list[str]) -> dict:
    """Drop suburbs the model named that the (re)chosen book has never seen."""
    crit["suburbs"] = [s for s in crit.get("suburbs") or [] if s in known]
    return crit


# -------------------------------------------------------- intent, no model
#
# Without credentials the thread is read with finder's regex parse — once per
# user message, oldest first, each result laid over the last. That is what
# makes "2 bed in Blouberg under R2m" followed by "cheaper" still a Blouberg
# search, which a parse of the latest message alone could never be.

_PAIRS = (("bedrooms_min", "bedrooms_max"), ("price_min_zar", "price_max_zar"))
_CHEAPER = re.compile(r"\b(cheaper|less|lower|too (?:expensive|dear|pricey|much)|"
                      r"under that|tighter budget)\b")
_DEARER = re.compile(r"\b(dearer|pricier|more expensive|higher|bigger budget|"
                     r"spend more|stretch (?:the|my) budget)\b")
_BIGGER = re.compile(r"\b(bigger|larger|more (?:bed|space|room)|extra bed(?:room)?)\b")


def _merge(base: dict, new: dict) -> dict:
    """Lay a later message's criteria over the search so far."""
    out = dict(base)
    for lo, hi in _PAIRS:
        # A range is replaced as a pair: "at least 3 bed" after "2 bed" must
        # not leave the old maximum of 2 standing.
        if new.get(lo) is not None or new.get(hi) is not None:
            out[lo], out[hi] = new.get(lo), new.get(hi)
    if new.get("bathrooms_min") is not None:
        out["bathrooms_min"] = new["bathrooms_min"]
    for f in ("property_types", "suburbs"):
        if new.get(f):
            out[f] = list(new[f])
    for f in ("search_terms", "avoid_terms", "wishes"):
        out[f] = list(dict.fromkeys((out.get(f) or []) + (new.get(f) or [])))
    if new.get("furnished") is not None:
        out["furnished"] = new["furnished"]
    return out


def _nudge(crit: dict, latest: str) -> dict:
    """"cheaper" / "bigger" with no number in them: move what is in play."""
    b = " " + latest.lower() + " "
    if _CHEAPER.search(b) and crit.get("price_max_zar"):
        crit["price_max_zar"] = int(crit["price_max_zar"] * NUDGE_STEP)
        if crit.get("price_min_zar") and crit["price_min_zar"] >= crit["price_max_zar"]:
            crit["price_min_zar"] = None
    elif _DEARER.search(b) and crit.get("price_max_zar"):
        crit["price_max_zar"] = int(crit["price_max_zar"] / NUDGE_STEP)
    if _BIGGER.search(b) and crit.get("bedrooms_min"):
        crit["bedrooms_min"] += 1
        crit["bedrooms_max"] = None
    return crit


def intent_heuristic(msgs: list[dict], known: list[str], rent: bool) -> dict:
    """finder's regex parse, run over the thread rather than one brief."""
    users = [m["content"] for m in msgs if m["role"] == "user"]
    crit: dict[str, Any] = {}
    for text in users:
        parsed = finder.parse_brief_heuristic(text, known, rent)
        crit = parsed if not crit else _merge(crit, parsed)
    if not crit:
        crit = finder.parse_brief_heuristic("", known, rent)
    return _nudge(crit, users[-1] if users else "")


# ------------------------------------------------------------- reply model

_REPLY_SYSTEM_TAIL = """
Answer with:

summary — YOUR CHAT REPLY. One to three short sentences of plain talk, second
person, no greeting, no markdown, no bullet list, no numbered rundown of the
listings: the picks are shown as cards right under your line, so say what you
found, name the trade-off honestly ("nothing at that price has a real sea
view, these three look over the bay instead"), and where it helps, invite the
next refinement. If the shortlist was thin, say so rather than overselling.

picks — what genuinely fits, best first, each with one plain sentence citing
something concrete from the listing (a feature, the street, the price, the
advert's own words). fit is 0-100: 85+ nails it, 60-84 fits with a
compromise, under 60 is a stretch — leave those out unless nothing better
exists. Use only listing_keys you were given, never invent one.

areas — up to 5 suburbs from the shortlist that suit the search, best first,
one grounded sentence each. Empty when the search already names one suburb.

If nothing fits, say so plainly in summary and return no picks."""

_REPLY_SYSTEM = (
    """You are Agent Z, the property finder inside a Western Cape estate
agency's prospecting engine. You are mid-conversation with the agent. You get
the conversation so far, the search as it now stands, and a shortlist of
listings from the agency's own database that passed the hard filters, each
with an excerpt of its description.
""" + _REPLY_SYSTEM_TAIL)

_REPLY_SYSTEM_RENT = (
    """You are Agent Z, the rentals finder inside a Western Cape estate
agency's engine. You are mid-conversation with the agent. You get the
conversation so far, the search as it now stands, and a shortlist of TO-RENT
listings that passed the hard filters, each with an excerpt of its advert.

Every candidate carries rent_per_month — rand a month, already converted from
whatever period it is advertised in — alongside the advertised price and its
period. Judge the budget on rent_per_month. Other rental facts you may cite:
furnished, available_from, deposit, beds, baths, type, suburb, agency. A
rental has no prospect score and no mandate; never mention either.
""" + _REPLY_SYSTEM_TAIL)


_RELAXED_NOTE = """
NOTE: too little passed the search as stated, so the shortlist below was
widened — it reaches past the suburbs and bedroom counts asked for. Do not
answer "nothing fits" while these are in front of you: say plainly that the
exact ask came up short, then offer the nearest of these as the compromise
they are (name the suburb or the bedroom count that differs).
"""


def reply(msgs: list[dict], brief: str, crit: dict, cands: list[dict],
          rent: bool, relaxed: bool = False) -> tuple[dict, str]:
    """Shortlist -> {summary (the chat line), areas, picks}."""
    if not cands:
        return {"summary": _nothing_line(crit, rent), "areas": [], "picks": []}, "none"
    line = finder._cand_line_rent if rent else finder._cand_line
    what = "rentals" if rent else "listings"
    user = ("Conversation so far:\n" + _render(msgs)
            + "\n\nThe search as it now stands:\n" + brief.strip()
            + "\n\nParsed criteria:\n" + json.dumps(
                {k: v for k, v in crit.items() if v not in (None, [], "")},
                ensure_ascii=False)
            + (_RELAXED_NOTE if relaxed else "")
            + f"\n\nShortlist ({len(cands)} {what}, best keyword coverage "
              "first):\n"
            + json.dumps([line(r) for r in cands], ensure_ascii=False,
                         default=str))
    parsed, who = finder._ask(_REPLY_SYSTEM_RENT if rent else _REPLY_SYSTEM,
                              user, finder.Models.ranking(), max_tokens=3000)
    if parsed is None:
        res = finder.rank_heuristic(cands, crit, rent)
        res["summary"] = _canned_line(crit, cands, res["picks"], rent, relaxed)
        return res, "heuristic"
    res = parsed.model_dump()
    valid = {r["listing_key"] for r in cands}
    subs = {r.get("suburb") for r in cands}
    res["picks"] = [p for p in res["picks"]
                    if p["listing_key"] in valid][:finder.MAX_PICKS]
    res["areas"] = [a for a in res["areas"]
                    if a["suburb"] in subs][:finder.MAX_AREAS]
    return res, who


# ------------------------------------------------------- reply, no model
#
# finder.rank_heuristic's summary reads like a report ("45 listings pass the
# hard criteria…"). In a chat that lands wrong, so the keyword path gets a
# line written the way Z talks — and it says plainly that no model read it.

def _money(v: int | None, rent: bool) -> str:
    """R45 000 a month, R1.8m, R850 000 — whichever reads naturally."""
    if not v:
        return ""
    if rent:
        return finder._zar_txt(v) + " a month"
    if v >= 1_000_000:
        return "R" + f"{v / 1e6:.2f}".rstrip("0").rstrip(".") + "m"
    return finder._zar_txt(v)


def _asked_for(crit: dict, rent: bool) -> str:
    bits = []
    lo, hi = crit.get("bedrooms_min"), crit.get("bedrooms_max")
    if lo and hi and lo == hi:
        bits.append(f"{lo}-bed")
    elif lo and hi:
        bits.append(f"{lo}–{hi} bed")
    elif lo:
        bits.append(f"{lo}+ bed")
    for t in (crit.get("property_types") or [])[:2]:
        bits.append(t)
    head = " ".join(bits) or ("rentals" if rent else "properties")
    if crit.get("price_max_zar"):
        head += " under " + _money(crit["price_max_zar"], rent)
    elif crit.get("price_min_zar"):
        head += " over " + _money(crit["price_min_zar"], rent)
    subs = crit.get("suburbs") or []
    if subs:
        head += " in " + (", ".join(subs[:3]) if len(subs) <= 3
                          else f"{subs[0]} and {len(subs) - 1} other areas")
    return head


_NO_AI = ("No AI credentials are set on this machine, so I matched on "
          "keywords rather than reading them properly.")


def _canned_line(crit: dict, cands: list[dict], picks: list[dict],
                 rent: bool, relaxed: bool = False) -> str:
    wishes = crit.get("wishes") or []
    n = len(picks)
    line = (f"Found {n} {_asked_for(crit, rent)} worth a look"
            f" — {len(cands)} passed the hard limits in all.")
    if relaxed:
        line = (f"Not much passes {_asked_for(crit, rent)} exactly, so I "
                f"widened it past the area and bedroom limits — {n} of the "
                f"{len(cands)} near misses are worth a look.")
    if wishes:
        line += (" Ranked by how much of " + ", ".join(wishes[:3])
                 + " each advert actually mentions.")
    return line + " " + _NO_AI


def _nothing_line(crit: dict, rent: bool) -> str:
    return (f"Nothing in the {'rentals ' if rent else ''}book matches "
            f"{_asked_for(crit, rent)}. Loosen the "
            f"{'rent' if rent else 'budget'}, the bedrooms or the area and "
            "I'll look again — or crawl more suburbs first.")


# ------------------------------------------------------------------ cards
#
# The chat renders its own cards, so a pick carries the row it needs rather
# than leaning on whatever list the page happens to have loaded — the thread
# can be about rentals while the engine page is showing the sale book.

_CARD_FIELDS = (
    "listing_key", "group_id", "source", "source_id", "url", "title",
    "suburb", "suburb_slug", "price_zar", "listing_type", "rent_period",
    "property_type", "bedrooms", "bathrooms", "garages", "floor_size_m2",
    "erf_size_m2", "photo_url", "photo_key", "has_photo", "days_on_market",
    "prospect_score", "tier", "mandate_verdict", "agencies", "furnished",
    "available_from", "deposit", "street_address_raw", "price_vs_gv",
)


def _card(r: dict) -> dict:
    return {k: r[k] for k in _CARD_FIELDS if k in r}


# ------------------------------------------------------------ entry point

def respond(messages: list[dict],
            load_rows: Callable[[str], list[dict]],
            listing_type: str | None = None) -> dict:
    """One turn of the conversation.

    messages   the whole thread, [{role: 'user'|'assistant', content}, …];
               the server keeps none of it.
    load_rows  'sale'|'rent' -> that book's /api/prospects payload. A
               callable, not a list, because which book the thread is about
               is part of what this works out — only the book actually used
               is ever built.
    listing_type pins the book when the caller already knows it (the page
               was opened from the rentals view); otherwise Z decides.
    """
    msgs = _clean(messages)
    if not any(m["role"] == "user" for m in msgs):
        raise ValueError("Say what you're looking for first.")
    if len(_latest_user(msgs)) < 2:
        raise ValueError("Say what you're looking for first.")

    pinned = listing_type if listing_type in ("sale", "rent") else None
    book = pinned or guess_book(msgs)

    with _lock:
        rows = load_rows(book)
        known = finder._known_suburbs(rows)
        crit, got, brief, parsed_by = read_intent(msgs, known, book)
        if pinned:
            got = pinned                     # the caller's book wins
        if got != book:
            # The model read the thread as the other book. Swap the stock and
            # revalidate the suburb names against it; the criteria themselves
            # were written under the rules for the book it chose.
            book, rows = got, load_rows(got)
            crit = revalidate(crit, finder._known_suburbs(rows))
        rent = book == "rent"
        with db.connect() as conn:
            cands, relaxed = finder.shortlist(rows, crit, conn, rent=rent)
        res, replied_by = reply(msgs, brief, crit, cands, rent, relaxed)

    by_key = {r["listing_key"]: r for r in cands}
    picks = []
    for p in res["picks"]:
        row = by_key.get(p["listing_key"])
        if row:
            picks.append({"listing_key": p["listing_key"],
                          "fit": p.get("fit"), "why": p.get("why") or "",
                          "row": _card(row)})
    return {
        "reply": (res["summary"] or "").strip(),
        "picks": picks,
        "areas": res["areas"],
        "brief": brief,
        "criteria": crit,
        "listing_type": book,
        "candidates": len(cands),
        "stock": len(rows),
        "relaxed": relaxed,
        "parsed_by": parsed_by,
        "replied_by": replied_by,
        "ai": replied_by not in ("heuristic", "none"),
    }
