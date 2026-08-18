"""Build spreadsheet rows and put them on the clipboard.

Excel and Google Sheets both accept tab-separated text on the clipboard and
spread it across columns on paste — so "add this property to my sheet" needs
no API, no service account and no OAuth: build a TSV row, copy it, press
Cmd+V on the row you want it in.

Two ways to use it:

    # a property already in the database, by group id or listing key
    python main.py row 412
    python main.py row property24:114992922

    # arbitrary fields you supply yourself
    python main.py row --set address="12 Oak Ave" --set price=4500000

Columns are configurable — COLUMNS below is the default order, and
`--cols` overrides it per call. A field with no value becomes an empty cell,
so the row always lines up with the same columns in the sheet.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

# Default column order. Rename/reorder freely — `key` is looked up in the
# property record (or in whatever --set fields you pass), `header` is what
# the column is called when you ask for a header row.
COLUMNS: list[tuple[str, str]] = [
    ("suburb",          "Suburb"),
    ("title",           "Title"),
    ("street_address",  "Address"),
    ("price_zar",       "Price"),
    ("bedrooms",        "Beds"),
    ("bathrooms",       "Baths"),
    ("erf_size_m2",     "Erf m²"),
    ("floor_size_m2",   "Floor m²"),
    ("agency",          "Agency"),
    ("agent_name",      "Agent"),
    ("erf_number",      "Erf No"),
    ("prospect_score",  "Score"),
    ("tier",            "Tier"),
    ("url",             "Link"),
]


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _clean(value) -> str:
    """One spreadsheet cell: no tabs or newlines, they would split the row."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value)
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def tsv_row(fields: dict, columns: list[tuple[str, str]] | None = None) -> str:
    """A single tab-separated line, in column order."""
    cols = columns or COLUMNS
    return "\t".join(_clean(fields.get(key)) for key, _ in cols)


def tsv_header(columns: list[tuple[str, str]] | None = None) -> str:
    return "\t".join(header for _, header in (columns or COLUMNS))


def to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard. True if it landed."""
    if sys.platform == "darwin":
        cmd = ["pbcopy"]
    elif sys.platform == "win32":
        cmd = ["clip"]
    elif shutil.which("xclip"):
        cmd = ["xclip", "-selection", "clipboard"]
    elif shutil.which("xsel"):
        cmd = ["xsel", "--clipboard", "--input"]
    else:
        return False
    try:
        subprocess.run(cmd, input=text.encode("utf-8"), check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def parse_columns(spec: str) -> list[tuple[str, str]]:
    """'price,beds,url' -> columns, reusing known headers where they exist."""
    known = dict(COLUMNS)
    out = []
    for key in (s.strip() for s in spec.split(",")):
        if key:
            out.append((key, known.get(key, key.replace("_", " ").title())))
    return out


def fields_for(conn, ident: str) -> dict | None:
    """Every column's worth of data for one property.

    `ident` is either a group id (as shown in the dashboard) or a listing
    key like 'property24:114992922'.

    A group's portals each hold a different slice of the truth: one carries
    89 photos but no title or bathroom count, another carries the street
    address, a third the fullest description. Picking a single "best"
    listing therefore exports a half-empty row. So the richest listing seeds
    the record and every remaining blank is filled from the other members —
    the row that lands in the sheet is as complete as the group can make it.
    """
    q = """
    SELECT l.*, s.prospect_score, s.tier, s.luxury_fit, s.pitch_angle,
           s.open_mandate_confidence, e.erf_number, e.official_address,
           g.group_id, g.agency_count
    FROM listings l
    LEFT JOIN scores s ON s.listing_key = l.listing_key
    LEFT JOIN erf_lookup e ON e.listing_key = l.listing_key
    LEFT JOIN property_groups g ON g.listing_key = l.listing_key
    WHERE %s
    """
    if ident.isdigit():
        rows = conn.execute(q % "g.group_id = ?", (int(ident),)).fetchall()
    else:
        rows = conn.execute(q % "l.listing_key = ?", (ident,)).fetchall()
    if not rows:
        return None

    # Richest first: a real description says more about completeness than a
    # photo count does (a portal can carry 89 images and no text at all).
    ranked = sorted(rows, key=lambda r: (len(r["description"] or ""),
                                         r["photo_count"] or 0), reverse=True)
    rec = dict(ranked[0])
    for other in ranked[1:]:
        for key in other.keys():
            if _blank(rec.get(key)) and not _blank(other[key]):
                rec[key] = other[key]

    # The cadastre's address is the verified one; fall back to the portal's.
    if not _blank(rec.get("official_address")):
        rec["street_address"] = rec["official_address"]
    rec["agencies"] = ", ".join(sorted(
        {r["agency"].strip() for r in rows if r["agency"] and r["agency"].strip()}))
    return rec
