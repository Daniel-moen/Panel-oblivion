"""Server-side filtering, facets, sorting and CSV export for the prospect list.

The prospect book (webapp._prospects_entry) is ~12k built rows held in
memory. The /prospects page used to download all of it (2.4 MB gzipped) and
filter in the browser; now it sends its filters here and gets one page of
rows plus facet counts back. Everything in this module works on the cached
rows in Python — nothing here touches SQLite, so a query is a few tens of
milliseconds and never rebuilds the book.

The query string IS the contract, shared by /api/prospects/query, the CSV
export, saved views and the /prospects URL (so a view is bookmarkable):

  type=sale|rent        which book (sale default)
  sole=1                include sole mandates (implied by mandate=sole…)
  q                     words, all must appear (title, address, erf, agency…)
  tier                  hot,warm,cold                       (facet: tier)
  suburb                suburb names, comma separated       (facet: suburb)
  region                region names                        (facet: region)
  source                portal names — any member listing   (facet: source)
  agency                substring of any agency name
  ptype                 House,Apartment,Townhouse,Estate,Farm,Commercial,Other
                                                            (facet: property_type)
  mandate               open,probably_open,unknown,probably_sole,sole
                                                            (facet: mandate)
  expiry=1              the scorer noted a mandate expiry
  erf                   resolved | candidates | unresolved
  price_min, price_max  rand (a rental: the rent as stated)
  beds_min, beds_max, baths_min                              (facet: beds)
  floor_min, floor_max  floor area m²
  erf_min, erf_max      erf (land) size m²
  ppm2_min, ppm2_max    asking R/m²
  gv_min, gv_max        asking ÷ municipal valuation (1.0 = on the roll)
  score_min             prospect score
  cut                   minimum total price cut, %
  reduced=1             any price cut / "reduced" flag
  dom_min, dom_max      days on market
  relisted=1            came back after being delisted
  off_min               ... after at least this many days off market
  under_offer=1|0       only / exclude under-offer listings
  agencies_min          distinct agency brands (2 = proven open mandate)
  portals_min           distinct portals carrying it
  dev=1|0               only / exclude new developments
  photo=1               has a photo
  life                  active,delisted,relisted   lifecycle state
  lead                  untracked | tracked | a lead stage (comma list)
  furnished=yes|no      rentals
  available=now         rentals available immediately / already
  keys                  explicit listing_keys (comma) — for pinned picks
  sort                  score | pricedesc | priceasc | newest | stale | cut |
                        weakness | ppm2asc | gvasc | agencies | beds
  limit, offset         page (limit 1-500, default 60)
"""

from __future__ import annotations

import csv
import io
import re
import threading
from collections import OrderedDict
from datetime import datetime

import config

FACETS = ("suburb", "source", "property_type", "tier", "mandate", "region",
          "beds")

BEDS_BUCKETS = ("1", "2", "3", "4", "5+")

# Portal property types are free text ("Apartment / Flat", "Freestanding",
# "Gated Estate" …). The filter and its facet work on a handful of buckets.
_TYPE_RULES = (
    ("Apartment", ("apartment", "flat", "studio", "penthouse", "sectional",
                   "loft", "bachelor")),
    ("Townhouse", ("townhouse", "duplex", "cluster", "simplex", "semi")),
    ("Estate", ("estate",)),
    ("Farm", ("farm", "smallholding", "plot", "agricultural")),
    ("Commercial", ("commercial", "office", "retail", "industrial",
                    "guest house", "guesthouse", "hotel", "lodge")),
    ("House", ("house", "freehold", "freestanding", "residence", "home",
               "villa", "mansion", "cottage")),
)
TYPE_GROUPS = ("House", "Apartment", "Townhouse", "Estate", "Farm",
               "Commercial", "Other")

MANDATES = ("open", "probably_open", "unknown", "probably_sole", "sole")
ERF_RESOLVED = ("ok", "confirmed", "check")

SORTS = ("score", "pricedesc", "priceasc", "newest", "stale", "cut",
         "weakness", "ppm2asc", "gvasc", "agencies", "beds")

_PER_MONTH = {"month": 1.0, "week": 52 / 12, "day": 365 / 12}


def type_group(pt) -> str:
    s = str(pt or "").strip().lower()
    if not s:
        return "Other"
    for name, words in _TYPE_RULES:
        if any(w in s for w in words):
            return name
    return "Other"


def beds_bucket(b) -> str | None:
    try:
        n = float(b)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if n >= 5:
        return "5+"
    return str(max(1, int(n)))


def gid_of(r) -> str:
    g = r.get("group_id")
    return str(g) if g is not None else "solo-" + str(r.get("listing_key"))


def monthly(r):
    p = r.get("price_zar")
    if not p:
        return None
    return p * _PER_MONTH.get(r.get("rent_period") or "month", 1.0)


def _available_now(v) -> bool:
    s = str(v or "").strip().lower()
    if not s:
        return False
    if any(w in s for w in ("immediate", "now", "asap", "vacant")):
        return True
    for fmt in ("%A, %d %B %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.title() if "%A" in fmt or "%B" in fmt
                                     else s, fmt) <= datetime.now()
        except ValueError:
            continue
    return False


# ------------------------------------------------------------ per-row index
#
# Derived, filter-only values computed once per cache entry (the entry dict
# is replaced on every rebuild, so the index goes with it). Built lazily by
# whichever request needs it first; two racing builders produce identical
# lists and the last assignment wins, so no lock is needed.

def _index_row(r) -> dict:
    agencies = r.get("agencies") or []
    listings = r.get("listings") or []
    sources = sorted({m.get("source") for m in listings if m.get("source")}
                     or ({r["source"]} if r.get("source") else set()))
    hay = " ".join(str(x) for x in (
        r.get("title"), r.get("suburb"), r.get("property_type"),
        r.get("street_address"), r.get("street_address_raw"),
        r.get("official_address"), r.get("erf_number"), r.get("pitch_angle"),
        r.get("agent_name"), " ".join(agencies), r.get("source_id"),
        r.get("listing_key"), r.get("description"), r.get("region"),
        " ".join(sources)) if x).lower()
    st = r.get("erf_status") or "none"
    erf = ("resolved" if st in ERF_RESOLVED
           else "candidates" if st == "candidates" else "unresolved")
    return {
        "hay": hay,
        "agencies_l": " | ".join(agencies).lower(),
        "sources": sources,
        "ptype": type_group(r.get("property_type")),
        "beds": beds_bucket(r.get("bedrooms")),
        "mandate": r.get("mandate_verdict") or "unknown",
        "erf": erf,
        "gid": gid_of(r),
        "monthly": monthly(r),
    }


def index_for(entry: dict) -> list:
    ix = entry.get("qx")
    if ix is None or len(ix) != len(entry["rows"]):
        ix = [_index_row(r) for r in entry["rows"]]
        entry["qx"] = ix
    return ix


def summary_for(entry: dict) -> dict:
    """Book-level numbers the page's tiles show, independent of filters."""
    s = entry.get("q_summary")
    if s is not None:
        return s
    rows = entry["rows"]
    rents = sorted(m for m in (monthly(r) for r in rows
                               if r.get("listing_type") == "rent") if m)
    s = {
        "total": len(rows),
        "hot": sum(1 for r in rows if r.get("tier") == "hot"),
        "multi": sum(1 for r in rows if (r.get("brand_count") or 0) >= 2),
        "suburbs": len({r.get("suburb") for r in rows if r.get("suburb")}),
        "median_rent": round(rents[len(rents) // 2]) if rents else None,
        "furnished": sum(1 for r in rows
                         if re.match(r"^\s*y", str(r.get("furnished") or ""),
                                     re.I)),
    }
    entry["q_summary"] = s
    return s


# ------------------------------------------------------------------ params

def _num(v):
    if v is None:
        return None
    s = str(v).strip().replace(" ", "").replace(",", "")
    if not s:
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    return n if n == n and abs(n) != float("inf") else None


def _list(v) -> tuple:
    if v is None:
        return ()
    items = v if isinstance(v, (list, tuple)) else str(v).split(",")
    return tuple(sorted({str(x).strip() for x in items if str(x).strip()}))


def _flag(v):
    """'1'/'true'/'yes' -> True, '0'/'false'/'no' -> False, else None."""
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on", "y"):
        return True
    if s in ("0", "false", "no", "off", "n"):
        return False
    return None


_NUM_KEYS = ("price_min", "price_max", "beds_min", "beds_max", "baths_min",
             "floor_min", "floor_max", "erf_min", "erf_max", "ppm2_min",
             "ppm2_max", "gv_min", "gv_max", "score_min", "cut", "dom_min",
             "dom_max", "off_min", "agencies_min", "portals_min")
_LIST_KEYS = ("tier", "suburb", "region", "source", "ptype", "mandate",
              "life", "lead", "keys")
_FLAG_KEYS = ("expiry", "reduced", "relisted", "under_offer", "dev", "photo")


def parse(args) -> dict:
    """Normalise a request's args (any mapping with .get) into a query dict.

    Unknown or malformed values are dropped rather than rejected: a stale
    bookmark with a retired filter should still open the list.
    """
    get = args.get
    f: dict = {}
    for k in _NUM_KEYS:
        n = _num(get(k))
        if n is not None:
            f[k] = n
    for k in _LIST_KEYS:
        vals = _list(get(k))
        if vals:
            f[k] = vals
    for k in _FLAG_KEYS:
        b = _flag(get(k))
        if b is not None:
            f[k] = b
    q = str(get("q") or "").strip().lower()
    if q:
        f["q"] = tuple(q.split())
    erf = str(get("erf") or "").strip()
    if erf in ("resolved", "candidates", "unresolved"):
        f["erf"] = erf
    agency = str(get("agency") or "").strip().lower()
    if agency:
        f["agency"] = agency
    furn = str(get("furnished") or "").strip().lower()
    if furn in ("yes", "no"):
        f["furnished"] = furn
    if str(get("available") or "").strip().lower() == "now":
        f["available"] = "now"
    if "mandate" in f:
        f["mandate"] = tuple(m for m in f["mandate"] if m in MANDATES) or None
        if f["mandate"] is None:
            del f["mandate"]
    if "tier" in f:
        f["tier"] = tuple(t for t in f["tier"] if t in ("hot", "warm", "cold"))
        if not f["tier"]:
            del f["tier"]

    sort = str(get("sort") or "score").strip()
    listing_type = "rent" if get("type") == "rent" else "sale"
    if sort not in SORTS or (listing_type == "rent" and sort in
                             ("score", "cut", "weakness", "gvasc")):
        sort = "score" if listing_type == "sale" else "pricedesc"
    try:
        limit = int(get("limit") or 60)
    except (TypeError, ValueError):
        limit = 60
    try:
        offset = int(get("offset") or 0)
    except (TypeError, ValueError):
        offset = 0
    # Asking for sole mandates by name only makes sense with them included.
    sole = (_flag(get("sole")) is True
            or any(m in ("sole", "probably_sole") for m in f.get("mandate", ())))
    return {"filters": f, "sort": sort, "type": listing_type, "sole": sole,
            "limit": max(1, min(limit, 500)), "offset": max(0, offset)}


def cache_key(query: dict) -> tuple:
    return (query["type"], query["sole"], query["sort"],
            tuple(sorted(query["filters"].items())))


# ------------------------------------------------------------------ filter

def _between(v, lo, hi) -> bool:
    if lo is None and hi is None:
        return True
    if v is None:
        return False
    if lo is not None and v < lo:
        return False
    if hi is not None and v > hi:
        return False
    return True


def _predicates(f: dict, rent: bool, tracked: dict) -> list:
    """[(facet dim or None, fn(row, ix) -> bool)] for the active filters.

    A predicate tagged with a facet dimension is ignored when counting that
    dimension's facet — so picking one suburb still shows every other
    suburb's count, the way a filter sidebar is expected to behave.

    Every lambda binds what it reads as a default argument: a closure over a
    loop-reassigned local would see only its last value.
    """
    P = []
    add = P.append
    if "tier" in f:
        add(("tier", lambda r, x, s=set(f["tier"]): r.get("tier") in s))
    if "suburb" in f:
        add(("suburb", lambda r, x, s={v.lower() for v in f["suburb"]}:
             (r.get("suburb") or "").lower() in s))
    if "region" in f:
        add(("region", lambda r, x, s=set(f["region"]): r.get("region") in s))
    if "source" in f:
        add(("source", lambda r, x, s=set(f["source"]):
             any(v in s for v in x["sources"])))
    if "ptype" in f:
        add(("property_type", lambda r, x, s=set(f["ptype"]): x["ptype"] in s))
    if "mandate" in f:
        add(("mandate", lambda r, x, s=set(f["mandate"]): x["mandate"] in s))
    if f.get("beds_min") is not None or f.get("beds_max") is not None:
        add(("beds", lambda r, x, lo=f.get("beds_min"), hi=f.get("beds_max"):
             _between(r.get("bedrooms"), lo, hi)))
    if "q" in f:
        add((None, lambda r, x, w=f["q"]: all(t in x["hay"] for t in w)))
    if "agency" in f:
        add((None, lambda r, x, a=f["agency"]: a in x["agencies_l"]))
    if f.get("expiry"):
        add((None, lambda r, x: bool(r.get("mandate_expiry_note"))))
    if "erf" in f:
        add((None, lambda r, x, e=f["erf"]: x["erf"] == e))
    if f.get("price_min") is not None or f.get("price_max") is not None:
        # A rental's price box means a MONTHLY rent, so a per-day holiday
        # let compares on the same scale. POA is hidden once a floor is set
        # and kept under a ceiling-only filter (the old client behaviour).
        def price_ok(r, x, lo=f.get("price_min"), hi=f.get("price_max")):
            p = x["monthly"] if rent else r.get("price_zar")
            if not p:
                return not lo
            return _between(p, lo, hi)
        add((None, price_ok))
    if f.get("baths_min") is not None:
        add((None, lambda r, x, b=f["baths_min"]: (r.get("bathrooms") or 0) >= b))
    for key, lo_k, hi_k in (("floor_size_m2", "floor_min", "floor_max"),
                            ("erf_size_m2", "erf_min", "erf_max"),
                            ("price_per_m2", "ppm2_min", "ppm2_max"),
                            ("price_vs_gv", "gv_min", "gv_max"),
                            ("days_on_market", "dom_min", "dom_max")):
        if f.get(lo_k) is not None or f.get(hi_k) is not None:
            add((None, lambda r, x, key=key, lo=f.get(lo_k), hi=f.get(hi_k):
                 _between(r.get(key), lo, hi)))
    if f.get("score_min") is not None:
        add((None, lambda r, x, n=f["score_min"]:
             (r.get("prospect_score") or -1) >= n))
    if f.get("cut") is not None:
        add((None, lambda r, x, n=f["cut"]: (r.get("total_cut_pct") or 0) >= n))
    if f.get("reduced"):
        add((None, lambda r, x: bool(r.get("total_cut_pct")
                                     or r.get("price_reduced"))))
    for flag, col in (("relisted", "relisted"), ("under_offer", "under_offer"),
                      ("dev", "is_development"), ("photo", "has_photo")):
        if f.get(flag) is not None:
            add((None, lambda r, x, col=col, want=f[flag]:
                 bool(r.get(col)) == want))
    if f.get("off_min") is not None:
        add((None, lambda r, x, n=f["off_min"]:
             (r.get("days_off_market") or 0) >= n))
    if f.get("agencies_min") is not None:
        add((None, lambda r, x, n=f["agencies_min"]:
             (r.get("brand_count") or 0) >= n))
    if f.get("portals_min") is not None:
        add((None, lambda r, x, n=f["portals_min"]: len(x["sources"]) >= n))
    if "life" in f:
        add((None, lambda r, x, s=set(f["life"]):
             (r.get("lifecycle") or "active") in s))
    if "lead" in f:
        def lead_ok(r, x, s=set(f["lead"])):
            stage = tracked.get(x["gid"])
            if stage is None:
                return "untracked" in s
            return "tracked" in s or stage in s
        add((None, lead_ok))
    if "furnished" in f:
        add((None, lambda r, x, want=f["furnished"] == "yes": bool(re.match(
            r"^\s*y", str(r.get("furnished") or ""), re.I)) == want))
    if f.get("available") == "now":
        add((None, lambda r, x: _available_now(r.get("available_from"))))
    if "keys" in f:
        add((None, lambda r, x, s=set(f["keys"]): r.get("listing_key") in s))
    return P


def _facet_values(r, x) -> dict:
    return {"suburb": r.get("suburb"), "source": x["sources"],
            "property_type": x["ptype"], "tier": r.get("tier"),
            "mandate": x["mandate"], "region": r.get("region"),
            "beds": x["beds"]}


def _bump(counts: dict, dim: str, v) -> None:
    if v is None or v == "":
        return
    d = counts[dim]
    if isinstance(v, list):
        for one in v:
            d[one] = d.get(one, 0) + 1
    else:
        d[v] = d.get(v, 0) + 1


_BIG = float("inf")


def _sort_key(sort: str):
    def score(r):
        return r.get("prospect_score") if r.get("prospect_score") is not None else -1
    if sort == "pricedesc":
        return lambda r: -(r.get("price_zar") or 0)
    if sort == "priceasc":
        return lambda r: r.get("price_zar") or _BIG
    if sort == "newest":
        return lambda r: (r.get("days_on_market") if r.get("days_on_market")
                          is not None else _BIG)
    if sort == "stale":
        return lambda r: -(r.get("days_on_market") or -1)
    if sort == "cut":
        return lambda r: (-(r.get("total_cut_pct") or -1), -score(r))
    if sort == "weakness":
        return lambda r: (-(r.get("marketing_weakness") or -1), -score(r))
    if sort == "ppm2asc":
        return lambda r: r.get("price_per_m2") or _BIG
    if sort == "gvasc":
        return lambda r: r.get("price_vs_gv") or _BIG
    if sort == "agencies":
        return lambda r: (-(r.get("brand_count") or 0), -score(r))
    if sort == "beds":
        return lambda r: (-(r.get("bedrooms") or 0), -(r.get("price_zar") or 0))
    return lambda r: (-score(r), -(r.get("price_zar") or 0))


def run(entry: dict, query: dict, tracked: dict | None = None) -> dict:
    """Filter + facet + sort one cache entry. Returns
    {"idx": [row indices in order], "total": n, "facets": {dim: {v: n}}}."""
    rows = entry["rows"]
    ix = index_for(entry)
    rent = query["type"] == "rent"
    preds = _predicates(query["filters"], rent, tracked or {})
    counts = {d: {} for d in FACETS}
    hits = []
    for i, r in enumerate(rows):
        x = ix[i]
        failed = None
        n_failed = 0
        for dim, fn in preds:
            if not fn(r, x):
                n_failed += 1
                failed = dim
                if n_failed > 1 or dim is None:
                    break
        if n_failed == 0:
            hits.append(i)
            for d, v in _facet_values(r, x).items():
                _bump(counts, d, v)
        elif n_failed == 1 and failed is not None:
            # Fails only its own facet's filter: counts toward that facet.
            _bump(counts, failed, _facet_values(r, x)[failed])
    key = _sort_key(query["sort"])
    # The book is pre-sorted by score, and sort() is stable, so ties keep
    # the score order.
    if query["sort"] != "score":
        hits.sort(key=lambda i: key(rows[i]))
    return {"idx": hits, "total": len(hits), "facets": counts}


class ResultCache:
    """A small LRU of query results per cache entry, so paging through one
    result set, the 304 revalidation poll and the CSV export never re-filter.
    Keyed on the entry object's identity + build time: a rebuilt book is a
    new entry, and the old results are simply never asked for again."""

    def __init__(self, size: int = 48):
        self.size = size
        self.lock = threading.Lock()
        self.data: OrderedDict = OrderedDict()

    def get(self, key):
        with self.lock:
            hit = self.data.get(key)
            if hit is not None:
                self.data.move_to_end(key)
            return hit

    def put(self, key, value) -> None:
        with self.lock:
            self.data[key] = value
            self.data.move_to_end(key)
            while len(self.data) > self.size:
                self.data.popitem(last=False)


# ------------------------------------------------------------------- views

PRESETS = [
    {"id": "preset:hot-open", "name": "Hot open mandates",
     "params": "tier=hot&mandate=open,probably_open"},
    {"id": "preset:cut10", "name": "Price-cut 10%+",
     "params": "cut=10&sort=cut"},
    {"id": "preset:stale90", "name": "Stale 90+ days on market",
     "params": "dom_min=90&sort=stale"},
    {"id": "preset:multi", "name": "Multi-agency, no sole",
     "params": "agencies_min=2&mandate=open,probably_open,unknown"},
    {"id": "preset:relisted", "name": "Relisted",
     "params": "relisted=1&sort=stale"},
    {"id": "preset:under-gv", "name": "Asking under 1.2x GV",
     "params": "gv_max=1.2&sort=gvasc"},
    {"id": "preset:new-week", "name": "New this week",
     "params": "dom_max=7&sort=newest"},
    {"id": "preset:hot-untracked", "name": "Hot, not yet tracked",
     "params": "tier=hot&lead=untracked"},
]


# --------------------------------------------------------------------- CSV

CSV_COLUMNS = (
    ("listing_key", "Listing key"), ("group_id", "Group"),
    ("title", "Title"), ("suburb", "Suburb"), ("region", "Region"),
    ("street_address", "Street address"), ("erf_number", "Erf"),
    ("erf_status", "Erf status"), ("property_type", "Type"),
    ("bedrooms", "Beds"), ("bathrooms", "Baths"),
    ("floor_size_m2", "Floor m2"), ("erf_size_m2", "Erf m2"),
    ("price_zar", "Price (R)"), ("rent_period", "Rent period"),
    ("price_per_m2", "R/m2"), ("gv_value", "Municipal GV (R)"),
    ("price_vs_gv", "Asking / GV"), ("total_cut_pct", "Price cut %"),
    ("price_changes", "Price changes"), ("days_on_market", "Days on market"),
    ("relisted", "Relisted"), ("days_off_market", "Days off market"),
    ("under_offer", "Under offer"), ("is_development", "Development"),
    ("tier", "Tier"), ("prospect_score", "Score"),
    ("luxury_fit", "Luxury fit"),
    ("open_mandate_confidence", "Open-mandate confidence"),
    ("marketing_weakness", "Marketing weakness"),
    ("mandate_verdict", "Mandate"), ("mandate_expiry_note", "Mandate expiry"),
    ("brand_count", "Agency brands"), ("agencies", "Agencies"),
    ("sources", "Portals"), ("agent_name", "Agent"),
    ("furnished", "Furnished"), ("available_from", "Available from"),
    ("lead_stage", "Lead stage"), ("pitch_angle", "Pitch angle"),
    ("url", "Listing URL"), ("urls", "All listing URLs"),
)


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else ""
    if isinstance(v, (list, tuple)):
        return " | ".join(str(x) for x in v if x not in (None, ""))
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def csv_lines(rows, ix, idx, tracked: dict):
    """Yield the CSV text in chunks: a header then one line per row index."""
    buf = io.StringIO()
    w = csv.writer(buf)
    buf.write("﻿")          # Excel opens UTF-8 (R, é, –) correctly
    w.writerow([h for _, h in CSV_COLUMNS])
    for n, i in enumerate(idx):
        r, x = rows[i], ix[i]
        extra = {"sources": x["sources"],
                 "lead_stage": tracked.get(x["gid"]),
                 "urls": [m.get("url") for m in (r.get("listings") or [])],
                 "street_address": (r.get("official_address")
                                    or r.get("street_address")
                                    or r.get("street_address_raw"))}
        w.writerow([_cell(extra[k] if k in extra else r.get(k))
                    for k, _ in CSV_COLUMNS])
        if n % 500 == 499:
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()
    yield buf.getvalue()
