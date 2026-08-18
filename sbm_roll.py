"""Saldanha Bay Municipality General Valuation roll (PDF) provider.

The City of Cape Town roll (valuations.py) only covers the metro; the West
Coast portfolio (Langebaan, Saldanha, Paternoster, St Helena Bay, Vredenburg,
Jacobsbaai) falls under Saldanha Bay Municipality, which publishes its GV2025
roll (values as at 2025-07-01, in force since 2026-07-01) as per-town PDFs on
sbm.gov.za — erf, portion, category, physical address, extent, market value.

Parsing is positional, not textual: a line like "Hoofstraat 96 1 487 m²" is
ambiguous as text (street number 96 vs extent 1 487) but the PDF lays the
columns out at fixed x-positions, so words are bucketed by the x-coordinates
of the page's own header row. The supplementary roll amends the main roll and
is parsed second so its rows override.

Rows are stored in the shared `valuations` table under roll 'SBM-GV2025',
keyed exactly like the CoCT rows so valuations.for_groups() and cma._gv_value
pick them up. Sectional-title parents appear on the main roll with value 0
("See SS <scheme>") — stored as-is; a zero market_value is already treated as
"no anchor" everywhere. Unit-level sectional matching needs unit numbers the
portals don't publish, so it is out of scope here.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time

import requests

import config
import valuations

ROLL = "SBM-GV2025"
BASE = ("https://sbm.gov.za/wp-content/uploads/Pages/Valuations/"
        "Valuation_Roll_2025/")
SUPP = "1st_Supplementary_Valuation_Roll_2025/"

# town slug (config.SUBURBS[slug]['town']) -> roll PDFs, main roll first.
TOWN_FILES = {
    "langebaan": ["Langebaan.pdf"],
    "saldanha": ["Saldanha.pdf", "Saldanha-Leaseholds.pdf"],
    "vredenburg": ["Vredenburg.pdf"],
    "paternoster": ["Paternoster.pdf"],
    "st-helena-bay": ["St-Helena-Bay.pdf", "St-Helena-Bay-Harbour-Sites.pdf"],
    "jacobsbaai": ["Jacobsbaai.pdf", "Jacobsbaai-Coastal-Plot.pdf"],
}
# Supplementary-roll files that exist on the portal (probing 404s is rude).
SUPP_FILES = {"Langebaan.pdf", "Saldanha.pdf", "Vredenburg.pdf",
              "Paternoster.pdf", "St-Helena-Bay.pdf", "Jacobsbaai.pdf"}

# Listings carry portal sub-suburb slugs (myburgh-park, country-club, …) that
# config.SUBURBS doesn't know, so towns are resolved geographically from the
# parcel centroid instead — the SBM towns are kilometres apart.
TOWN_CENTRES = {
    "langebaan": (-33.092, 18.033),
    "saldanha": (-33.011, 17.944),
    "vredenburg": (-32.907, 17.989),
    "paternoster": (-32.809, 17.881),
    "st-helena-bay": (-32.757, 18.028),
    "jacobsbaai": (-32.971, 17.883),
}
TOWN_RADIUS_KM = 20.0


def _town_for(lat: float | None, lng: float | None) -> str | None:
    if lat is None or lng is None:
        return None
    best, best_km = None, TOWN_RADIUS_KM
    for town, (tlat, tlng) in TOWN_CENTRES.items():
        km = (((lat - tlat) * 111.0) ** 2 +
              ((lng - tlng) * 93.0) ** 2) ** 0.5   # ~km at 33°S
        if km < best_km:
            best, best_km = town, km
    return best

CACHE_DIR = os.path.join(config.CACHE_DIR, "sbmroll")
CACHE_TTL_HOURS = 24 * 90       # rolls change on a multi-year cycle
REQUEST_TIMEOUT = 60


# ------------------------------------------------------------------ download

def _cache_fresh(path: str) -> bool:
    try:
        return (time.time() - os.path.getmtime(path)) < CACHE_TTL_HOURS * 3600
    except OSError:
        return False


def _download(rel_name: str, progress=print) -> str | None:
    """Fetch one roll PDF into the cache; returns the local path or None."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    local = os.path.join(CACHE_DIR, rel_name.replace("/", "__"))
    if _cache_fresh(local):
        return local
    url = BASE + rel_name
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 404:
            progress(f"[sbm] {rel_name}: not on the portal (404)")
            return None
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            progress(f"[sbm] {rel_name}: not a PDF, skipping")
            return None
    except requests.RequestException as e:
        progress(f"[sbm] {rel_name}: download failed ({e})")
        return None
    with open(local, "wb") as f:
        f.write(r.content)
    return local


# ------------------------------------------------------------------ parsing

def _group_lines(words: list[dict]) -> list[list[dict]]:
    lines: dict[int, list[dict]] = {}
    for w in words:
        lines.setdefault(round(w["top"]), []).append(w)
    return [sorted(ws, key=lambda w: w["x0"]) for _, ws in sorted(lines.items())]


def _header_bounds(line: list[dict]) -> dict | None:
    """Column x-boundaries from the roll's own header row.

    Main-roll header:  Erf No | Portion | Category | Physical Address |
                       Extent | Value | Other Particulars
    ('Portion' renders on its own line just below, so it may be absent here —
    its boundary is anchored off 'Category' instead.)
    """
    xs = {w["text"]: w for w in line}
    if "Extent" not in xs or "Value" not in xs or "Category" not in xs:
        return None
    return {
        # apportionment continuation lines leave the erf column empty, so a
        # word is only an erf number if it sits under the 'Erf No' header
        "erf_max": (xs.get("Erf") or {"x1": xs["Category"]["x0"] - 40})["x1"]
                   + 20,
        "category": xs["Category"]["x0"] - 8,
        "address": xs["Category"]["x1"] + 5,
        "extent": xs["Extent"]["x0"] - 25,
        # value numbers are right-aligned; anchor between the m² unit and the
        # header word rather than on the header's own x0
        "value": (xs["Extent"]["x1"] + xs["Value"]["x0"]) / 2 + 10,
        "note": (xs.get("Other") or {"x0": 9999})["x0"] - 10,
    }


_NUM = re.compile(r"^\d+$")


def _parse_pdf(path: str, progress=print) -> list[dict]:
    """Every parcel row in one roll PDF (main-roll layout only)."""
    import pdfplumber

    rows: list[dict] = []
    area = None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            lines = _group_lines(page.extract_words())
            bounds = None
            for line in lines:
                text = " ".join(w["text"] for w in line)
                m = re.match(r"Geographical Area\s*:\s*(.+)", text)
                if m:
                    area = m.group(1).strip()
                    continue
                if bounds is None:
                    bounds = _header_bounds(line)
                    if bounds is not None:
                        continue
                if bounds is None or area is None:
                    continue
                # data line: starts with erf digits left of the category col
                first = line[0]
                if not _NUM.match(first["text"]) or \
                        first["x0"] >= bounds["erf_max"]:
                    continue
                erf, portion = first["text"], ""
                cat, addr, extent, value, note = "", [], [], [], []
                for w in line[1:]:
                    x = w["x0"]
                    if x >= bounds["note"]:
                        note.append(w["text"])
                    elif x >= bounds["value"]:
                        value.append(w["text"])
                    elif x >= bounds["extent"]:
                        extent.append(w["text"])
                    elif x >= bounds["address"]:
                        addr.append(w["text"])
                    elif x >= bounds["category"]:
                        cat = (cat + " " + w["text"]).strip()
                    elif _NUM.match(w["text"]):
                        portion = w["text"]
                # extent is "1 487 m²" or "5.5997 Ha" (farm parcels)
                unit = extent.pop() if extent and extent[-1] in ("m²", "Ha") \
                    else "m²"
                ext = "".join(extent)
                ext_m2 = None
                if re.match(r"^\d+(\.\d+)?$", ext):
                    ext_m2 = float(ext) * (10_000 if unit == "Ha" else 1)
                # 'Note :-' text can start left of the Other Particulars
                # header — keep only the leading digit run as the value
                digits = []
                for tok in value:
                    if not _NUM.match(tok):
                        note = value[len(digits):] + note
                        break
                    digits.append(tok)
                val = "".join(digits)
                rows.append({
                    "area": area,
                    "erf": erf,
                    "portion": portion,
                    "category": cat,
                    "address": " ".join(addr),
                    "extent_m2": ext_m2,
                    "value": int(val) if _NUM.match(val) else None,
                    "note": " ".join(note),
                })
    progress(f"[sbm] parsed {len(rows)} parcels from "
             f"{os.path.basename(path)}")
    return rows


def _load_file(rel_name: str, progress=print) -> list[dict]:
    """Parsed rows for one roll PDF, cached as JSON beside the PDF."""
    local = _download(rel_name, progress)
    if local is None:
        return []
    cache = local + ".json"
    if _cache_fresh(cache) and os.path.getmtime(cache) >= os.path.getmtime(local):
        with open(cache) as f:
            return json.load(f)
    rows = _parse_pdf(local, progress)
    with open(cache, "w") as f:
        json.dump(rows, f)
    return rows


def _portion_key(p: str | None) -> str:
    p = (p or "").strip().lstrip("0")
    return p          # roll portion '0' == erf_lookup '' (whole erf)


def load_town(town: str, progress=print) -> dict[tuple[str, str], dict]:
    """(erf digits, portion) -> roll row for one town, supplementary last so
    its amendments override the main roll."""
    out: dict[tuple[str, str], dict] = {}
    names = TOWN_FILES.get(town, [])
    for rel in names + [SUPP + n for n in names if n in SUPP_FILES]:
        for row in _load_file(rel, progress):
            out[(row["erf"].lstrip("0"), _portion_key(row["portion"]))] = row
    return out


# ------------------------------------------------------------------ resolve

def resolve_all(conn: sqlite3.Connection, force: bool = False,
                progress=print) -> dict:
    """Value every resolved erf that falls inside Saldanha Bay Municipality.

    Same contract as valuations.resolve_all: skips pairs already valued on
    this roll unless `force`. Returns {matched, cached, not_found, towns}.
    """
    valuations.ensure_table(conn)
    counts = {"matched": 0, "cached": 0, "not_found": 0, "towns": 0}

    targets = conn.execute("""
        SELECT e.erf_number, COALESCE(e.portion, '') AS portion,
               MAX(e.latitude) AS lat, MAX(e.longitude) AS lng,
               MAX(COALESCE(e.parcel_area_m2, 0)) AS parcel_area_m2
        FROM erf_lookup e
        WHERE e.erf_number IS NOT NULL AND TRIM(e.erf_number) <> ''
          AND e.status IN ('ok', 'confirmed', 'check')
        GROUP BY e.erf_number, COALESCE(e.portion, '')
    """).fetchall()

    by_town: dict[str, list] = {}
    for t in targets:
        town = _town_for(t["lat"], t["lng"])
        if town in TOWN_FILES:
            by_town.setdefault(town, []).append(t)
    if not by_town:
        progress("[sbm] no resolved erven inside Saldanha Bay Municipality")
        return counts

    for town, rows in sorted(by_town.items()):
        roll_rows = load_town(town, progress)
        if not roll_rows:
            progress(f"[sbm] {town}: no roll data — skipping "
                     f"{len(rows)} erven")
            continue
        counts["towns"] += 1
        for t in rows:
            erf_digits = re.sub(r"\D", "", t["erf_number"]).lstrip("0")
            key = (t["erf_number"], t["portion"])
            if not force:
                existing = conn.execute(
                    "SELECT status FROM valuations WHERE erf_number = ?"
                    " AND portion = ? AND roll = ?", (*key, ROLL)).fetchone()
                if existing and existing["status"] in ("ok", "not_found"):
                    counts["cached"] += 1
                    continue
            row = roll_rows.get((erf_digits, _portion_key(t["portion"])))
            store = {
                "erf_number": t["erf_number"], "portion": t["portion"],
                "roll": ROLL,
            }
            # wrong-town guard: the roll and the cadastre both quote the
            # SG parcel extent, so a big mismatch means this erf number
            # belongs to a different township than the one we loaded
            if row is not None and row["extent_m2"] and t["parcel_area_m2"]:
                ratio = row["extent_m2"] / t["parcel_area_m2"]
                if not (0.7 <= ratio <= 1.4):
                    progress(f"[sbm] erf {t['erf_number']} {town}: extent "
                             f"mismatch (roll {row['extent_m2']:.0f} vs "
                             f"cadastre {t['parcel_area_m2']:.0f} m²) — "
                             "skipping")
                    row = None
            if row is None:
                store.update({"status": "not_found",
                              "raw": json.dumps({"town": town})})
                counts["not_found"] += 1
                progress(f"[sbm] erf {t['erf_number']} {town}: "
                         "no match on the roll")
            else:
                prior = conn.execute(
                    "SELECT suburb FROM valuations WHERE erf_number = ?"
                    " AND portion = ? AND roll = ?", (*key, ROLL)).fetchone()
                if prior and prior["suburb"] and prior["suburb"] != row["area"]:
                    # same erf number in two SBM towns we both track — refuse
                    # to overwrite rather than serve the wrong town's value
                    progress(f"[sbm] erf {t['erf_number']}: already stored "
                             f"for {prior['suburb']}, skipping {row['area']}")
                    continue
                store.update({
                    "suburb": row["area"], "address": row["address"],
                    "use_code": row["category"],
                    "market_value": row["value"],
                    "extent_m2": row["extent_m2"],
                    "status": "ok", "raw": json.dumps(row),
                })
                counts["matched"] += 1
                v = row["value"]
                progress(f"[sbm] erf {t['erf_number']} {row['area']}: "
                         f"R {v:,}" if v else
                         f"[sbm] erf {t['erf_number']} {row['area']}: "
                         f"value 0 ({row['note'] or 'no anchor'})")
            valuations._store(conn, store)
        conn.commit()
    progress(f"[sbm] done {counts}")
    return counts


if __name__ == "__main__":
    import db
    with db.connect() as conn:
        resolve_all(conn)
