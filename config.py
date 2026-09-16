"""Configuration for the Oblivion Estates prospecting engine."""

import os

# Load .env (keeps API keys out of source / shell history)
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

ROOT = os.path.dirname(os.path.abspath(__file__))

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------- sources
#
# Per-source politeness. Property24 is by far the most aggressive: observed
# behaviour is that ~15 requests at 5s spacing trips a block lasting 10-20
# minutes, and poking it during the block keeps the block alive. The other
# four portals tolerate a few requests per second; 2-3s spacing is already
# conservative for them.
#
# Because each source talks to a different host, they are crawled in PARALLEL
# (see pipeline.py) — the slow Property24 crawl no longer gates the others.
#
#   delay/jitter : seconds between requests to that host
#   backoffs     : escalating sleeps after a 429/503
#   enabled      : crawled by default
SOURCES = {
    "property24": {
        "label": "Property24",
        "base_url": "https://www.property24.com",
        "delay": 12.0, "jitter": 6.0,
        "backoffs": [60, 180, 360],
        "enabled": True,
    },
    "privateproperty": {
        "label": "Private Property",
        "base_url": "https://www.privateproperty.co.za",
        "delay": 2.5, "jitter": 1.5,
        "backoffs": [20, 60, 120],
        "enabled": True,
    },
    "pamgolding": {
        "label": "Pam Golding",
        "base_url": "https://www.pamgolding.co.za",
        "delay": 2.0, "jitter": 1.0,
        "backoffs": [20, 60, 120],
        "enabled": True,
    },
    "seeff": {
        "label": "Seeff",
        "base_url": "https://www.seeff.com",
        "delay": 2.0, "jitter": 1.0,
        "backoffs": [20, 60, 120],
        "enabled": True,
    },
    "remax": {
        "label": "RE/MAX",
        "base_url": "https://www.remax.co.za",
        "delay": 2.0, "jitter": 1.0,
        "backoffs": [20, 60, 120],
        "enabled": True,
    },
    # -- aggregators ----------------------------------------------------
    # Worth crawling next to the agency sites they syndicate: they reach
    # brands with no scrapeable site of their own, and seeing the same house
    # under two agencies is the open-mandate proof this engine hunts for.
    "myproperty": {
        "label": "MyProperty",
        "base_url": "https://www.myproperty.co.za",
        "delay": 2.5, "jitter": 1.5,
        "backoffs": [20, 60, 120],
        "enabled": True,
    },
    "immoafrica": {
        "label": "ImmoAfrica",
        "base_url": "https://www.immoafrica.net",
        "delay": 2.5, "jitter": 1.5,
        "backoffs": [20, 60, 120],
        "enabled": True,
    },
    "rawson": {
        "label": "Rawson",
        "base_url": "https://rawson.co.za",
        "delay": 2.0, "jitter": 1.0,
        "backoffs": [20, 60, 120],
        "enabled": True,
    },
}

# -- the Prop Data platform ---------------------------------------------
#
# propdata.net white-labels one property website to a large part of the SA
# agency market, so these tenants share a single scraper (sources/propdata.py)
# and differ only by domain. Seeff above is one of them; it keeps its own
# entry because locations.json still holds hand-validated paths for it.
#
# Ordered by how much stock each carries in the configured areas. Firzt,
# Wakefields and Acutts run the same platform but are Johannesburg and KZN
# books — four listings between them across all 84 areas — so they are left
# out rather than crawled for nothing.
PROPDATA_SITES = {
    "lewgeffen":   ("Lew Geffen Sotheby's", "https://www.sothebysrealty.co.za"),
    "greeff":      ("Greeff Christie's",    "https://www.greeff.co.za"),
    "dogon":       ("Dogon Group",          "https://www.dgproperties.co.za"),
    "chaseveritt": ("Chas Everitt",         "https://www.chaseveritt.co.za"),
    "harcourts":   ("Harcourts",            "https://www.harcourts.co.za"),
    "jawitz":      ("Jawitz Properties",    "https://www.jawitz.co.za"),
    "century21":   ("Century 21",           "https://www.century21.co.za"),
    "tysonprop":   ("Tyson Properties",     "https://www.tysonprop.co.za"),
    "justproperty": ("Just Property",       "https://www.just.property"),
    "onlyrealty":  ("Only Realty",          "https://www.onlyrealty.co.za"),
}

for _name, (_label, _url) in PROPDATA_SITES.items():
    SOURCES[_name] = {
        "label": _label,
        "base_url": _url,
        "delay": 2.0, "jitter": 1.0,
        "backoffs": [20, 60, 120],
        "enabled": True,
    }

# lxml parses these ~200KB portal pages measurably faster than the stdlib
# html.parser and returns identical results for every field the scrapers
# read (verified field-by-field on cached Property24 detail pages). Falls
# back automatically where lxml is not installed.
try:
    import lxml  # noqa: F401
    HTML_PARSER = "lxml"
except ImportError:                                         # pragma: no cover
    HTML_PARSER = "html.parser"


# Concurrent HTML parsing is a net loss and must be capped.
#
# BeautifulSoup builds its tree in pure Python, so parsing holds the GIL.
# Measured on this codebase's own cached pages: 1 parsing thread manages
# ~44 pages/sec, 8 threads only ~20 — concurrency makes parsing SLOWER while
# also starving the Flask dashboard that shares the process (a /api/prospects
# query goes from 93ms to 3.5s with just 4 crawl threads parsing).
#
# So parsing is funnelled through a semaphore while network waits stay
# concurrent. This costs no crawl throughput and keeps the dashboard usable
# during a run. Raise only if the crawl ever moves out of the web process.
PARSE_WORKERS = int(os.environ.get("PARSE_WORKERS", "1"))


# -- adaptive rate tuning -------------------------------------------------
#
# `delay` above is now only the STARTING gap between requests. httpclient
# tightens it after a run of clean responses and doubles it on any 429/503,
# so a portal that tolerates more gets crawled faster and one that starts
# throttling is backed off from automatically (see httpclient.Fetcher).
#
#   delay_min : floor, never crawl faster than this
#   delay_max : ceiling, where a badly throttling portal gets parked
#   workers   : concurrent detail fetches for this source. The rate limiter
#               still enforces the gap globally per host; workers only let
#               the NEXT request's wait overlap the current one's download,
#               which is most of the win once the gap is short.
#
# Property24 is deliberately kept conservative: measured behaviour is a
# burst limit (~5 requests at 2s spacing trips a 503), so its floor stays
# high and it gets few workers. The other portals are far more tolerant
# than the old fixed 2-3s gap assumed.
_TUNING = {
    "property24": {"delay_min": 4.0, "delay_max": 60.0, "workers": 2},
}
_DEFAULT_TUNING = {"delay_min": 0.6, "delay_max": 20.0, "workers": 3}

for _name, _cfg in SOURCES.items():
    for _k, _v in _TUNING.get(_name, _DEFAULT_TUNING).items():
        _cfg.setdefault(_k, _v)
    # A start gap below the floor would be nonsense; keep them consistent.
    _cfg["delay"] = max(_cfg["delay_min"], _cfg["delay"])


# Back-compat: several modules still reference config.BASE_URL / REQUEST_DELAY
# as "the Property24 settings".
BASE_URL = SOURCES["property24"]["base_url"]
REQUEST_DELAY = SOURCES["property24"]["delay"]
REQUEST_JITTER = SOURCES["property24"]["jitter"]
RETRY_BACKOFFS = SOURCES["property24"]["backoffs"]

# Where persistent state lives. On a host with an ephemeral filesystem
# (Railway, Fly, Heroku) point DATA_DIR at a mounted volume — otherwise every
# redeploy silently starts from an empty database and the crawl history,
# scores and tracker imports are gone.
DATA_DIR = os.environ.get("DATA_DIR", ROOT)

# Cache fetched HTML on disk so re-runs and parser iteration don't re-hit the
# portals (and so a Property24 block doesn't cost you the whole run).
CACHE_DIR = os.environ.get("CACHE_DIR", os.path.join(DATA_DIR, ".httpcache"))
CACHE_TTL_HOURS = 20
CACHE_ENABLED = True
# Hard ceiling on the cache directory. The TTL alone can't bound disk use —
# a full crawl's *live* working set of uncompressed pages overflowed the
# 4.6 GB hosted volume (measured 2026-08-27: 4.5 GB / 9,785 pages) — so
# prune_cache() also evicts oldest-first down to this budget.
CACHE_MAX_MB = int(os.environ.get("CACHE_MAX_MB", "1024"))

# ---------------------------------------------------------------- areas
#
# Areas Oblivion Estates targets, grouped by region.
#
# `town`/`province` identify the area unambiguously — suburb names repeat
# across South Africa (there is a Noordhoek in Velddrif and a Newlands in
# Pretoria), and matching on name alone silently crawls the wrong one.
#
# Portal area ids are NOT hardcoded here. Each portal keys its search pages off
# its own internal ids, so they are mined from the portals' sitemaps into
# locations.json — refresh with `python main.py discover-locations`. The `p24`
# values below are a legacy fallback for areas discovery hasn't run for.
#
# Region coverage reflects Oblivion's own tracker: Atlantic Seaboard and the
# City Bowl dominate, but Stellenbosch is the third most-worked area, and the
# team has pursued Somerset West and Pringle Bay too.
#
# `scope: "town"` marks an entry that covers a whole town in one search rather
# than a single suburb (the Langebaan model). Sources relax their suburb guard
# for these and re-derive the real suburb from each detail URL — see
# sources/base.py. Entries without `scope` are ordinary suburbs.
#
# `p24: None` means no legacy Property24 id is known; discovery mines the real
# path into locations.json, and until it has, the Property24 source simply
# returns no listings for the area (it never guesses).
SUBURBS = {
    # ---------------------------------------------------- Atlantic Seaboard
    "clifton":               {"name": "Clifton",               "p24": 11015, "town": "cape-town",    "province": "western-cape", "region": "Atlantic Seaboard"},
    "camps-bay":             {"name": "Camps Bay",             "p24": 11014, "town": "cape-town",    "province": "western-cape", "region": "Atlantic Seaboard"},
    "bantry-bay":            {"name": "Bantry Bay",            "p24": 11013, "town": "cape-town",    "province": "western-cape", "region": "Atlantic Seaboard"},
    "fresnaye":              {"name": "Fresnaye",              "p24": 11016, "town": "cape-town",    "province": "western-cape", "region": "Atlantic Seaboard"},
    "bakoven":               {"name": "Bakoven",               "p24": 11012, "town": "cape-town",    "province": "western-cape", "region": "Atlantic Seaboard"},
    "llandudno":             {"name": "Llandudno",             "p24": 9118,  "town": "cape-town",    "province": "western-cape", "region": "Atlantic Seaboard"},
    "sea-point":             {"name": "Sea Point",             "p24": 11021, "town": "cape-town",    "province": "western-cape", "region": "Atlantic Seaboard"},
    "three-anchor-bay":      {"name": "Three Anchor Bay",      "p24": 11022, "town": "cape-town",    "province": "western-cape", "region": "Atlantic Seaboard"},
    "green-point":           {"name": "Green Point",           "p24": 11017, "town": "cape-town",    "province": "western-cape", "region": "Atlantic Seaboard"},
    "mouille-point":         {"name": "Mouille Point",         "p24": 11018, "town": "cape-town",    "province": "western-cape", "region": "Atlantic Seaboard"},
    "waterfront":            {"name": "V&A Waterfront",        "p24": 9169,  "town": "cape-town",    "province": "western-cape", "region": "Atlantic Seaboard"},

    # ------------------------------------------------------------ City Bowl
    "cape-town-city-centre": {"name": "City Centre",           "p24": 9138,  "town": "cape-town",    "province": "western-cape", "region": "City Bowl"},
    "de-waterkant":          {"name": "De Waterkant",          "p24": 9141,  "town": "cape-town",    "province": "western-cape", "region": "City Bowl"},
    "gardens":               {"name": "Gardens",               "p24": 9145,  "town": "cape-town",    "province": "western-cape", "region": "City Bowl"},
    "higgovale":             {"name": "Higgovale",             "p24": 9149,  "town": "cape-town",    "province": "western-cape", "region": "City Bowl"},
    "tamboerskloof":         {"name": "Tamboerskloof",         "p24": 9163,  "town": "cape-town",    "province": "western-cape", "region": "City Bowl"},
    "oranjezicht":           {"name": "Oranjezicht",           "p24": 9155,  "town": "cape-town",    "province": "western-cape", "region": "City Bowl"},
    "vredehoek":             {"name": "Vredehoek",             "p24": 9166,  "town": "cape-town",    "province": "western-cape", "region": "City Bowl"},
    "devils-peak-estate":    {"name": "Devil's Peak Estate",   "p24": 16541, "town": "cape-town",    "province": "western-cape", "region": "City Bowl"},

    # ----------------------------------------------------- Southern Suburbs
    "constantia":            {"name": "Constantia",            "p24": 11742, "town": "cape-town",    "province": "western-cape", "region": "Southern Suburbs"},
    "nova-constantia":       {"name": "Nova Constantia",       "p24": 16249, "town": "cape-town",    "province": "western-cape", "region": "Southern Suburbs"},
    "high-constantia":       {"name": "High Constantia",       "p24": 16248, "town": "cape-town",    "province": "western-cape", "region": "Southern Suburbs"},
    "bishopscourt":          {"name": "Bishopscourt",          "p24": 8661,  "town": "cape-town",    "province": "western-cape", "region": "Southern Suburbs"},
    "newlands":              {"name": "Newlands",              "p24": 8679,  "town": "cape-town",    "province": "western-cape", "region": "Southern Suburbs"},
    "claremont-upper":       {"name": "Claremont Upper",       "p24": 14225, "town": "cape-town",    "province": "western-cape", "region": "Southern Suburbs"},
    "kenilworth-upper":      {"name": "Kenilworth Upper",      "p24": 14224, "town": "cape-town",    "province": "western-cape", "region": "Southern Suburbs"},
    "rondebosch":            {"name": "Rondebosch",            "p24": 8682,  "town": "cape-town",    "province": "western-cape", "region": "Southern Suburbs"},
    "wynberg-upper":         {"name": "Wynberg Upper",         "p24": 10102, "town": "cape-town",    "province": "western-cape", "region": "Southern Suburbs"},
    "tokai":                 {"name": "Tokai",                 "p24": 9044,  "town": "cape-town",    "province": "western-cape", "region": "Southern Suburbs"},
    "steenberg":             {"name": "Steenberg",             "p24": 9040,  "town": "cape-town",    "province": "western-cape", "region": "Southern Suburbs"},

    # ------------------------------------------------------------- Hout Bay
    "hout-bay":              {"name": "Hout Bay — all",        "p24": None,  "town": "hout-bay",     "province": "western-cape", "region": "Hout Bay", "scope": "town"},
    "hout-bay-central":      {"name": "Hout Bay Central",      "p24": 16694, "town": "hout-bay",     "province": "western-cape", "region": "Hout Bay"},
    "hout-bay-beachfront":   {"name": "Hout Bay Beachfront",   "p24": 17480, "town": "hout-bay",     "province": "western-cape", "region": "Hout Bay"},
    "hout-bay-heights":      {"name": "Hout Bay Heights",      "p24": 10119, "town": "hout-bay",     "province": "western-cape", "region": "Hout Bay"},
    "scott-estate":          {"name": "Scott Estate",          "p24": 10055, "town": "hout-bay",     "province": "western-cape", "region": "Hout Bay"},

    # ------------------------------------------------------- South Peninsula
    "noordhoek":             {"name": "Noordhoek — all",       "p24": None,  "town": "noordhoek",    "province": "western-cape", "region": "South Peninsula", "scope": "town"},
    "simons-town":           {"name": "Simon's Town — all",    "p24": None,  "town": "simons-town",  "province": "western-cape", "region": "South Peninsula", "scope": "town"},
    "scarborough":           {"name": "Scarborough — all",     "p24": None,  "town": "scarborough",  "province": "western-cape", "region": "South Peninsula", "scope": "town"},
    "kommetjie":             {"name": "Kommetjie",             "p24": 9068,  "town": "kommetjie",    "province": "western-cape", "region": "South Peninsula", "scope": "town"},
    "st-james":              {"name": "St James",              "p24": 9039,  "town": "cape-town",    "province": "western-cape", "region": "South Peninsula"},
    "kalk-bay":              {"name": "Kalk Bay",              "p24": 9067,  "town": "cape-town",    "province": "western-cape", "region": "South Peninsula"},
    "chapmans-peak":         {"name": "Chapman's Peak",        "p24": 15623, "town": "noordhoek",    "province": "western-cape", "region": "South Peninsula"},

    # ------------------------------------------------------------ Blaauwberg
    "melkbosstrand":         {"name": "Melkbosstrand — all",   "p24": None,  "town": "melkbosstrand","province": "western-cape", "region": "Blaauwberg", "scope": "town"},
    "bloubergstrand":        {"name": "Bloubergstrand",        "p24": None,  "town": "blouberg",     "province": "western-cape", "region": "Blaauwberg"},
    "big-bay":               {"name": "Big Bay",               "p24": None,  "town": "blouberg",     "province": "western-cape", "region": "Blaauwberg"},
    "sunset-beach":          {"name": "Sunset Beach",          "p24": None,  "town": "milnerton",    "province": "western-cape", "region": "Blaauwberg"},

    # ------------------------------------------------------------ Winelands
    "stellenbosch":          {"name": "Stellenbosch — all",    "p24": None,  "town": "stellenbosch", "province": "western-cape", "region": "Winelands", "scope": "town"},
    "paarl":                 {"name": "Paarl — all",           "p24": None,  "town": "paarl",        "province": "western-cape", "region": "Winelands", "scope": "town"},
    "stellenbosch-farms":    {"name": "Stellenbosch Farms",    "p24": 8562,  "town": "stellenbosch", "province": "western-cape", "region": "Winelands"},
    "mostertsdrift":         {"name": "Mostertsdrift",         "p24": 11541, "town": "stellenbosch", "province": "western-cape", "region": "Winelands"},
    "dalsig":                {"name": "Dalsig",                "p24": 8528,  "town": "stellenbosch", "province": "western-cape", "region": "Winelands"},
    "paradyskloof":          {"name": "Paradyskloof",          "p24": 8540,  "town": "stellenbosch", "province": "western-cape", "region": "Winelands"},
    "die-boord":             {"name": "Die Boord",             "p24": 8530,  "town": "stellenbosch", "province": "western-cape", "region": "Winelands"},
    "brandwacht":            {"name": "Brandwacht",            "p24": 10436, "town": "stellenbosch", "province": "western-cape", "region": "Winelands"},
    "devonvallei":           {"name": "Devonvallei",           "p24": 8521,  "town": "stellenbosch", "province": "western-cape", "region": "Winelands"},
    "de-zalze-winelands-golf-estate": {"name": "De Zalze",     "p24": 10502, "town": "stellenbosch", "province": "western-cape", "region": "Winelands"},
    "franschhoek":           {"name": "Franschhoek",           "p24": 8653,  "town": "franschhoek",  "province": "western-cape", "region": "Winelands", "scope": "town"},
    "val-de-vie-estate":     {"name": "Val de Vie Estate",     "p24": 11726, "town": "paarl",        "province": "western-cape", "region": "Winelands"},
    "pearl-valley-golf-and-country-estate": {"name": "Pearl Valley", "p24": 11772, "town": "paarl",  "province": "western-cape", "region": "Winelands"},
    "boschenmeer-golf-and-country-estate":  {"name": "Boschenmeer",  "p24": 10770, "town": "paarl",  "province": "western-cape", "region": "Winelands"},

    # ----------------------------------------------------------- Helderberg
    "somerset-west":         {"name": "Somerset West — all",   "p24": None,  "town": "somerset-west", "province": "western-cape", "region": "Helderberg", "scope": "town"},
    "somerset-west-central": {"name": "Somerset West Central", "p24": 9019,  "town": "somerset-west", "province": "western-cape", "region": "Helderberg"},
    "erinvale-golf-estate":  {"name": "Erinvale Golf Estate",  "p24": 8952,  "town": "somerset-west", "province": "western-cape", "region": "Helderberg"},
    "parel-vallei":          {"name": "Parel Vallei",          "p24": 7802,  "town": "somerset-west", "province": "western-cape", "region": "Helderberg"},
    "heldervue":             {"name": "Heldervue",             "p24": 8966,  "town": "somerset-west", "province": "western-cape", "region": "Helderberg"},

    # ---------------------------------------------------------- Whale Coast
    "hermanus":              {"name": "Hermanus — all",        "p24": None,  "town": "hermanus",     "province": "western-cape", "region": "Whale Coast", "scope": "town"},
    "voelklip":              {"name": "Voelklip",              "p24": 7857,  "town": "hermanus",     "province": "western-cape", "region": "Whale Coast"},
    "eastcliff":             {"name": "Eastcliff",             "p24": 7846,  "town": "hermanus",     "province": "western-cape", "region": "Whale Coast"},
    "kwaaiwater":            {"name": "Kwaaiwater",            "p24": 7850,  "town": "hermanus",     "province": "western-cape", "region": "Whale Coast"},
    "hermanus-heights":      {"name": "Hermanus Heights",      "p24": 7849,  "town": "hermanus",     "province": "western-cape", "region": "Whale Coast"},
    "hemel-en-aarde-valley": {"name": "Hemel-en-Aarde Valley", "p24": 17530, "town": "hermanus",     "province": "western-cape", "region": "Whale Coast"},
    "onrus":                 {"name": "Onrus",                 "p24": 10648, "town": "hermanus",     "province": "western-cape", "region": "Whale Coast"},
    "pringle-bay":           {"name": "Pringle Bay",           "p24": 10846, "town": "pringle-bay",  "province": "western-cape", "region": "Whale Coast", "scope": "town"},
    "bettys-bay":            {"name": "Betty's Bay",           "p24": 7823,  "town": "bettys-bay",   "province": "western-cape", "region": "Whale Coast", "scope": "town"},

    # ----------------------------------------------------------- West Coast
    "langebaan":             {"name": "Langebaan",             "p24": 427,   "town": "langebaan",    "province": "western-cape", "region": "West Coast", "scope": "town"},
    "saldanha":              {"name": "Saldanha",              "p24": 410,   "town": "saldanha",     "province": "western-cape", "region": "West Coast", "scope": "town"},
    "jacobsbaai":            {"name": "Jacobsbaai",            "p24": 692,   "town": "jacobsbaai",   "province": "western-cape", "region": "West Coast", "scope": "town"},
    "paternoster":           {"name": "Paternoster",           "p24": 429,   "town": "paternoster",  "province": "western-cape", "region": "West Coast", "scope": "town"},
    "yzerfontein":           {"name": "Yzerfontein",           "p24": 425,   "town": "yzerfontein",  "province": "western-cape", "region": "West Coast", "scope": "town"},
    "st-helena-bay":         {"name": "St Helena Bay",         "p24": 431,   "town": "st-helena-bay","province": "western-cape", "region": "West Coast", "scope": "town"},
    "vredenburg":            {"name": "Vredenburg",            "p24": 430,   "town": "vredenburg",   "province": "western-cape", "region": "West Coast", "scope": "town"},
    "velddrif":              {"name": "Velddrif",              "p24": 428,   "town": "velddrif",     "province": "western-cape", "region": "West Coast", "scope": "town"},

    # ---------------------------------------------------------- Garden Route
    "knysna":                {"name": "Knysna — all",          "p24": None,  "town": "knysna",       "province": "western-cape", "region": "Garden Route", "scope": "town"},
    "plettenberg-bay":       {"name": "Plettenberg Bay — all", "p24": None,  "town": "plettenberg-bay", "province": "western-cape", "region": "Garden Route", "scope": "town"},
}


def regions() -> dict:
    """{region: [(slug, name, scope), ...]} in config order — used by the
    dashboard. scope is "town" or "suburb"; whole-town entries sort first
    within their region so the UI leads with the broad search."""
    out: dict[str, list] = {}
    for slug, info in SUBURBS.items():
        scope = info.get("scope", "suburb")
        out.setdefault(info.get("region", "Other"), []).append(
            (slug, info["name"], scope))
    for items in out.values():
        items.sort(key=lambda t: t[2] != "town")   # stable: keeps config order
    return out


# Property24 search URLs default to /for-sale/<slug>/cape-town/western-cape/<id>.
# Towns outside Cape Town use a different path between /for-sale/ and the id;
# the wrong path 301s to an unrelated area, so it must match exactly.
#
# The rental crawl reuses these unchanged: /to-rent/ mirrors /for-sale/ on
# Property24 exactly — same area path, same area id, same result markup
# (verified against /to-rent/camps-bay/cape-town/western-cape/11014). Only
# the leading segment differs, so a town override fixed here is fixed for
# both crawls.
SEARCH_PATH_OVERRIDES = {
    "langebaan": "langebaan/western-cape",
    "saldanha": "saldanha/western-cape",
    "jacobsbaai": "jacobsbaai/western-cape",
    "vredenburg": "vredenburg/western-cape",
    "paternoster": "paternoster/western-cape",
    "st-helena-bay": "st-helena-bay/western-cape",
    "velddrif": "velddrif/western-cape",
    "yzerfontein": "yzerfontein/western-cape",
    "hout-bay-central": "hout-bay-central/hout-bay/western-cape",
    "stellenbosch-farms": "stellenbosch-farms/stellenbosch/western-cape",
    "franschhoek": "franschhoek/franschhoek/western-cape",
}

LOCATIONS_PATH = os.path.join(ROOT, "locations.json")

# Only surface properties at or above this price as prospects (Oblivion is a
# luxury/media-led brand; low-value stock isn't worth a film crew).
MIN_PRICE_ZAR = 1_000_000

# Ask each portal to pre-filter search results to this floor where it supports
# it. Saves a throttled detail-page request per cheap listing — essential in
# West Coast towns where most stock is far below MIN_PRICE_ZAR. POA listings
# still come through, which is fine (POA often means high-end).
SEARCH_PRICE_FLOOR = MIN_PRICE_ZAR

# ---------------------------------------------------------------- rentals
#
# The same crawl, pointed at each portal's to-rent/to-let section
# (`python main.py crawl --rentals`). Rentals are stored in the same
# `listings` table with listing_type='rent' and are deliberately kept out of
# every for-sale view: they are not mandate prospects, they are not comps,
# and they must never be scored.
#
# Why crawl them at all: a home advertised BOTH for sale and to rent is a
# seller hedging — an owner who could not sell and is bridging with a tenant
# is a live prospecting conversation, and it is one only a rental crawl can
# see. A rental also names the managing agency, which is often a different
# brand to the one holding the sale mandate.
#
# MIN_RENT_ZAR mirrors MIN_PRICE_ZAR. The user wants the lower end of the
# rental market too (2026-09-16: "below 40k"), so the floor only drops
# student rooms and parking bays. It is compared against the MONTHLY EQUIVALENT of the rent
# (see sources.base.monthly_equivalent) — Atlantic Seaboard holiday lets are
# advertised per day, and R25 000/day is not a cheap rental.
MIN_RENT_ZAR = int(os.environ.get("MIN_RENT_ZAR", "5000"))

# Pre-filter the portal's own rent search where it supports a price floor
# (Property24's ?sp=pf=N works identically on /to-rent/).
SEARCH_RENT_FLOOR = MIN_RENT_ZAR

# Pages of search results to crawl per suburb per source (~20 listings/page)
MAX_PAGES_PER_SUBURB = 3

# A whole-town area (scope == "town") covers every suburb in the town at once,
# so three pages is nowhere near its inventory: Private Property carries 905
# Langebaan listings across 46 pages, of which the suburb default reached 60.
# Sources stop as soon as a page yields nothing new, so this is a ceiling
# rather than a target — an area with 40 listings still costs two pages.
#
# The cost lands on the detail fetches, not the search: a first full Langebaan
# crawl is ~900 requests at that portal's pacing. Subsequent runs are cheap,
# because db.recently_seen() skips anything already scraped.
MAX_PAGES_TOWN_SCOPE = 50

DB_PATH = os.environ.get("DB_PATH", os.path.join(DATA_DIR, "prospects.db"))

# Multi-agency open-mandate proof is only as fresh as its STALEST brand: if
# one of the two proving listings hasn't been seen for days, the seller may
# have since consolidated onto a sole mandate with the other agency. Proof
# where every brand was seen live within this window keeps the hard "open"
# verdict at full confidence; staler proof degrades to probably_open with a
# re-verify note. verify.py re-fetches exactly these stale members for
# hot-tier prospects after each crawl.
PROOF_FRESH_HOURS = 72

# verify.py: after each scored crawl, hot multi-agency prospects whose
# members haven't been sighted within VERIFY_STALE_HOURS are re-fetched live
# (cache dropped) before the report goes out, budgeted per run so the extra
# load stays a rounding error against every portal's rate limit.
VERIFY_STALE_HOURS = 24
VERIFY_MAX_FETCHES = 40

# ------------------------------------------------------------- auto-crawl
#
# AUTO_CRAWL=1 turns the dashboard process into the constant loop: a nightly
# full pass over every suburb and enabled portal (Property24 included — its
# 12-18s pacing makes the night the right time for it), plus a cheap
# freshness sweep of the fast portals (page 1 only, Property24 excluded)
# every AUTO_SWEEP_HOURS. Sweeps keep last_seen fresh, which is what the
# proof-freshness gate, the delisting sweep and the price history all feed
# on. Scheduled jobs go through the exact same job path as the dashboard's
# Scrape button — same single-job guard, same progress display, same
# only_stale scoring — so a human and the scheduler can never run over each
# other.
AUTO_CRAWL = os.environ.get("AUTO_CRAWL") == "1"
AUTO_CRAWL_HOUR = int(os.environ.get("AUTO_CRAWL_HOUR", "1"))   # local hour
AUTO_SWEEP_HOURS = float(os.environ.get("AUTO_SWEEP_HOURS", "6"))  # 0 = off

# The nightly pass crawls both books — for-sale and to-rent — so the rental
# view fills itself on a hosted deploy instead of only ever from the CLI.
# Rentals are stored and nothing more (no dedupe, no lifecycle, no scoring),
# so the only cost is crawl time, which is what the night is for. The cheap
# every-few-hours freshness sweep stays sale-only.
# AUTO_CRAWL_RENTALS=0 turns the nightly rental crawl off.
AUTO_CRAWL_RENTALS = os.environ.get("AUTO_CRAWL_RENTALS", "1") != "0"

# Yield canary: a portal redesign can make a parser "succeed" while storing
# far fewer listings, and 48h later the lifecycle sweep would read the gap as
# a mass delisting — poisoning the comps feed with phantom off-market events.
# After a crawl, a source whose crawled-suburb listings were confirmed at
# below this fraction is excluded from that run's delisting sweep and logged.
LIFECYCLE_MIN_COVERAGE = 0.5

# ---------------------------------------------------------------- dedupe
#
# Cross-portal matching thresholds. A pair of listings scoring at or above
# MATCH_THRESHOLD is treated as the same physical property.
GEO_MATCH_METRES = 60          # coords this close are the same building
SIZE_TOLERANCE = 0.03          # floor/erf size ±3%
PRICE_TOLERANCE = 0.07         # asking price ±7%
MATCH_THRESHOLD = 1.0

# ---------------------------------------------------------------- AI scoring
#
# Backends are tried in this order and the first one with usable credentials
# wins; if it fails mid-run (out of credits, bad key) the next takes over
# automatically — see scorer.build_backends().
#
#   1. Kimi     MOONSHOT_API_KEY   (OpenAI-compatible API)
#   2. OpenAI   OPENAI_API_KEY
#   3. Claude   ANTHROPIC_API_KEY
#   4. heuristic fallback (no credentials needed)
AI_BACKEND_ORDER = ("kimi", "openai", "anthropic")

# Kimi / Moonshot. Use the global endpoint — api.moonshot.cn rejects keys
# issued for the international platform. kimi-k3 supports schema-enforced
# structured output through the OpenAI SDK's .parse().
KIMI_BASE_URL = "https://api.moonshot.ai/v1"
KIMI_MODEL = "kimi-k3"
KIMI_FALLBACK_MODEL = "kimi-k2.6"

# Per-provider concurrency ceilings. Moonshot enforces an ORGANISATION-wide
# concurrency limit (3 on this account) and answers 429 above it. Exceeding it
# used to push work onto a weaker model, so scores silently varied by
# provider — the semaphore is what keeps every property on kimi-k3.
MAX_CONCURRENCY = {"kimi": 3, "openai": 8, "anthropic": 4}

# Transient failures (429/timeout/overloaded) are retried on the SAME model
# with backoff, rather than being treated as "this model doesn't work".
AI_TRANSIENT_RETRIES = 5
AI_RETRY_BASE_DELAY = 2.0

OPENAI_MODEL = "gpt-5-mini"          # lightweight; falls back to gpt-4o-mini
OPENAI_FALLBACK_MODEL = "gpt-4o-mini"
AI_MODEL = "claude-opus-4-8"
AI_MAX_TOKENS = 4096

# The AI photo-locator sends every candidate property's photo gallery plus
# ~12 satellite crops to a vision model — the most expensive stage in the
# whole pipeline by far (it has drained an OpenAI credit balance twice).
# Off means crawls and sweeps never trigger it; it runs only when asked —
# per property from the dashboard, or in bulk via POST /api/erf/locate-all.
AI_LOCATE_AUTO = os.environ.get("AI_LOCATE_AUTO", "0") == "1"

# Parallel AI scoring requests. Scoring talks to the model provider, not the
# portals, so it is not bound by the crawl rate limits. Kimi K3 is a reasoning
# model and spends real time per property, so concurrency is what keeps a full
# re-score to a few minutes rather than half an hour.
SCORE_WORKERS = 12


# Running on a cloud host (Railway/Fly/Heroku set $PORT).
HOSTED = bool(os.environ.get("PORT") or os.environ.get("RAILWAY_ENVIRONMENT"))

# Property24 blocks datacenter IPs at the network level, not by rate.
# Measured on Railway (EU West): 2 successful detail fetches, then sustained
# 503s that survived the full 60/180/360s backoff ladder — where the same
# crawl from a residential IP manages ~15 requests before any throttling.
# Slowing down does not help, because it is the IP that is blocked.
#
# So on a hosted deploy Property24 is off by default and the other four
# portals (which serve Railway fine) carry the crawl. Run Property24 locally,
# or set ENABLE_PROPERTY24=1 if you have put a residential proxy in front.
PROPERTY24_HOSTED_OK = os.environ.get("ENABLE_PROPERTY24") == "1"
if HOSTED and not PROPERTY24_HOSTED_OK:
    SOURCES["property24"]["enabled"] = False
    SOURCES["property24"]["blocked_reason"] = (
        "Property24 blocks datacenter IPs — run it locally, or set "
        "ENABLE_PROPERTY24=1 if you have a residential proxy.")


# Bare plots are dropped at crawl time. Oblivion sells filmed homes, so a
# vacant stand has nothing to shoot and no owner holding a mandate worth
# winning — the same reasoning that already excludes off-plan developments.
# It matters most on the aggregators: Langebaan alone offered 172 building
# plots, which would have outnumbered its houses in the report.
#
# Set to False to keep them (the crawl stores them again on the next run).
EXCLUDE_VACANT_LAND = os.environ.get("INCLUDE_VACANT_LAND") != "1"


def enabled_sources() -> list[str]:
    return [k for k, v in SOURCES.items() if v.get("enabled")]
