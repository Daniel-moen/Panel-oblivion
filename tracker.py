"""Oblivion's manual prospecting tracker (xlsx) -> DB, and the taste profile.

The team keeps a spreadsheet of properties they've actually pursued
(OBLVN.PROSPECTING.xlsx: P24 links + a PROSPECTED=Y column). Imported it
steers the engine two ways:
- already-prospected listings are excluded from reports/the dashboard
- the full history becomes a "revealed preference" profile injected into
  the AI scoring prompt
"""

import re
import sqlite3
from collections import Counter

LISTING_URL_RE = re.compile(r"property24\.com/for-sale/([a-z0-9-]+)/.*/(\d+)(?:\?|$)")


def import_xlsx(conn: sqlite3.Connection, path: str) -> dict:
    import openpyxl

    wb = openpyxl.load_workbook(path)
    rows, prospected_count = 0, 0
    for ws in wb.worksheets:
        for row in ws.iter_rows(min_row=3):
            cells = {c.column_letter: c for c in row}
            b = cells.get("B")
            if b is None or b.hyperlink is None:
                continue
            m = LISTING_URL_RE.search(b.hyperlink.target or "")
            if not m:
                continue
            slug, listing_number = m.group(1), m.group(2)
            title = str(b.value or "").strip()
            if title.startswith("http"):
                title = ""
            h = cells.get("H")
            h_val = str(h.value or "") if h is not None else ""
            prospected = 1 if h_val.strip().upper() == "Y" else 0
            conn.execute(
                """INSERT INTO tracker (listing_number, url, title, suburb_slug, prospected, sheet)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(listing_number) DO UPDATE SET
                       prospected = MAX(tracker.prospected, excluded.prospected),
                       title = CASE WHEN excluded.title != '' THEN excluded.title ELSE tracker.title END""",
                (listing_number, b.hyperlink.target, title, slug, prospected, ws.title),
            )
            rows += 1
            prospected_count += prospected
    total = conn.execute("SELECT COUNT(*), SUM(prospected) FROM tracker").fetchone()
    return {"rows_read": rows, "unique": total[0], "prospected": total[1] or 0}


def _classify_title(title: str) -> tuple[str | None, int | None]:
    """('House', 6) from '6 Bedroom House for sale in Camps Bay - ...'."""
    beds_m = re.match(r"(\d+) Bedroom", title)
    beds = int(beds_m.group(1)) if beds_m else None
    for ptype in ("Townhouse", "House", "Apartment", "Vacant land", "Farm", "Commercial"):
        if ptype.lower() in title.lower():
            return ptype, beds
    return None, beds


def taste_profile(conn: sqlite3.Connection) -> str | None:
    """Compact revealed-preference summary of the tracker for the AI prompt."""
    rows = conn.execute("SELECT title, suburb_slug FROM tracker").fetchall()
    if not rows:
        return None
    suburbs: Counter[str] = Counter()
    types: Counter[str] = Counter()
    house_beds: list[int] = []
    for r in rows:
        title = r["title"] or ""
        in_m = re.search(r" in (.+?)(?: - |$)", title)
        suburb = in_m.group(1) if in_m else r["suburb_slug"].replace("-", " ").title()
        suburbs[suburb] += 1
        ptype, beds = _classify_title(title)
        if ptype:
            types[ptype] += 1
            if ptype == "House" and beds:
                house_beds.append(beds)
    suburb_str = ", ".join(f"{s} ({n})" for s, n in suburbs.most_common(12))
    type_str = ", ".join(f"{t} ({n})" for t, n in types.most_common())
    # a spread of concrete picks (varied types/areas) as few-shot exemplars
    examples: list[str] = []
    seen_kinds: set[tuple] = set()
    for r in rows:
        title = (r["title"] or "").split(" - ")[0].strip()
        kind = _classify_title(title)
        if title and kind not in seen_kinds:
            seen_kinds.add(kind)
            examples.append(title)
        if len(examples) >= 10:
            break
    example_str = "; ".join(examples)
    beds_str = ""
    if house_beds:
        beds_str = (f" Houses they pursue are large: {min(house_beds)}-{max(house_beds)} "
                    f"bedrooms, typically {sorted(house_beds)[len(house_beds) // 2]}+.")
    return (
        f"\n\nOblivion's own prospecting history ({len(rows)} properties they chose "
        f"to pursue, from their tracker) — treat this as revealed preference. "
        f"Areas worked, by frequency: {suburb_str}. "
        f"Property mix: {type_str}.{beds_str} "
        f"Actual picks from their tracker: {example_str}. "
        f"A property resembling this history (same area calibre, same type, "
        f"similar scale) deserves a higher luxury_fit and prospect_score; a "
        f"property unlike anything here needs other strong signals to rank hot."
    )
