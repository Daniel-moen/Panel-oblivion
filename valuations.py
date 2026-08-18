"""City of Cape Town General Valuation roll fetcher.

For every erf resolved by erf.py (the `erf_lookup` table) this module fetches
the City's official GV market valuation from the public search portal at
https://web1.capetown.gov.za/web1/<roll>/ and stores it in the `valuations`
table. The GV value anchors the CMA reports (cma.py reads this table).

How the portal actually works (probed August 2026):

* It is a legacy ASP.NET WebForms app. The newest roll is GV2025 (values as
  at 1 July 2025, effective 1 July 2026); GV2022 and GV2018 remain online.
  Rolls are detected by probing /web1/<roll>/ — a missing roll 404s.
* Both searches are reachable WITHOUT the __VIEWSTATE dance as plain GETs:
      GET /web1/<ROLL>/Results?Search=ERF,<erf_number>
      GET /web1/<ROLL>/Results?Search=ADD,<street_number>,<street_name>
  Each returns a `dgSearch` DataGrid, 10 rows per page. The ERF search lists
  every rating unit on any erf with that number CITY-WIDE (no suburb
  parameter — filtering is done client-side) — and it is INCOMPLETE: Camps
  Bay erf 1102 (27 Ingleside Rd) is missing from ERF,1102 yet found by
  ADD,27,INGLESIDE. The ADD search needs the CORE street name — the roll
  abbreviates suffixes ('BLAIR' matches 'BLAIR RD'; 'BLAIR ROAD' matches
  nothing). So this module searches by address first (usually one request,
  verified by the erf in the returned description) and falls back to the
  paginated erf search.
* Paging IS a WebForms postback: the pager row holds anchors like
  __doPostBack('dgSearch$ctl14$ctl01','') labelled with the page number; the
  next page is fetched by POSTing the current page's hidden fields with
  __EVENTTARGET set to that anchor's target, within the same session.
* Grid columns: Property Reference | Registered Description | Rating
  Category | Physical Address | Extent (m²) | Market Value | Valuation
  Reason | Reason Description | Valuation Type | Effective Date | Dispute
  Expiry | Rebates. Freehold descriptions look like "687 CAMPS BAY"
  (erf + allotment); sectional units look like "NORTHCOUNTRY - SS316/2013-45".
  Values come formatted ("R 62,000,000.00").

Ground truth: Camps Bay erf 687 = 8 BLAIR RD, 1156 m², R 62 000 000 (GV2025).

Politeness: one request per ~3s with jitter; the parsed result set for each
(roll, erf) is cached on disk under config.CACHE_DIR/gvroll/ so re-runs are
free. Do not edit other modules from here — integration happens elsewhere.
"""

from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import sys
import threading
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup, Tag

import config

PORTAL_BASE = "https://web1.capetown.gov.za/web1"

# Newest first. GV rolls run on a three-year cycle; when GV2028 goes live the
# probe picks it up automatically (the probe result is cached for 30 days).
ROLL_CANDIDATES = ("GV2028", "GV2025", "GV2022")
FALLBACK_ROLL = "GV2022"

REQUEST_DELAY = 3.0     # seconds between requests to the portal
REQUEST_JITTER = 1.5
REQUEST_TIMEOUT = 30
MAX_PAGES = 60          # safety cap: low erf numbers match big sectional schemes

CACHE_DIR = os.path.join(config.CACHE_DIR, "gvroll")
CACHE_TTL_HOURS = 24 * 90      # roll values change once every three years
ROLL_PROBE_TTL_HOURS = 24 * 30

_lock = threading.Lock()
_next_ok = 0.0
_detected_roll: str | None = None

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS valuations (
    erf_number   TEXT NOT NULL,           -- as erf_lookup records it (may be '4-RE')
    portion      TEXT NOT NULL DEFAULT '',
    suburb       TEXT,                    -- allotment/suburb as the roll states it
    address      TEXT,                    -- physical address per the roll
    use_code     TEXT,                    -- rating category, e.g. 'RESIDENTIAL'
    market_value INTEGER,                 -- Rand
    extent_m2    REAL,
    roll         TEXT NOT NULL,           -- e.g. 'GV2025'
    status       TEXT,                    -- 'ok' | 'not_found' | 'error'
    raw          TEXT,                    -- JSON: every candidate row parsed
    fetched_at   TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (erf_number, portion, roll)
);
"""


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(TABLE_SQL)


# --------------------------------------------------------------- normalising

def _norm(s: str | None) -> str:
    """Uppercase, punctuation collapsed to single spaces."""
    return re.sub(r"[^A-Z0-9]+", " ", (s or "").upper()).strip()


def _portion_key(p: str | None) -> str:
    """Canonical portion for comparison: remainder/none forms collapse to ''."""
    p = _norm(p)
    if p in ("", "0", "RE", "REM", "R E", "REMAINDER"):
        return ""
    return p.lstrip("0") or "0"


def _split_erf(erf_number: str) -> tuple[str, str]:
    """'4-RE' -> ('4', 'RE'); '687' -> ('687', ''). Digits drive the search."""
    m = re.match(r"\s*(\d+)\s*[-/]?\s*(.*)$", str(erf_number or ""))
    if not m:
        return "", ""
    return m.group(1), m.group(2).strip()


def _parse_money(text: str) -> int | None:
    """'R 62,000,000.00' / 'R 12 500 000' -> 62000000 / 12500000."""
    m = re.search(r"[\d][\d\s,]*(?:\.\d+)?", text or "")
    if not m:
        return None
    whole = m.group(0).split(".")[0]
    digits = re.sub(r"[^\d]", "", whole)
    return int(digits) if digits else None


def _parse_float(text: str) -> float | None:
    try:
        return float(re.sub(r"[^\d.]", "", text or ""))
    except ValueError:
        return None


_DESC_RE = re.compile(r"^\s*(\d+)\s*(?:/\s*(\w+))?\s+(.+)$")


def _parse_description(desc: str) -> tuple[str, str, str]:
    """'687 CAMPS BAY' -> ('687', '', 'CAMPS BAY'); '687/2 X' -> ('687','2','X').

    Sectional descriptions ('NORTHCOUNTRY - SS316/2013-45') yield ('','',desc).
    """
    d = desc or ""
    if re.search(r"SS\d+/\d+", d):
        # sectional scheme rows carry the scheme name, not an erf description
        return "", "", d.strip()
    m = _DESC_RE.match(d)
    if not m:
        return "", "", d.strip()
    return m.group(1), m.group(2) or "", m.group(3).strip()


def _suburb_matches(hint: str, row: dict) -> bool:
    """Normalised containment against the roll's description AND address.

    CoCT uses composite names ('CAMPS BAY / BAKOVEN', 'Signal Hill / Lions
    Head') on both sides, so each '/'-part of the hint is tried separately.
    An empty hint matches everything (erf-number filtering still applies).
    """
    if not (hint or "").strip():
        return True
    hay = _norm((row.get("description") or "") + " " + (row.get("address") or ""))
    for part in re.split(r"[/,]", hint):
        p = _norm(part)
        if p and p in hay:
            return True
    return False


# ------------------------------------------------------------------ HTTP

def _throttle() -> None:
    global _next_ok
    while True:
        with _lock:
            now = time.monotonic()
            if now >= _next_ok:
                _next_ok = now + REQUEST_DELAY + random.uniform(0, REQUEST_JITTER)
                return
            wait = _next_ok - now
        time.sleep(min(wait, 5.0))


def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": config.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-ZA,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    })
    return s


def _cache_path(*parts: str) -> str:
    return os.path.join(CACHE_DIR, *parts)


def _cache_read(path: str, ttl_hours: float) -> str | None:
    if not config.CACHE_ENABLED:
        return None
    try:
        if (time.time() - os.path.getmtime(path)) / 3600 > ttl_hours:
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _cache_write(path: str, body: str) -> None:
    if not config.CACHE_ENABLED:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
    except OSError:
        pass


def detect_roll(progress=print) -> str:
    """Newest valuation roll the City has online (e.g. 'GV2025'), disk-cached."""
    global _detected_roll
    if _detected_roll:
        return _detected_roll
    cached = _cache_read(_cache_path("current_roll.txt"), ROLL_PROBE_TTL_HOURS)
    if cached and cached.strip() in ROLL_CANDIDATES:
        _detected_roll = cached.strip()
        return _detected_roll
    s = _new_session()
    for roll in ROLL_CANDIDATES:
        _throttle()
        try:
            r = s.get(f"{PORTAL_BASE}/{roll}/", timeout=REQUEST_TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code == 200:
            _detected_roll = roll
            _cache_write(_cache_path("current_roll.txt"), roll)
            progress(f"[valuations] using roll {roll}")
            return roll
    progress(f"[valuations] roll probe failed, falling back to {FALLBACK_ROLL}")
    _detected_roll = FALLBACK_ROLL
    return _detected_roll


# ------------------------------------------------------------------ scraping

_HIDDEN_RE = re.compile(r'name="(__[A-Za-z0-9_]+)"[^>]*value="([^"]*)"')


def _parse_results_page(html: str) -> tuple[list[dict], dict, str]:
    """-> (rows, pager {page label -> postback target}, error message)."""
    soup = BeautifulSoup(html, "html.parser")
    err = soup.find(id="lblErrMsg")
    err_text = err.get_text(strip=True) if err else ""
    rows: list[dict] = []
    pager: dict[str, str] = {}
    grid = soup.find(id="dgSearch")
    if not isinstance(grid, Tag):
        return rows, pager, err_text or "no results grid on page"
    for tr in grid.find_all("tr"):
        if not isinstance(tr, Tag):
            continue
        if "DataGridPager" in (tr.get("class") or []):
            for a in tr.find_all("a"):
                if not isinstance(a, Tag):
                    continue
                m = re.search(r"__doPostBack\('([^']+)'", str(a.get("href", "")))
                if m:
                    pager[a.get_text(strip=True)] = m.group(1)
            continue
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) < 6 or cells[0] == "Property Reference":
            continue
        rows.append({
            "reference": cells[0],
            "description": cells[1],
            "use_code": cells[2],
            "address": cells[3],
            "extent_m2": _parse_float(cells[4]),
            "market_value": _parse_money(cells[5]),
            "valuation_type": cells[8] if len(cells) > 8 else "",
            "effective": cells[9] if len(cells) > 9 else "",
        })
    return rows, pager, err_text


def _search(roll: str, query: str, cache_name: str,
            progress=print) -> list[dict] | None:
    """All grid rows for a portal search ('ERF,687' or 'ADD,8,BLAIR').

    Served from the disk cache when possible; a live crawl walks the pager
    within one session and caches the PARSED rows (raw pages are useless for
    replay — page N is only reachable by posting page N-1's viewstate back
    inside the same session, so cached HTML could not be re-paged later).
    Returns None on network failure (a cached empty list means truly no rows).
    """
    cache = _cache_path(roll, cache_name)
    body = _cache_read(cache, CACHE_TTL_HOURS)
    if body is not None:
        try:
            return json.loads(body)
        except ValueError:
            pass

    url = f"{PORTAL_BASE}/{roll}/Results?Search={urllib.parse.quote(query, safe=',')}"
    s = _new_session()
    _throttle()
    try:
        r = s.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        progress(f"[valuations] {type(e).__name__} fetching {query}")
        return None
    if r.status_code != 200:
        progress(f"[valuations] HTTP {r.status_code} for {query}")
        return None

    html = r.text
    all_rows: list[dict] = []
    page = 1
    while True:
        rows, pager, err = _parse_results_page(html)
        if err and not rows and page == 1:
            # the portal reports "no results" style errors on lblErrMsg
            break
        all_rows.extend(rows)
        nxt = str(page + 1)
        if nxt not in pager or page >= MAX_PAGES:
            if nxt in pager:
                progress(f"[valuations] {query}: capped at "
                         f"{MAX_PAGES} pages, results truncated")
            break
        data = dict(_HIDDEN_RE.findall(html))
        data["__EVENTTARGET"] = pager[nxt]
        data["__EVENTARGUMENT"] = ""
        _throttle()
        try:
            r = s.post(url, data=data, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            progress(f"[valuations] {type(e).__name__} paging {query}")
            return None
        if r.status_code != 200:
            progress(f"[valuations] HTTP {r.status_code} paging {query}")
            return None
        html = r.text
        page += 1

    _cache_write(cache, json.dumps(all_rows))
    return all_rows


# ------------------------------------------------------------------ matching

def _pick_rows(rows: list[dict], erf_digits: str, portion: str,
               suburb_hint: str) -> list[dict]:
    """Rows for OUR property: suburb containment, then erf/portion refinement."""
    matches = [r for r in rows if _suburb_matches(suburb_hint, r)]
    # prefer rows whose registered description names exactly this erf
    exact = []
    for r in matches:
        d_erf, d_portion, d_allot = _parse_description(r["description"])
        r["desc_erf"], r["desc_portion"], r["desc_suburb"] = d_erf, d_portion, d_allot
        if d_erf == erf_digits:
            exact.append(r)
    if exact:
        matches = exact
    want = _portion_key(portion)
    with_portion = [r for r in matches
                    if _portion_key(r.get("desc_portion")) == want]
    if with_portion:
        matches = with_portion
    return matches


_STREET_SUFFIXES = {
    "ROAD", "RD", "STREET", "ST", "AVENUE", "AVE", "WAY", "CLOSE", "CL",
    "CRESCENT", "CRES", "DRIVE", "DR", "LANE", "LN", "PLACE", "PL",
    "BOULEVARD", "BLVD", "TERRACE", "SQUARE", "SQ", "STEPS", "MEWS",
}


def _addr_parts(address: str) -> tuple[str, str]:
    """'8 Blair Road' -> ('8', 'BLAIR') — the ADD search wants the CORE
    street name (the roll abbreviates suffixes, so 'BLAIR ROAD' finds
    nothing while 'BLAIR' matches 'BLAIR RD')."""
    m = re.match(r"\s*(\d+)[A-Za-z]?\s+(.+)$", address or "")
    if not m:
        return "", ""
    words = _norm(m.group(2)).split()
    if len(words) > 1 and words[-1] in _STREET_SUFFIXES:
        words = words[:-1]
    return m.group(1), " ".join(words)


def fetch_one(erf_number: str, suburb_hint: str, portion: str = "",
              roll: str | None = None, address_hint: str = "",
              progress=print) -> dict | None:
    """Fetch this erf's valuation from the live portal (or the disk cache).

    Searches by site address first when `address_hint` is given (one request,
    and the erf in the returned description verifies the match — the portal's
    ERF search is incomplete), then falls back to the paginated city-wide erf
    search. Returns a dict shaped like a `valuations` row (plus `from_cache`),
    with status 'ok' or 'not_found'; returns None only when EVERY attempted
    search failed on the network. No DB access.
    """
    roll = roll or detect_roll(progress)
    erf_digits, embedded_portion = _split_erf(erf_number)
    if not erf_digits:
        return {
            "erf_number": str(erf_number), "portion": portion or "",
            "suburb": None, "address": None, "use_code": None,
            "market_value": None, "extent_m2": None, "roll": roll,
            "status": "not_found", "from_cache": True,
            "raw": json.dumps({"note": "no numeric erf in erf_number"}),
        }
    portion = portion or embedded_portion

    matches: list[dict] = []
    attempts: list[dict] = []
    from_cache = True
    network_ok = False
    loose: list[dict] = []      # suburb-matched rows lacking our erf number

    # ---- 1. address search: cheap, and the description's erf verifies it
    number, street = _addr_parts(address_hint)
    if number and street:
        query = f"ADD,{number},{street}"
        cache_name = f"add_{number}_{re.sub(r'[^A-Z0-9]+', '_', street)}.json"
        if _cache_read(_cache_path(roll, cache_name), CACHE_TTL_HOURS) is None:
            from_cache = False
        rows = _search(roll, query, cache_name, progress)
        if rows is not None:
            network_ok = True
            picked = _pick_rows(rows, erf_digits, portion, suburb_hint)
            attempts.append({"query": query, "rows_returned": len(rows),
                             "matched": len(picked)})
            verified = [r for r in picked if r.get("desc_erf") == erf_digits]
            if verified:
                matches = verified
            elif picked:
                loose = picked  # right street+suburb, but erf not confirmed

    # ---- 2. erf search: authoritative on the erf, but incomplete and paged
    if not matches:
        query = f"ERF,{erf_digits}"
        cache_name = f"erf_{erf_digits}.json"
        if _cache_read(_cache_path(roll, cache_name), CACHE_TTL_HOURS) is None:
            from_cache = False
        rows = _search(roll, query, cache_name, progress)
        if rows is not None:
            network_ok = True
            matches = _pick_rows(rows, erf_digits, portion, suburb_hint)
            attempts.append({"query": query, "rows_returned": len(rows),
                             "matched": len(matches)})

    if not matches and loose:
        # sectional-title units carry the scheme name, not the erf, so the
        # suburb-matched address rows are the best available evidence
        matches = loose

    if not network_ok:
        return None

    raw = json.dumps({
        "roll": roll,
        "attempts": attempts,
        "suburb_hint": suburb_hint,
        "portion_hint": portion,
        "address_hint": address_hint,
        "matches": matches,
    })
    out = {
        "erf_number": str(erf_number),
        "portion": portion or "",
        "roll": roll,
        "raw": raw,
        "from_cache": from_cache,
    }
    if not matches:
        out.update({"suburb": None, "address": None, "use_code": None,
                    "market_value": None, "extent_m2": None,
                    "status": "not_found"})
        return out
    # several rows can survive (sectional units, portions): freehold rows
    # (description carries the erf) beat scheme units; then largest extent.
    best = sorted(
        matches,
        key=lambda r: (bool(r.get("desc_erf")), r.get("extent_m2") or 0.0),
        reverse=True,
    )[0]
    out.update({
        "suburb": best.get("desc_suburb") or suburb_hint or None,
        "address": best.get("address"),
        "use_code": best.get("use_code"),
        "market_value": best.get("market_value"),
        "extent_m2": best.get("extent_m2"),
        "status": "ok",
    })
    return out


# ------------------------------------------------------------------ storage

_COLUMNS = ("erf_number", "portion", "suburb", "address", "use_code",
            "market_value", "extent_m2", "roll", "status", "raw")


def _store(conn: sqlite3.Connection, row: dict) -> None:
    vals = {c: row.get(c) for c in _COLUMNS}
    vals["portion"] = vals.get("portion") or ""
    conn.execute(
        f"""INSERT INTO valuations ({', '.join(_COLUMNS)}, fetched_at)
            VALUES ({', '.join(':' + c for c in _COLUMNS)}, datetime('now'))
            ON CONFLICT(erf_number, portion, roll) DO UPDATE SET
                {', '.join(f'{c} = excluded.{c}' for c in _COLUMNS[2:])},
                fetched_at = datetime('now')""",
        vals,
    )


# ------------------------------------------------------------------ public

def resolve_all(conn: sqlite3.Connection, force: bool = False,
                progress=print) -> dict:
    """Fetch the GV valuation for every resolved erf in erf_lookup.

    Skips (erf, portion) pairs already valued on the current roll unless
    `force`; rows previously stored as 'error' are always retried.
    Returns {fetched, cached, not_found, errors}.
    """
    ensure_table(conn)
    roll = detect_roll(progress)
    counts = {"fetched": 0, "cached": 0, "not_found": 0, "errors": 0}

    targets = conn.execute("""
        SELECT erf_number, COALESCE(portion, '') AS portion,
               MAX(COALESCE(official_suburb, '')) AS suburb,
               MAX(COALESCE(official_address, '')) AS address
        FROM erf_lookup
        WHERE erf_number IS NOT NULL AND TRIM(erf_number) <> ''
          AND status IN ('ok', 'confirmed', 'check')
        GROUP BY erf_number, COALESCE(portion, '')
    """).fetchall()
    progress(f"[valuations] {len(targets)} resolved erven to value ({roll})")

    for t in targets:
        erf, portion, suburb = t["erf_number"], t["portion"], t["suburb"]
        if not force:
            existing = conn.execute(
                "SELECT status FROM valuations WHERE erf_number = ?"
                " AND portion = ? AND roll = ?", (erf, portion, roll),
            ).fetchone()
            if existing and existing["status"] in ("ok", "not_found"):
                counts["cached"] += 1
                continue
        res = fetch_one(erf, suburb, portion, roll=roll,
                        address_hint=t["address"], progress=progress)
        if res is None:
            counts["errors"] += 1
            _store(conn, {
                "erf_number": erf, "portion": portion, "roll": roll,
                "status": "error",
                "raw": json.dumps({"note": "network/portal failure — rerun "
                                           "resolve_all to retry"}),
            })
            conn.commit()
            continue
        from_cache = res.pop("from_cache", False)
        _store(conn, res)
        conn.commit()
        if res["status"] == "ok":
            counts["cached" if from_cache else "fetched"] += 1
            progress(f"[valuations] erf {erf} {suburb}: "
                     f"R {res['market_value']:,} ({res['address']})")
        else:
            counts["not_found"] += 1
            progress(f"[valuations] erf {erf} {suburb}: no match on the roll")
    progress(f"[valuations] done {counts}")
    return counts


def get(conn: sqlite3.Connection, erf_number: str, portion: str = "") -> dict | None:
    """The newest-roll valuation row for this erf, as a dict."""
    ensure_table(conn)
    row = conn.execute(
        "SELECT * FROM valuations WHERE erf_number = ? AND portion = ?"
        " ORDER BY roll DESC, fetched_at DESC LIMIT 1",
        (str(erf_number), portion or ""),
    ).fetchone()
    return dict(row) if row else None


def _slugish(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def for_groups(conn: sqlite3.Connection) -> dict[str, dict]:
    """erf_lookup.group_id -> newest successful valuation dict (for reports).

    Erf numbers repeat across towns (Langebaan erf 800 vs Camps Bay erf 800)
    and the CoCT and SBM rolls share this table, so when several 'ok' rows
    carry the same (erf, portion) the group's official_suburb picks the row;
    an ambiguous key with no suburb match yields nothing rather than the
    wrong town's value.
    """
    ensure_table(conn)
    by_erf: dict[tuple[str, str], list[dict]] = {}
    for row in conn.execute(
            # sub-R50k values are municipal-nominal (open space, roads at
            # R1,000) — real anchors only
            "SELECT * FROM valuations WHERE status = 'ok'"
            " AND COALESCE(market_value, 0) >= 50000"
            " ORDER BY roll ASC, fetched_at ASC"):
        by_erf.setdefault(
            (row["erf_number"], row["portion"] or ""), []).append(dict(row))
    out: dict[str, dict] = {}
    for r in conn.execute("""
            SELECT group_id, erf_number, COALESCE(portion, '') AS portion,
                   COALESCE(official_suburb, '') AS official_suburb
            FROM erf_lookup
            WHERE group_id IS NOT NULL AND erf_number IS NOT NULL
              AND status IN ('ok', 'confirmed', 'check')"""):
        cands = by_erf.get((r["erf_number"], r["portion"]))
        if not cands:
            continue
        if len(cands) == 1:
            out[str(r["group_id"])] = cands[-1]
            continue
        hint = _slugish(r["official_suburb"])
        matched = [v for v in cands if hint and _slugish(v["suburb"]) and
                   (_slugish(v["suburb"]) in hint or hint in _slugish(v["suburb"]))]
        if matched:
            out[str(r["group_id"])] = matched[-1]
    return out


# ------------------------------------------------------------------ CLI

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # usage: valuations.py <erf> [suburb] [portion] [street address]
        result = fetch_one(
            sys.argv[1],
            sys.argv[2] if len(sys.argv) > 2 else "",
            sys.argv[3] if len(sys.argv) > 3 else "",
            address_hint=sys.argv[4] if len(sys.argv) > 4 else "",
        )
        print(json.dumps(result, indent=2))
    else:
        import db
        with db.connect() as conn:
            resolve_all(conn)
