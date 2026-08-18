"""HTML for the Oblivion CMA pages — /cma (index) and /cma/<group_id> (report).

All new markup lives here so webapp.py only gains thin routes; the main
dashboard page is untouched. Styling mirrors the dashboard's dark aesthetic
(#0d0d0f / #e8c47a) on screen; @media print flips to an ink-friendly A4
layout and hides everything marked internal-only (pitch angle, owner
details, nav), so "print to PDF" yields a client-ready document.
"""

from __future__ import annotations

import html
import json
import sqlite3
import statistics
from datetime import datetime, timezone

import cma
import config
import lifecycle
import owners
import valuations
from sources.base import canonical_agency

DISCLAIMER = ("Comparative market analysis for guidance only — not a formal "
              "valuation; only a registered professional valuer may issue a "
              "valuation (SA Property Valuers Profession Act).")

_TIER_ORDER = {"hot": 0, "warm": 1, "cold": 2}

# Same palette the prospect report uses, so a mandate verdict reads identically
# wherever it appears.
_MANDATE_COLORS = {
    "open": "#1e8449", "probably_open": "#148f77", "unknown": "#5d5d66",
    "probably_sole": "#a04000", "sole": "#922b21",
}

_PROOF_FRESH_HOURS = getattr(config, "PROOF_FRESH_HOURS", 72)


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _fmt_r(v) -> str:
    if not v:
        return "POA"
    return "R " + f"{int(v):,}".replace(",", " ")


def _fmt_num(v, suffix="") -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return f"{v}{suffix}"


def _fmt_area(v) -> str:
    """22 ha reads as '2.2 ha', not '22 000 m²' — farm sizes stay in the
    unit an agent would say out loud."""
    if v is None:
        return "—"
    if v >= 10_000:
        ha = v / 10_000
        return f"{ha:.1f}".rstrip("0").rstrip(".") + " ha"
    return f"{_fmt_num(v)} m²"


def _sat_url(lat, lng) -> str:
    # same pattern the dashboard uses: satellite view at the parcel centroid
    return (f"https://www.google.com/maps/place/{lat},{lng}"
            f"/@{lat},{lng},110m/data=!3m1!1e3")


def _rget(row, key, default=None):
    """sqlite3.Row lookup that tolerates a column the DB doesn't have yet —
    the same forgiveness the rest of the engine gives optional tables."""
    if row is None:
        return default
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def _utcnow() -> datetime:
    """Naive UTC, comparable to SQLite's datetime('now') text."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _age_hours(ts) -> float | None:
    d = cma._parse_date(ts)
    if d is None:
        return None
    return max(0.0, (_utcnow() - d).total_seconds() / 3600.0)


def _age_label(hours: float | None) -> str:
    """Hours while the sighting is arguably still 'live', days after that."""
    if hours is None:
        return "—"
    return f"{hours:.0f}h" if hours < 48 else f"{hours / 24.0:.0f}d"


def _days_since(ts) -> int | None:
    h = _age_hours(ts)
    return None if h is None else int(h // 24)


def _pool_label(v) -> str:
    """`pool` is a TEXT column: mostly '1'/'0', occasionally prose
    ('Communal Pool', 'Heated') — keep the prose, translate the flags."""
    if v is None:
        return "—"
    s = str(v).strip()
    if s == "" or s.lower() in ("0", "false", "no", "none"):
        return "—"
    if s.lower() in ("1", "true", "yes"):
        return "yes"
    return s


def _money_or_dash(v) -> str:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return "—"
    return "—" if n <= 0 else "R " + f"{n:,}".replace(",", " ")


def _pct(v, digits=1) -> str:
    return "—" if v is None else f"{v:.{digits}f}%"


def _chip(text: str, cls: str = "") -> str:
    return f'<span class="chip {cls}">{text}</span>'


def _sparkline(points: list[tuple[datetime, float]], width: int = 300,
               height: int = 58, color: str = "#e8c47a") -> str:
    """Inline SVG price line — no libraries, prints fine, scales to the card.

    points: chronological [(datetime, value)]. Fewer than two distinct
    observations is not a trend, so nothing is drawn.
    """
    pts = [(d, float(v)) for d, v in points if d and v]
    if len(pts) < 2:
        return ""
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or (hi or 1) * 0.02
    t0, t1 = pts[0][0], pts[-1][0]
    tspan = (t1 - t0).total_seconds()
    pad = 5

    def xy(i, d, v):
        frac = ((d - t0).total_seconds() / tspan) if tspan > 0 \
            else (i / max(len(pts) - 1, 1))
        x = pad + frac * (width - 2 * pad)
        y = height - pad - ((v - lo) / span) * (height - 2 * pad)
        return round(x, 1), round(y, 1)

    coords = [xy(i, d, v) for i, (d, v) in enumerate(pts)]
    line = " ".join(f"{x},{y}" for x, y in coords)
    area = (f"{coords[0][0]},{height - pad} " + line
            + f" {coords[-1][0]},{height - pad}")
    dots = "".join(
        f'<circle cx="{x}" cy="{y}" r="2.4" fill="{color}"/>'
        for x, y in (coords[0], coords[-1]))
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'preserveAspectRatio="none" role="img" aria-label="price history" '
        f'style="max-width:{width}px;display:block">'
        f'<polygon points="{area}" fill="{color}" opacity=".12"/>'
        f'<polyline points="{line}" fill="none" stroke="{color}" '
        f'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>'
        f'{dots}</svg>')


# ---------------------------------------------------------------- shared CSS

_CSS = """
 :root { color-scheme: dark; }
 * { box-sizing: border-box; }
 body { font-family:-apple-system,BlinkMacSystemFont,Helvetica,sans-serif; margin:0;
        background:#0d0d0f; color:#e8e8e8; }
 header.bar { padding:1rem 1.6rem; border-bottom:1px solid #26262b; display:flex;
        align-items:baseline; gap:1rem; flex-wrap:wrap; }
 header.bar h1 { font-weight:300; letter-spacing:.25em; font-size:1rem; margin:0; }
 header.bar .sub { color:#777; font-size:.72rem; letter-spacing:.08em; }
 nav.crumbs { padding:.6rem 1.6rem; font-size:.75rem; color:#8b8b93;
        border-bottom:1px solid #1a1a1f; }
 main { padding:1.2rem 1.6rem 4rem; max-width:1180px; margin:0 auto; }
 a { color:#e8c47a; text-decoration:none; }
 a:hover { text-decoration:underline; }
 h2 { font-weight:350; letter-spacing:.14em; font-size:.82rem; text-transform:uppercase;
      color:#999; margin:1.9rem 0 .7rem; border-bottom:1px solid #26262b; padding-bottom:.35rem; }
 table { border-collapse:collapse; width:100%; }
 th,td { text-align:left; padding:.5rem .6rem; border-bottom:1px solid #222;
         vertical-align:top; font-size:.82rem; }
 th { color:#888; font-size:.63rem; text-transform:uppercase; letter-spacing:.12em; }
 .tier { color:#fff; font-size:.58rem; padding:2px 6px; border-radius:3px; letter-spacing:.06em; }
 .hot{background:#c0392b}.warm{background:#d68910}.cold{background:#555}
 .price { white-space:nowrap; font-weight:600; }
 .meta { color:#8b8b93; font-size:.7rem; margin-top:.15rem; }
 .badge { background:#1e8449; color:#fff; padding:2px 6px; border-radius:3px; font-size:.62rem; }
 .badge.gray { background:#3a3a42; }
 .badge.blue { background:#2e5c7a; }
 .disclaimer { color:#b09256; font-size:.7rem; border:1px solid #3a3320; background:#16140e;
        border-radius:6px; padding:.55rem .8rem; margin:.8rem 0; line-height:1.45; }
 .stats { display:flex; gap:1.4rem; flex-wrap:wrap; margin:.6rem 0 .4rem; }
 .stat b { display:block; font-size:1.15rem; font-weight:650; color:#e8c47a; }
 .stat span { font-size:.6rem; color:#888; text-transform:uppercase; letter-spacing:.12em; }
 .internal { border:1px dashed #5a2f2a; border-radius:8px; padding:.9rem 1.1rem;
        margin-top:1.6rem; background:#141013; }
 .internal .tag { color:#b4645a; font-size:.62rem; text-transform:uppercase;
        letter-spacing:.16em; margin-bottom:.5rem; display:block; }
 input, select, textarea, button { background:#1a1a1f; color:#e8e8e8; border:1px solid #333;
        border-radius:5px; padding:.4rem .6rem; font-size:.8rem; font-family:inherit; }
 button { cursor:pointer; }
 button.primary { background:#e8c47a; color:#111; border:none; font-weight:650; }
 button.danger { border-color:#5a2f2a; color:#d98b7e; }
 select option:disabled { color:#555; }
 /* ---- report cards, chips, meters (added by the full-detail overhaul) ---- */
 .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(290px,1fr));
        gap:.85rem; margin:.55rem 0 .2rem; align-items:start; }
 .cards.wide { grid-template-columns:repeat(auto-fit,minmax(400px,1fr)); }
 .card { background:#131318; border:1px solid #26262b; border-radius:8px;
        padding:.85rem 1rem; }
 .card h3 { margin:0 0 .6rem; font-size:.6rem; letter-spacing:.16em; font-weight:500;
        text-transform:uppercase; color:#8b8b93; }
 .chips { display:flex; gap:.35rem; flex-wrap:wrap; align-items:center; }
 .chip { font-size:.64rem; background:#1c1c22; border:1px solid #32323a; color:#a9a9b4;
        padding:2px 8px; border-radius:10px; white-space:nowrap; display:inline-block; }
 .chip b { color:#e8e8e8; font-weight:650; }
 .chip.gold  { border-color:#4a4026; color:#e8c47a; background:#16140e; }
 .chip.red   { border-color:#5a2f2a; color:#e08b7e; background:#1a1012; }
 .chip.amber { border-color:#4d3c18; color:#d6a95a; background:#17120a; }
 .chip.green { border-color:#204d33; color:#6fbf8e; background:#0e1712; }
 .chip.violet{ border-color:#3d3060; color:#a291d6; background:#131029; }
 .mv { color:#fff; padding:3px 9px; border-radius:3px; font-size:.68rem; letter-spacing:.04em; }
 .kv { display:grid; grid-template-columns:auto 1fr; gap:.3rem .9rem; font-size:.78rem;
        margin:0; }
 .kv dt { color:#8b8b93; font-size:.62rem; text-transform:uppercase; letter-spacing:.1em;
        white-space:nowrap; padding-top:.12rem; }
 .kv dd { margin:0; }
 .bignum { font-size:2.7rem; font-weight:650; color:#e8c47a; line-height:.95; }
 .sub { font-size:.72rem; color:#b0b0b8; }
 .meter { height:5px; background:#1f1f26; border-radius:3px; overflow:hidden; margin-top:4px; }
 .meter i { display:block; height:100%; background:#e8c47a; }
 .wrapx { overflow-x:auto; margin-top:.3rem; }
 .wrapx table { min-width:900px; }
 /* eleven columns of portal detail have to fit the page, not scroll off it */
 table.portaltbl { min-width:1080px; }
 table.portaltbl th, table.portaltbl td { padding:.45rem .35rem; font-size:.76rem; }
 table.portaltbl th { font-size:.57rem; letter-spacing:.08em; }
 table.portaltbl .meta { font-size:.63rem; }
 .nowrap { white-space:nowrap; }
 details.desc { border:1px solid #26262b; border-radius:8px; background:#131318;
        padding:.55rem .95rem; margin-top:.75rem; }
 details.desc summary { cursor:pointer; color:#e8c47a; font-size:.74rem; letter-spacing:.06em; }
 details.desc .body { white-space:pre-wrap; font-size:.83rem; line-height:1.65;
        color:#c5c5ce; margin-top:.75rem; }
 .thumbs { display:flex; gap:.4rem; flex-wrap:wrap; margin-top:.6rem; }
 .thumbs figure { margin:0; }
 .thumbs img { width:104px; height:76px; object-fit:cover; border-radius:5px;
        border:1px solid #2c2c33; background:#1a1a1f; display:block; }
 .thumbs figcaption { font-size:.58rem; color:#7c7c86; margin-top:.15rem;
        text-align:center; letter-spacing:.06em; }
 .proof { font-size:.7rem; color:#6f8f7a; margin-top:.3rem; }
 .proof.stale { color:#d6a95a; }
 .ev { margin:.35rem 0 0; padding-left:1.05rem; }
 .ev li { font-size:.69rem; color:#7f9f8a; line-height:1.55; }
 .flagline { color:#b4645a; font-size:.75rem; line-height:1.5; }
 .note { color:#d6a95a; font-size:.75rem; line-height:1.5; }
 .hero { display:flex; gap:1.4rem; flex-wrap:wrap; align-items:flex-start; }
 .hero img.shot { width:340px; max-width:100%; height:238px; object-fit:cover;
        border-radius:8px; border:1px solid #2c2c33; background:#16161b; }
 .delta.up { color:#e08b7e; } .delta.down { color:#6fbf8e; }
 @media print {
   .card { background:#fff; border-color:#ccc; break-inside:avoid; }
   .card h3 { color:#555; }
   .chip { background:#f5f5f5; border-color:#ccc; color:#333; }
   .chip b { color:#111; }
   .bignum { color:#111; }
   .kv dt { color:#555; }
   .meter { background:#eee; } .meter i { background:#888; }
   details.desc { background:#fff; border-color:#ccc; }
   details.desc[open] summary { color:#111; }
   details.desc .body { color:#222; }
   .wrapx table { min-width:0; }
   .proof { color:#555; }
   .ev li { color:#555; }
 }
 @media print {
   :root { color-scheme: light; }
   body { background:#fff; color:#111; font-size:11pt; }
   header.bar { border-color:#ccc; }
   header.bar .sub, .meta { color:#555; }
   nav.crumbs, .internal, .noprint { display:none !important; }
   a { color:#111; text-decoration:none; }
   h2 { color:#333; border-color:#ccc; }
   th { color:#555; }
   th,td { border-color:#ddd; }
   .disclaimer { color:#444; border-color:#bbb; background:#f5f2ea; }
   .stat b { color:#111; }
   .stat span { color:#555; }
   .price { color:#111; }
   .tier { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
   main { max-width:none; padding:0 .2cm; }
   @page { size: A4; margin: 1.4cm; }
 }
"""

_HEADER = """<header class="bar"><h1>OBLIVION ESTATES</h1>
 <span class="sub">COMPARATIVE MARKET ANALYSIS</span></header>"""


def _page(title: str, body: str, extra_css: str = "",
          script: str = "") -> str:
    return (f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title>
<style>{_CSS}{extra_css}</style></head><body>
{body}
<script>{script}</script></body></html>""")


# --------------------------------------------------------------------- index

_INDEX_QUERY = """
SELECT g.group_id, l.listing_key, l.title, l.suburb, l.suburb_slug,
       l.price_zar, l.photo_count, l.description,
       s.prospect_score, s.tier, s.sellable,
       g.agency_count, g.source_count,
       e.status AS erf_status, e.erf_number
FROM property_groups g
JOIN listings l ON l.listing_key = g.listing_key
LEFT JOIN scores s ON s.listing_key = l.listing_key
LEFT JOIN erf_lookup e ON e.listing_key = l.listing_key
"""


def _index_rows(conn: sqlite3.Connection,
                include_sole: bool = False) -> list[dict]:
    grouped: dict[int, list[sqlite3.Row]] = {}
    for r in conn.execute(_INDEX_QUERY):
        grouped.setdefault(r["group_id"], []).append(r)

    gv_by_group = valuations.for_groups(conn)
    owners.ensure_table(conn)
    owner_by_group = owners.for_groups(conn)

    out = []
    for gid, members in grouped.items():
        best = max(members, key=lambda m: (
            m["prospect_score"] is not None, m["prospect_score"] or 0,
            m["photo_count"] or 0, len(m["description"] or "")))
        if not include_sole and best["sellable"] != 1:
            continue  # sole-mandate or not yet scored: not pitchable stock

        erf = next((m for m in members
                    if m["erf_status"] in ("ok", "confirmed", "check")
                    and m["erf_number"]), None)
        val = gv_by_group.get(str(gid))
        price = max((m["price_zar"] or 0) for m in members) or None
        out.append({
            "group_id": gid,
            "title": best["title"] or best["listing_key"],
            "suburb": best["suburb"] or best["suburb_slug"] or "",
            "price_zar": price,
            "tier": best["tier"],
            "score": best["prospect_score"],
            "erf_number": erf["erf_number"] if erf else None,
            "erf_status": erf["erf_status"] if erf else (best["erf_status"] or "—"),
            "gv_value": (val or {}).get("market_value"),
            "gv_roll": (val or {}).get("roll"),
            "agency_count": max((m["agency_count"] or 1) for m in members),
            "owner_known": str(gid) in owner_by_group,
        })
    out.sort(key=lambda d: (_TIER_ORDER.get(d["tier"] or "", 3),
                            -(d["score"] or -1), -(d["price_zar"] or 0)))
    return out


def render_index(conn: sqlite3.Connection) -> str:
    rows = _index_rows(conn)
    suburbs = sorted({r["suburb"] for r in rows if r["suburb"]})

    trs = []
    for r in rows:
        tier = (f'<span class="tier {_e(r["tier"])}">{_e(r["tier"]).upper()}'
                f'</span> <b>{r["score"]}</b>'
                if r["tier"] else '<span class="meta">unscored</span>')
        erf = (f'ERF {_e(r["erf_number"])}' if r["erf_number"]
               else f'<span class="meta">{_e(r["erf_status"])}</span>')
        gv = (f'{_fmt_r(r["gv_value"])} <span class="meta">{_e(r["gv_roll"])}'
              f'</span>' if r["gv_value"] else '<span class="meta">—</span>')
        owner = ('<span class="badge">owner known</span>' if r["owner_known"]
                 else '<span class="meta">—</span>')
        trs.append(f"""<tr data-suburb="{_e(r['suburb'])}">
  <td>{tier}</td>
  <td><a href="/cma/{r['group_id']}">{_e(r['title'])}</a></td>
  <td>{_e(r['suburb'])}</td>
  <td class="price">{_fmt_r(r['price_zar'])}</td>
  <td>{erf}</td>
  <td>{gv}</td>
  <td>{r['agency_count']}</td>
  <td>{owner}</td>
</tr>""")

    options = '<option value="">all suburbs</option>' + "".join(
        f"<option>{_e(s)}</option>" for s in suburbs)
    body = f"""{_HEADER}
<nav class="crumbs"><a href="/">&larr; dashboard</a> · CMA index</nav>
<main>
<div class="disclaimer">{_e(DISCLAIMER)}</div>
<div class="noprint" style="margin:.6rem 0 .9rem">
  <select id="fsub">{options}</select>
  <span id="fcount" class="meta"></span>
</div>
<table id="cmatable"><tr><th>Tier / score</th><th>Property</th><th>Suburb</th>
<th>Asking</th><th>Erf</th><th>Municipal GV</th><th>Agencies</th><th>Owner</th></tr>
{"".join(trs) if trs else '<tr><td colspan="8" class="meta">No sellable property groups yet — run a scrape and score first.</td></tr>'}
</table>
</main>"""
    script = """
const sel = document.getElementById('fsub');
const rows = [...document.querySelectorAll('#cmatable tr[data-suburb]')];
function apply(){
  const v = sel.value;
  let n = 0;
  rows.forEach(tr => { const show = !v || tr.dataset.suburb === v;
    tr.style.display = show ? '' : 'none'; if (show) n++; });
  document.getElementById('fcount').textContent = n + ' of ' + rows.length + ' properties';
}
sel.addEventListener('input', apply); apply();
"""
    return _page("Oblivion CMA — sellable properties", body, script=script)


# -------------------------------------------------------------------- report

def _comp_status(c: dict) -> str:
    if c.get("likely_sold_price"):
        return (f'<span class="badge">likely sold</span> '
                f'<span class="price">{_fmt_r(c["likely_sold_price"])}</span>'
                f'<div class="meta">asking-at-disappearance proxy</div>')
    if c.get("lifecycle_status") == "delisted":
        return '<span class="badge gray">delisted</span>'
    if c.get("under_offer"):
        return '<span class="badge blue">under offer</span>'
    if c.get("lifecycle_status") == "relisted":
        return '<span class="badge gray">relisted</span>'
    return '<span class="meta">active</span>'


def _cut_cell(cut: dict | None) -> str:
    if not cut:
        return '<span class="meta">—</span>'
    return (f'{_fmt_r(cut["first_price"])} &rarr; {_fmt_r(cut["latest_price"])}'
            f'<div class="meta">{cut["cut_pct"]}% cut</div>')


def _band_graphic(band: dict, asking) -> str:
    """Pure-CSS horizontal ruler: low / mid / high ticks + asking marker."""
    low, mid, high = band.get("low"), band.get("mid"), band.get("high")
    if not (low and mid and high):
        return ""
    lo_dom = min(low, asking or low) * 0.92
    hi_dom = max(high, asking or high) * 1.06
    span = hi_dom - lo_dom or 1

    def pct(v):
        return round((v - lo_dom) / span * 100, 1)

    ticks = ""
    for v, label, color in ((low, "low", "#8b8b93"), (mid, "mid", "#e8c47a"),
                            (high, "high", "#8b8b93")):
        ticks += (
            f'<div style="position:absolute;left:{pct(v)}%;top:0;height:100%;'
            f'width:2px;background:{color}"></div>'
            f'<div style="position:absolute;left:{pct(v)}%;top:-1.35rem;'
            f'transform:translateX(-50%);font-size:.62rem;color:{color};'
            f'text-transform:uppercase;letter-spacing:.1em">{label}</div>'
            f'<div style="position:absolute;left:{pct(v)}%;bottom:-1.35rem;'
            f'transform:translateX(-50%);font-size:.68rem;color:{color};'
            f'white-space:nowrap">{_fmt_r(v)}</div>')
    marker = ""
    if asking:
        marker = (
            f'<div style="position:absolute;left:{pct(asking)}%;top:-.45rem;'
            f'transform:translateX(-50%);width:0;height:0;'
            f'border-left:7px solid transparent;border-right:7px solid transparent;'
            f'border-top:9px solid #c0392b"></div>'
            f'<div style="position:absolute;left:{pct(asking)}%;top:-2.5rem;'
            f'transform:translateX(-50%);font-size:.62rem;color:#c0392b;'
            f'white-space:nowrap">asking {_fmt_r(asking)}</div>')
    fill = (f'<div style="position:absolute;left:{pct(low)}%;'
            f'width:{max(pct(high) - pct(low), 0.5)}%;top:30%;height:40%;'
            f'background:linear-gradient(90deg,#3a3320,#e8c47a55,#3a3320);'
            f'border-radius:3px"></div>')
    return (f'<div style="position:relative;height:22px;background:#1a1a1f;'
            f'border:1px solid #26262b;border-radius:4px;'
            f'margin:3.1rem .4rem 2.2rem">{fill}{ticks}{marker}</div>')


def _owner_block(conn: sqlite3.Connection, group_id: int) -> str:
    owners.ensure_table(conn)
    fields = [f for f in owners.FIELDS if f != "raw"]
    inputs = ""
    for f in fields:
        label = f.replace("_", " ")
        tag = ('<textarea id="own_notes" rows="2"></textarea>' if f == "notes"
               else f'<input id="own_{f}" '
                    f'{"type=number" if f == "purchase_price" else "type=text"}'
                    f'{" placeholder=YYYY-MM-DD" if f == "purchase_date" else ""}>')
        inputs += (f'<label style="display:block;font-size:.68rem;color:#999;'
                   f'text-transform:uppercase;letter-spacing:.1em;'
                   f'margin:.5rem 0 .15rem">{_e(label)}</label>{tag}')

    return f"""<div class="internal" id="ownerblock">
<span class="tag">Internal — not for the seller · owner details (POPIA: minimum data, mandate-pitch use only)</span>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:.2rem .9rem">
{inputs}
</div>
<div style="margin-top:.8rem;display:flex;gap:.6rem;align-items:center;flex-wrap:wrap">
  <button class="primary" onclick="ownerSave()">Save owner details</button>
  <button class="danger" onclick="ownerDelete()">POPIA purge</button>
  <span id="own_updated" class="badge gray" style="display:none"></span>
  <span id="own_msg" class="meta"></span>
</div>
<div class="meta" style="margin-top:.5rem">Self-sourced: look the owner up
against the erf number above in a primary source — DeedsWeb (deeds.gov.za),
the Deeds Office's own search at state-regulated fees — and capture the
result here. Note the source and search date in "notes".</div>
</div>"""


_OWNER_JS = """
const GID = __GID__;
const OWN_FIELDS = __OWN_FIELDS__;
async function ownerLoad(){
  const r = await fetch('/api/owner/' + GID);
  if (!r.ok) return;
  const d = await r.json();
  for (const f of OWN_FIELDS){
    const el = document.getElementById('own_' + f);
    if (el && d[f] != null) el.value = d[f];
  }
  const u = document.getElementById('own_updated');
  if (d.updated_at){ u.style.display=''; u.textContent = 'updated ' + d.updated_at + ' UTC'; }
}
async function ownerSave(){
  const body = {};
  for (const f of OWN_FIELDS){
    const el = document.getElementById('own_' + f);
    if (el && el.value.trim() !== '') body[f] = el.value.trim();
  }
  const r = await fetch('/api/owner/' + GID, {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const d = await r.json().catch(() => ({}));
  const m = document.getElementById('own_msg');
  if (!r.ok){ m.textContent = d.error || ('save failed (' + r.status + ')'); return; }
  m.textContent = 'saved ✓';
  const u = document.getElementById('own_updated');
  if (d.updated_at){ u.style.display=''; u.textContent = 'updated ' + d.updated_at + ' UTC'; }
  setTimeout(() => m.textContent = '', 2500);
}
async function ownerDelete(){
  if (!confirm('Purge stored owner details for this property? (POPIA erasure — cannot be undone)')) return;
  const r = await fetch('/api/owner/' + GID, {method:'DELETE'});
  const d = await r.json().catch(() => ({}));
  const m = document.getElementById('own_msg');
  if (!r.ok){ m.textContent = d.error || 'delete failed'; return; }
  for (const f of OWN_FIELDS){
    const el = document.getElementById('own_' + f);
    if (el) el.value = '';
  }
  document.getElementById('own_updated').style.display = 'none';
  m.textContent = d.deleted ? 'purged ✓' : 'nothing stored';
  setTimeout(() => m.textContent = '', 2500);
}
ownerLoad();
"""


# ------------------------------------------------- batched group-level reads
#
# Everything below is deliberately query-frugal: four extra round trips for
# the whole page (members, price history, scores, erf) and nothing per row.

def _member_rows(conn: sqlite3.Connection, group_id: int) -> list[sqlite3.Row]:
    """Every portal listing in the group, with its lifecycle row attached.

    listing_lifecycle is built by a sibling module and may be absent; ensuring
    the table (it is a CREATE IF NOT EXISTS) keeps the LEFT JOIN legal on a
    database that has never run a lifecycle sweep, and the join then simply
    yields NULLs.
    """
    try:
        lifecycle.ensure_table(conn)
    except sqlite3.Error:
        pass
    try:
        return conn.execute(
            """SELECT l.*, g.agency_count, g.source_count, g.match_evidence,
                      lc.status AS lc_status, lc.delisted_at, lc.relisted_at,
                      lc.days_on_market AS crawl_dom, lc.total_cut_pct,
                      lc.likely_sold, lc.price_at_first_seen
               FROM property_groups g
               JOIN listings l ON l.listing_key = g.listing_key
               LEFT JOIN listing_lifecycle lc ON lc.listing_key = l.listing_key
               WHERE g.group_id = ?
               ORDER BY l.source, l.listing_key""", (group_id,)).fetchall()
    except sqlite3.OperationalError:
        return conn.execute(
            """SELECT l.*, g.agency_count, g.source_count, g.match_evidence
               FROM property_groups g
               JOIN listings l ON l.listing_key = g.listing_key
               WHERE g.group_id = ?
               ORDER BY l.source, l.listing_key""", (group_id,)).fetchall()


def _history_by_key(conn: sqlite3.Connection,
                    keys: list[str]) -> dict[str, list[tuple[str, int]]]:
    """One query for the whole group — never one per listing."""
    if not keys:
        return {}
    out: dict[str, list[tuple[str, int]]] = {}
    for r in conn.execute(
            f"""SELECT listing_key, price_zar, observed_at FROM price_history
                WHERE listing_key IN ({','.join('?' * len(keys))})
                ORDER BY observed_at, rowid""", keys):
        if r["price_zar"]:
            out.setdefault(r["listing_key"], []).append(
                (r["observed_at"], r["price_zar"]))
    return out


def _score_row(conn: sqlite3.Connection, group_id: int) -> sqlite3.Row | None:
    """Best-scored member's row — the group's verdict."""
    return conn.execute(
        """SELECT s.* FROM scores s
           JOIN property_groups g ON g.listing_key = s.listing_key
           WHERE g.group_id = ?
           ORDER BY (s.prospect_score IS NULL), s.prospect_score DESC
           LIMIT 1""", (group_id,)).fetchone()


def _erf_row(conn: sqlite3.Connection, group_id: int,
             keys: list[str]) -> sqlite3.Row | None:
    """Best cadastre resolution for the group (erf_lookup may be missing)."""
    rank = {"confirmed": 3, "ok": 2, "check": 1}
    try:
        rows = conn.execute(
            f"""SELECT * FROM erf_lookup
                WHERE group_id = ?
                   OR listing_key IN ({','.join('?' * len(keys)) or "''"})""",
            (str(group_id), *keys)).fetchall()
    except sqlite3.OperationalError:
        return None
    if not rows:
        return None
    return max(rows, key=lambda r: (
        1 if _rget(r, "erf_number") else 0,
        rank.get(_rget(r, "status") or "", 0),
        1 if _rget(r, "latitude") else 0))


def _group_price_series(history: dict[str, list[tuple[str, int]]]
                        ) -> list[tuple[datetime, float]]:
    """The group's asking price over time.

    Portals lag each other after a reduction, so a single portal's line is not
    "the price". Replaying every observation in order and taking the median of
    the latest-known price per portal gives one curve that moves when the
    market actually moved.
    """
    events = sorted((ts, key, price)
                    for key, rows in history.items() for ts, price in rows)
    latest: dict[str, int] = {}
    series: list[tuple[datetime, float]] = []
    for ts, key, price in events:
        latest[key] = price
        d = cma._parse_date(ts)
        if d is None:
            continue
        series.append((d, statistics.median(sorted(latest.values()))))
    return series


def _brand_proof(members: list[sqlite3.Row]) -> list[tuple[str, float]]:
    """Per distinct agency BRAND, how long ago its freshest listing was seen.

    Two brands only prove an open mandate while both listings are actually
    live, so the proof is worth exactly as much as its stalest brand.
    """
    freshest: dict[str, datetime] = {}
    for m in members:
        brand = canonical_agency(_rget(m, "agency"))
        seen = cma._parse_date(_rget(m, "last_seen"))
        if brand and seen and (brand not in freshest or seen > freshest[brand]):
            freshest[brand] = seen
    now = _utcnow()
    return sorted(((b, (now - t).total_seconds() / 3600.0)
                   for b, t in freshest.items()), key=lambda x: -x[1])


def _best_lifecycle(members: list[sqlite3.Row]) -> sqlite3.Row | None:
    rows = [m for m in members if _rget(m, "lc_status")]
    if not rows:
        return None
    order = {"delisted": 2, "relisted": 3, "active": 1}
    return max(rows, key=lambda m: order.get(m["lc_status"], 0))


def _source_label(source: str | None) -> str:
    info = config.SOURCES.get(source or "", {})
    return info.get("label") or (source or "—")


def _photo_src(member: sqlite3.Row) -> str | None:
    """Stored hero URL, else the cache-only photo endpoint.

    `fetch=0` matters: a report page must never kick off live portal fetches.
    """
    url = _rget(member, "photo_url")
    if url and url != "-":
        return url
    key = _rget(member, "listing_key")
    return f"/api/photo/{key}?fetch=0" if key else None


# ------------------------------------------------------- report sub-sections

def _identity_chips(members: list[sqlite3.Row], lc: sqlite3.Row | None,
                    score: sqlite3.Row | None) -> str:
    chips = []
    if any(_rget(m, "under_offer") for m in members):
        chips.append(_chip("UNDER OFFER", "red"))
    if any(_rget(m, "price_reduced") for m in members):
        chips.append(_chip("price reduced", "amber"))
    if any(_rget(m, "is_development") for m in members):
        chips.append(_chip("development", "violet"))
    explicit = {(_rget(m, "mandate_explicit") or "").strip()
                for m in members} - {""}
    if "sole" in explicit:
        chips.append(_chip("portal says SOLE mandate", "red"))
    if "not_sole" in explicit:
        chips.append(_chip("portal says NOT sole", "green"))
    status = _rget(lc, "lc_status")
    if status == "relisted":
        chips.append(_chip("relisted", "amber"))
    elif status == "delisted":
        chips.append(_chip("delisted", ""))
    verdict = _rget(score, "mandate_verdict")
    if verdict:
        colour = _MANDATE_COLORS.get(verdict, "#5d5d66")
        chips.insert(0, f'<span class="mv" style="background:{colour}">'
                        f'{_e(verdict.replace("_", " "))}</span>')
    tier = _rget(score, "tier")
    if tier:
        chips.insert(0, f'<span class="tier {_e(tier)}">{_e(tier).upper()}'
                        f'</span>')
    return f'<div class="chips" style="margin:.55rem 0">{"".join(chips)}</div>' \
        if chips else ""


def _score_card(score: sqlite3.Row | None) -> str:
    if score is None:
        return ('<div class="card"><h3>Prospect score</h3>'
                '<div class="meta">Not scored yet — run a scoring pass.</div>'
                '</div>')
    tier = _rget(score, "tier") or "cold"
    subs = (("luxury fit", _rget(score, "luxury_fit")),
            ("open-mandate confidence", _rget(score, "open_mandate_confidence")),
            ("marketing weakness", _rget(score, "marketing_weakness")))
    bars = ""
    for label, v in subs:
        pct = max(0, min(100, int(v or 0)))
        bars += (f'<div style="margin-top:.5rem"><div style="display:flex;'
                 f'justify-content:space-between;font-size:.68rem;color:#9a9aa2">'
                 f'<span>{_e(label)}</span><b style="color:#e8e8e8">'
                 f'{"—" if v is None else int(v)}</b></div>'
                 f'<div class="meter"><i style="width:{pct}%"></i></div></div>')
    sellable = _rget(score, "sellable")
    sell_chip = ("" if sellable is None else _chip(
        "pitchable" if sellable else "not pitchable — sole mandate",
        "green" if sellable else "red"))
    return f"""<div class="card"><h3>Prospect score</h3>
<div style="display:flex;gap:.9rem;align-items:baseline;flex-wrap:wrap">
  <div class="bignum">{_rget(score, 'prospect_score') if _rget(score, 'prospect_score') is not None else '—'}</div>
  <div><span class="tier {_e(tier)}">{_e(tier).upper()}</span>
   <div class="meta">{_e(_rget(score, 'scored_by') or 'unscored')} ·
    {_e((_rget(score, 'scored_at') or '')[:16])}</div></div>
</div>
<div class="chips" style="margin-top:.5rem">{sell_chip}</div>
{bars}
</div>"""


def _mandate_card(members: list[sqlite3.Row], score: sqlite3.Row | None) -> str:
    agencies = sorted({(_rget(m, "agency") or "").strip()
                       for m in members} - {""})
    brands = sorted({b for b in (canonical_agency(_rget(m, "agency"))
                                 for m in members) if b})
    proof = _brand_proof(members)
    verdict = _rget(score, "mandate_verdict") or "unknown"
    colour = _MANDATE_COLORS.get(verdict, "#5d5d66")
    conf = _rget(score, "open_mandate_confidence")

    proof_html = ""
    if len(brands) > 1 and proof:
        worst = proof[0][1]
        cls = "proof stale" if worst > _PROOF_FRESH_HOURS else "proof"
        seen = " · ".join(f"{_e(b)} {_age_label(h)} ago" for b, h in proof)
        warn = (f'<div class="note">Stalest brand is {_age_label(worst)} old '
                f'(> {_PROOF_FRESH_HOURS}h) — re-crawl before pitching the '
                f'open mandate as proven.</div>'
                if worst > _PROOF_FRESH_HOURS else "")
        proof_html = (f'<div class="{cls}">proof last confirmed live: {seen}'
                      f'</div>{warn}')
    elif brands:
        age = _age_label(proof[0][1]) if proof else "—"
        proof_html = (f'<div class="proof">single brand — last confirmed live '
                      f'{age} ago</div>')

    # A portal carrying five units of the same complex repeats its mandate
    # flag five times; the fact, not the repetition, is what matters.
    seen_flags: dict[tuple[str, str], int] = {}
    for m in members:
        ex = (_rget(m, "mandate_explicit") or "").strip()
        if ex:
            k = (_source_label(_rget(m, "source")), ex)
            seen_flags[k] = seen_flags.get(k, 0) + 1
    explicit_bits = [
        f'{_e(src)}: <b>{_e(ex.replace("_", " "))}</b>'
        + (f' <span class="meta">×{n}</span>' if n > 1 else "")
        for (src, ex), n in sorted(seen_flags.items())]
    texts = sorted({(_rget(m, "mandate_text") or "").strip()
                    for m in members} - {"", "unknown"})

    note = _rget(score, "mandate_expiry_note")
    rows = [
        ("verdict", f'<span class="mv" style="background:{colour}">'
                    f'{_e(verdict.replace("_", " "))}</span>'
                    + (f' <span class="meta">confidence {int(conf)}/100</span>'
                       if conf is not None else "")),
        ("distinct brands", f'<b>{len(brands)}</b> — {_e(", ".join(brands)) or "—"}'),
        ("agency names", _e(", ".join(agencies)) or "—"),
        ("portals", f'{len({_rget(m, "source") for m in members})} '
                    f'({_e(", ".join(sorted({_source_label(_rget(m, "source")) for m in members})))})'),
    ]
    if explicit_bits:
        rows.append(("portal mandate flag", "<br>".join(explicit_bits)))
    if texts:
        rows.append(("mandate wording", _e(", ".join(texts))))
    kv = "".join(f"<dt>{_e(k) if '<' not in k else k}</dt><dd>{v}</dd>"
                 for k, v in rows)
    return f"""<div class="card"><h3>Mandate &amp; evidence</h3>
<dl class="kv">{kv}</dl>
{proof_html}
{f'<div class="note" style="margin-top:.45rem">{_e(note)}</div>' if note else ''}
</div>"""


def _evidence_card(members: list[sqlite3.Row]) -> str:
    raw = next((_rget(m, "match_evidence") for m in members
                if _rget(m, "match_evidence")), None)
    try:
        ev = json.loads(raw or "[]")
    except (ValueError, TypeError):
        ev = []
    if not ev:
        return ""
    items = "".join(f"<li>{_e(x)}</li>" for x in ev[:10])
    more = (f'<div class="meta">+{len(ev) - 10} more</div>'
            if len(ev) > 10 else "")
    return f"""<div class="card"><h3>Why these listings are one property</h3>
<ul class="ev">{items}</ul>{more}</div>"""


def _internal_score_block(score: sqlite3.Row | None) -> str:
    if score is None:
        return ""
    pitch = _rget(score, "pitch_angle")
    reasoning = _rget(score, "reasoning")
    flags = _rget(score, "red_flags")
    if not (pitch or reasoning or flags):
        return ""
    return f"""<div class="internal">
<span class="tag">Internal — not for the seller · scoring rationale</span>
{f'<div style="font-size:.92rem;line-height:1.55;margin-bottom:.5rem">{_e(pitch)}</div>' if pitch else ''}
{f'<div class="meta" style="line-height:1.6">{_e(reasoning)}</div>' if reasoning else ''}
{f'<div class="flagline" style="margin-top:.5rem">Red flags: {_e(flags)}</div>' if flags else ''}
</div>"""


def _deal_signals(members: list[sqlite3.Row],
                  history: dict[str, list[tuple[str, int]]],
                  lc: sqlite3.Row | None) -> str:
    # --- days on market on both bases, stated separately: the portal's own
    # listing date is the truth; first_seen is only a floor set by our crawl.
    listed = [d for d in (cma._parse_date(_rget(m, "listing_date"))
                          for m in members) if d]
    seen = [d for d in (cma._parse_date(_rget(m, "first_seen"))
                        for m in members) if d]
    # listing_date is a calendar date the portal printed (local); first_seen is
    # SQLite's UTC stamp — mixing the two clocks would put this chip a day out
    # from the same figure in the subject block.
    dom_portal = (datetime.now() - min(listed)).days if listed else None
    dom_crawl = (_utcnow() - min(seen)).days if seen else None

    chips = []
    if dom_portal is not None:
        chips.append(_chip(f'<b>{dom_portal}</b> days on market '
                           f'<span style="opacity:.7">portal listing date</span>',
                           "gold" if dom_portal >= 90 else ""))
    if dom_crawl is not None:
        chips.append(_chip(f'<b>{dom_crawl}+</b> days observed '
                           f'<span style="opacity:.7">since first crawl</span>'))
    if any(_rget(m, "under_offer") for m in members):
        chips.append(_chip("under offer", "red"))
    if any(_rget(m, "price_reduced") for m in members):
        chips.append(_chip("portal flags a price reduction", "amber"))
    cut = max((_rget(m, "total_cut_pct") or 0.0 for m in members), default=0.0)
    if cut:
        chips.append(_chip(f'total cut <b>{cut:.1f}%</b>', "amber"))
    status = _rget(lc, "lc_status")
    if status:
        cls = {"relisted": "amber", "delisted": "", "active": "green"}.get(status, "")
        chips.append(_chip(f"lifecycle: {_e(status)}", cls))
    if status == "relisted":
        gone = cma._parse_date(_rget(lc, "delisted_at"))
        back = cma._parse_date(_rget(lc, "relisted_at"))
        gap = f" after {(back - gone).days}d off-market" if gone and back else ""
        chips.append(_chip(f"relisted{gap} — possible failed mandate", "amber"))
    if _rget(lc, "likely_sold"):
        chips.append(_chip("vanished while under offer — likely sold", "red"))

    # --- per-listing chronology, then one curve for the group
    labels = {m["listing_key"]: _source_label(_rget(m, "source"))
              for m in members}
    rows_out = []
    for key, obs in history.items():
        first = obs[0][1]
        prev = None
        for ts, price in obs:
            delta = "" if prev is None else price - prev
            if delta == "":
                delta_html = '<span class="meta">first sighting</span>'
            elif delta == 0:
                delta_html = '<span class="meta">—</span>'
            else:
                cls = "down" if delta < 0 else "up"
                sign = "−" if delta < 0 else "+"
                delta_html = (f'<span class="delta {cls}">{sign}'
                              f'{_fmt_r(abs(delta))[2:]}</span>')
            from_first = ((first - price) / first * 100) if first else None
            ff_html = ('<span class="meta">—</span>' if not from_first
                       else f'<span class="delta '
                            f'{"down" if from_first > 0 else "up"}">'
                            f'{"−" if from_first > 0 else "+"}'
                            f'{abs(from_first):.1f}%</span>')
            rows_out.append((ts, f"""<tr>
  <td class="nowrap">{_e(ts[:16])}</td>
  <td>{_e(labels.get(key, key))}<div class="meta">{_e(key)}</div></td>
  <td class="price">{_fmt_r(price)}</td>
  <td>{delta_html}</td>
  <td>{ff_html}</td>
</tr>"""))
            prev = price
    rows_out.sort(key=lambda x: x[0])
    shown = rows_out[-60:]
    truncated = ('<div class="meta">showing the most recent 60 of '
                 f'{len(rows_out)} observations</div>'
                 if len(rows_out) > len(shown) else "")
    timeline = (f"""<table><tr><th>Observed</th><th>Portal</th><th>Price</th>
<th>Change</th><th>vs that listing's first</th></tr>
{''.join(h for _, h in shown)}</table>{truncated}"""
                if shown else
                '<div class="meta">No price observations recorded yet.</div>')

    spark = _sparkline(_group_price_series(history))
    spark_html = (f'<div class="card" style="max-width:360px">'
                  f'<h3>Group asking price</h3>{spark}'
                  f'<div class="meta" style="margin-top:.35rem">median of the '
                  f'latest price known per portal, replayed over time</div>'
                  f'</div>' if spark else "")

    return f"""<h2>Deal signals</h2>
<div class="chips">{''.join(chips) or '<span class="meta">no deal signals recorded</span>'}</div>
<div style="display:flex;gap:1.1rem;flex-wrap:wrap;align-items:flex-start;margin-top:.8rem">
  {spark_html}
  <div style="flex:1;min-width:340px">{timeline}</div>
</div>"""


def _portal_table(members: list[sqlite3.Row]) -> str:
    rows = ""
    for m in members:
        badges = []
        if _rget(m, "under_offer"):
            badges.append(_chip("under offer", "red"))
        if _rget(m, "price_reduced"):
            badges.append(_chip("reduced", "amber"))
        ex = (_rget(m, "mandate_explicit") or "").strip()
        if ex:
            badges.append(_chip(ex.replace("_", " "),
                                "red" if ex == "sole" else "green"))
        mt = (_rget(m, "mandate_text") or "").strip()
        if mt and mt != "unknown":
            badges.append(_chip(f"“{_e(mt)}”"))
        st = _rget(m, "lc_status")
        if st and st != "active":
            badges.append(_chip(st, "amber" if st == "relisted" else ""))

        age = _age_hours(_rget(m, "last_seen"))
        stale = age is not None and age > _PROOF_FRESH_HOURS
        listed = _rget(m, "listing_date")
        listed_days = _days_since(listed)

        size = " / ".join(x for x in (
            f"{_fmt_area(_rget(m, 'floor_size_m2'))} floor"
            if _rget(m, "floor_size_m2") else None,
            f"{_fmt_area(_rget(m, 'erf_size_m2'))} erf"
            if _rget(m, "erf_size_m2") else None) if x) or "—"
        extras = " · ".join(x for x in (
            f"{_fmt_num(_rget(m, 'garages'))} gar" if _rget(m, "garages") else None,
            f"{_fmt_num(_rget(m, 'parking'))} park" if _rget(m, "parking") else None,
            f"pool {_pool_label(_rget(m, 'pool'))}"
            if _pool_label(_rget(m, "pool")) != "—" else None) if x) or "—"
        url = _rget(m, "url")
        portal = _e(_source_label(_rget(m, "source")))
        portal_html = (f'<a href="{_e(url)}" target="_blank" rel="noopener">'
                       f'{portal}</a>' if url else portal)
        rows += f"""<tr>
  <td>{portal_html}<div class="meta">{_e(_rget(m, 'listing_key'))}</div></td>
  <td>{_e(_rget(m, 'agency') or '—')}
      <div class="meta">{_e(_rget(m, 'agent_name') or 'agent not published')}</div></td>
  <td class="price">{_fmt_r(_rget(m, 'price_zar'))}</td>
  <td class="nowrap">{_fmt_num(_rget(m, 'bedrooms'))} bd · {_fmt_num(_rget(m, 'bathrooms'))} ba</td>
  <td class="nowrap">{size}</td>
  <td class="nowrap">levies {_money_or_dash(_rget(m, 'levies'))}
      <div class="meta">rates {_money_or_dash(_rget(m, 'rates'))}</div></td>
  <td class="nowrap">{extras}</td>
  <td class="nowrap">{_e(listed) or '—'}
      {f'<div class="meta">{listed_days}d ago</div>' if listed_days is not None else ''}</td>
  <td class="nowrap">{_fmt_num(_rget(m, 'photo_count'))}</td>
  <td class="nowrap"{' style="color:#d6a95a"' if stale else ''}>{_age_label(age)}
      <div class="meta">{_e((_rget(m, 'last_seen') or '')[:10])}</div></td>
  <td><div class="chips">{''.join(badges) or '<span class="meta">—</span>'}</div></td>
</tr>"""
    return f"""<div class="wrapx"><table class="portaltbl">
<tr><th>Portal</th><th>Agency / agent</th><th>Price</th><th>Beds/baths</th>
<th>Size</th><th>Levies / rates</th><th>Garaging · pool</th><th>Listed</th>
<th>Photos</th><th>Last seen</th><th>Flags</th></tr>
{rows}</table></div>"""


def _thumbs(members: list[sqlite3.Row]) -> str:
    figs = ""
    for m in members:
        src = _photo_src(m)
        if not src:
            continue
        url = _rget(m, "url")
        img = (f'<img loading="lazy" src="{_e(src)}" alt="" '
               f'onerror="this.closest(\'figure\').remove()">')
        if url:
            img = (f'<a href="{_e(url)}" target="_blank" rel="noopener" '
                   f'tabindex="-1">{img}</a>')
        figs += (f'<figure>{img}<figcaption>'
                 f'{_e(_source_label(_rget(m, "source")))}</figcaption></figure>')
    return f'<div class="thumbs noprint">{figs}</div>' if figs else ""


def _description_block(members: list[sqlite3.Row]) -> str:
    best = max(members, key=lambda m: len(_rget(m, "description") or ""),
               default=None)
    text = _rget(best, "description") or ""
    if not text.strip():
        return ""
    src = _source_label(_rget(best, "source"))
    words = len(text.split())
    return f"""<details class="desc">
<summary>Full listing description — longest of the {len(members)} portal copies
({_e(src)}, {words} words)</summary>
<div class="body">{_e(text.strip())}</div></details>"""


def _valuation_block(subj: dict, stats: dict, gv_value, gv_roll,
                     erf: sqlite3.Row | None) -> str:
    asking = subj.get("price_zar")
    cards = []

    # --- municipal GV anchor
    if gv_value:
        ratio = (asking / gv_value) if asking else None
        if ratio is None:
            verdict = '<span class="meta">no asking price to compare</span>'
        elif ratio > 1.3:
            verdict = _chip(f"asking is <b>{ratio:.2f}×</b> GV — overpriced "
                            f"vs the roll", "red")
        elif ratio < 0.9:
            verdict = _chip(f"asking is <b>{ratio:.2f}×</b> GV — possible "
                            f"value", "green")
        else:
            verdict = _chip(f"asking is <b>{ratio:.2f}×</b> GV — in line", "")
        cards.append(f"""<div class="card"><h3>Municipal valuation</h3>
<div class="bignum" style="font-size:1.7rem">{_fmt_r(gv_value)}</div>
<div class="meta">{_e(gv_roll or '')} general valuation roll</div>
<div class="chips" style="margin-top:.55rem">{verdict}</div>
<div class="meta" style="margin-top:.4rem">A municipal rates valuation, not a
market valuation — it lags the market and is a sanity check, not a price.</div>
</div>""")

    # --- price per m² against the suburb median
    rows = []
    for label, size_key, med_key in (
            ("floor", "floor_size_m2", "median_r_per_m2_floor"),
            ("erf", "erf_size_m2", "median_r_per_m2_erf_houses")):
        size = subj.get(size_key)
        med = stats.get(med_key)
        if not (asking and size):
            continue
        ppm2 = asking / size
        cell = f'<b>R {round(ppm2):,}'.replace(",", " ") + "</b>/m²"
        if med:
            diff = (ppm2 - med) / med * 100
            cls = "up" if diff > 0 else "down"
            cell += (f'<div class="meta">suburb median R '
                     f'{med:,}'.replace(",", " ") + f'/m² · '
                     f'<span class="delta {cls}">{"+" if diff > 0 else "−"}'
                     f'{abs(diff):.0f}%</span></div>')
        else:
            cell += '<div class="meta">no suburb median for this basis</div>'
        rows.append((f"R/m² ({label})", cell))
    if rows:
        kv = "".join(f"<dt>{_e(k)}</dt><dd>{v}</dd>" for k, v in rows)
        cards.append(f'<div class="card"><h3>Price per m²</h3>'
                     f'<dl class="kv">{kv}</dl></div>')

    # --- cadastre / erf
    if erf is not None and _rget(erf, "status"):
        bits = []
        num = _rget(erf, "erf_number")
        if num:
            portion = _rget(erf, "portion")
            bits.append(("erf", f'<b>{_e(num)}'
                                f'{"/" + _e(portion) if portion else ""}</b>'))
        for label, key in (("official address", "official_address"),
                           ("official suburb", "official_suburb"),
                           ("SG code", "sg26_code"),
                           ("resolution", "method")):
            v = _rget(erf, key)
            if v:
                bits.append((label, _e(v)))
        area = _rget(erf, "parcel_area_m2")
        if area:
            bits.append(("parcel area", _fmt_area(area)))
        bits.append(("status", _e(_rget(erf, "status"))))
        note = _rget(erf, "note")
        lat, lng = _rget(erf, "latitude"), _rget(erf, "longitude")
        sat = (f'<div style="margin-top:.5rem"><a class="noprint" '
               f'href="{_sat_url(lat, lng)}" target="_blank" rel="noopener">'
               f'satellite view of the parcel &rarr;</a></div>'
               if lat and lng else "")
        kv = "".join(f"<dt>{_e(k)}</dt><dd>{v}</dd>" for k, v in bits)
        cards.append(f"""<div class="card"><h3>Land parcel (public cadastre)</h3>
<dl class="kv">{kv}</dl>
{f'<div class="note" style="margin-top:.4rem">{_e(note)}</div>' if note else ''}
{sat}</div>""")

    if not cards:
        return ""
    return (f'<h2>Valuation anchors &amp; land</h2>'
            f'<div class="cards">{"".join(cards)}</div>')


def render_report(conn: sqlite3.Connection, group_id: int) -> str | None:
    """The full CMA report page; None when the group doesn't exist.

    Page order is deliberate: who/what this is, then whether it is worth
    pitching (score + mandate), then the pressure the seller is under (deal
    signals), then the money (guidance + comps), then the raw per-portal
    record, the land, the owner and finally what has left the market nearby.
    """
    data = cma.analyse(conn, group_id)
    if data is None:
        return None
    subj = data["subject"]
    band = data["price_range"]
    stats = data["suburb_stats"] or {}
    asking = subj.get("price_zar")

    # Four batched reads for the whole page — nothing per row.
    members = _member_rows(conn, group_id)
    keys = [m["listing_key"] for m in members]
    history = _history_by_key(conn, keys)
    score = _score_row(conn, group_id)
    erf = _erf_row(conn, group_id, keys)
    lc = _best_lifecycle(members)

    val = valuations.for_groups(conn).get(str(group_id))
    gv_value = (val or {}).get("market_value")
    gv_roll = (val or {}).get("roll")

    slug = subj.get("suburb_slug")
    offmarket = lifecycle.history_comps(conn, slug, limit=8) if slug else []
    evidence_html = _evidence_card(members)

    # ---------------- identity
    erf_label = subj["erf_number"] or (_rget(erf, "erf_number") or "")
    street = subj.get("official_address") or next(
        (_rget(m, "street_address_raw") for m in members
         if _rget(m, "street_address_raw")), None)
    address_line = " · ".join(x for x in (
        street,
        f"Erf {erf_label}" if erf_label else None,
        subj.get("official_suburb") or subj.get("suburb"),
        subj.get("property_type")) if x)

    hero_member = max(members, key=lambda m: (
        1 if (_rget(m, "photo_url") or "-") != "-" else 0,
        _rget(m, "photo_count") or 0), default=None)
    hero_src = subj.get("photo_url") if (subj.get("photo_url") or "-") != "-" \
        else (_photo_src(hero_member) if hero_member is not None else None)
    photo = (f'<img class="shot" src="{_e(hero_src)}" alt="" '
             f'onerror="this.remove()">' if hero_src else "")

    size_bits = []
    if subj.get("floor_size_m2"):
        size_bits.append(f"{_fmt_area(subj['floor_size_m2'])} floor")
    if subj.get("erf_size_m2"):
        size_bits.append(f"{_fmt_area(subj['erf_size_m2'])} erf")

    dom = subj.get("days_on_market")
    dom_txt = (f"<b>{dom}</b> days on market "
               f"<span class='meta'>({_e(subj.get('days_on_market_basis'))} "
               f"basis)</span>" if dom is not None
               else "<span class='meta'>days on market unknown</span>")

    # Two listings on one portal are common (different agencies, same house),
    # so a bare portal name would give two identical chips — qualify them.
    per_source: dict = {}
    brands_per_source: dict = {}
    for m in members:
        src = _rget(m, "source")
        per_source[src] = per_source.get(src, 0) + 1
        brands_per_source.setdefault(src, set()).add(
            canonical_agency(_rget(m, "agency")) or "")
    portal_bits = []
    for m in members:
        if not _rget(m, "url"):
            continue
        src = _rget(m, "source")
        label = _source_label(src)
        if per_source.get(src, 0) > 1:
            # The agency only disambiguates when the portal's listings differ
            # by agency; otherwise (one agency, several units) the portal's own
            # reference is the only thing that tells them apart.
            brand = canonical_agency(_rget(m, "agency"))
            qual = (brand if brand and len(brands_per_source[src]) > 1
                    else _rget(m, "source_id"))
            label += f" · {qual}"
        portal_bits.append(
            f'<a class="chip noprint" href="{_e(m["url"])}" target="_blank" '
            f'rel="noopener">{_e(label)} &rarr;</a>')
    portals = " ".join(portal_bits)
    lat, lng = _rget(erf, "latitude"), _rget(erf, "longitude")
    sat = (f'<a class="chip noprint" href="{_sat_url(lat, lng)}" '
           f'target="_blank" rel="noopener">satellite &rarr;</a>'
           if lat and lng else "")

    gv_line = ""
    if gv_value:
        ratio = f" · asking <b>{asking / gv_value:.2f}&times;</b> GV" \
            if asking else ""
        gv_line = (f'<div style="margin-top:.45rem;font-size:.8rem">'
                   f'Municipal GV <b>{_fmt_r(gv_value)}</b> '
                   f'<span class="meta">({_e(gv_roll)} roll)</span>{ratio}</div>')

    identity = f"""<div class="hero">
  {photo}
  <div style="flex:1;min-width:280px">
    <div class="price" style="font-size:2rem;color:#e8c47a">{_fmt_r(asking)}</div>
    {_identity_chips(members, lc, score)}
    <div style="margin-top:.15rem">{_fmt_num(subj.get('beds'))} bed ·
      {_fmt_num(subj.get('baths'))} bath
      {(' · ' + ' · '.join(size_bits)) if size_bits else ''}</div>
    <div style="margin-top:.35rem">{dom_txt}</div>
    <div class="meta" style="margin-top:.35rem">Marketed by
      {_e(", ".join(subj.get("agencies") or []) or "—")}</div>
    {gv_line}
    <div class="chips" style="margin-top:.6rem">{portals}{sat}</div>
  </div>
</div>"""

    # ---------------- price guidance (unchanged maths, same graphic)
    if band.get("mid"):
        band_html = f"""
<div style="display:flex;gap:2.2rem;flex-wrap:wrap;align-items:baseline">
  <div><span class="meta">LOW</span><div class="price" style="font-size:1.25rem">{_fmt_r(band['low'])}</div></div>
  <div><span class="meta">RECOMMENDED</span><div class="price" style="font-size:1.8rem;color:#e8c47a">{_fmt_r(band['mid'])}</div></div>
  <div><span class="meta">HIGH</span><div class="price" style="font-size:1.25rem">{_fmt_r(band['high'])}</div></div>
</div>
{_band_graphic(band, asking)}
<div class="meta">Basis: {_e(band.get('basis'))}</div>"""
    else:
        band_html = (f'<div class="meta">No price guidance possible — '
                     f'{_e(band.get("basis"))}</div>')
    notes_html = "".join(f'<li>{_e(n)}</li>' for n in data.get("notes") or [])

    # ---------------- comps table
    comp_rows = ""
    for c in data["comps"]:
        size = (f"{_fmt_area(c['floor_size_m2'])} floor"
                if c.get("floor_size_m2")
                else (f"{_fmt_area(c['erf_size_m2'])} erf"
                      if c.get("erf_size_m2") else "—"))
        ppm2 = (f"R {c['r_per_m2_floor']:,}".replace(",", " ")
                if c.get("r_per_m2_floor")
                else (f"R {c['r_per_m2_erf']:,} (erf)".replace(",", " ")
                      if c.get("r_per_m2_erf") else "—"))
        title = (f'<a href="{_e(c["url"])}" target="_blank" rel="noopener">'
                 f'{_e(c["title"] or c["listing_key"])}</a>'
                 if c.get("url") else _e(c["title"] or c["listing_key"]))
        comp_rows += f"""<tr>
  <td>{title}<div class="meta">{_e(c['distance'])}</div></td>
  <td>{_e(c['suburb'] or '')}</td>
  <td class="price">{_fmt_r(c['price_zar'])}</td>
  <td>{size}</td>
  <td>{ppm2}</td>
  <td>{_fmt_num(c['beds'])}</td>
  <td>{_comp_status(c)}</td>
  <td>{_cut_cell(c.get('price_cut'))}</td>
  <td><b>{c['similarity']}</b><span class="meta">/100</span></td>
</tr>"""
    comps_html = (f"""<div class="wrapx"><table><tr><th>Property</th><th>Suburb</th>
<th>Price</th><th>Size</th><th>R/m²</th><th>Beds</th><th>Status</th>
<th>Price move</th><th>Similar</th></tr>{comp_rows}</table></div>"""
                  if comp_rows
                  else '<div class="meta">No comparable listings found.</div>')

    # ---------------- suburb stats strip
    stat_bits = ""
    if stats.get("active_count"):
        pct_share = stats.get("price_cut_share")
        for label, v in (
                ("active listings", stats.get("active_count")),
                ("median asking", _fmt_r(stats.get("median_asking_zar"))
                 if stats.get("median_asking_zar") else "—"),
                ("median R/m² (floor)",
                 f"R {stats['median_r_per_m2_floor']:,}".replace(",", " ")
                 if stats.get("median_r_per_m2_floor") else "—"),
                ("median days on market",
                 _fmt_num(stats.get("median_days_on_market"))),
                ("share with a price cut",
                 f"{round(pct_share * 100)}%" if pct_share is not None else "—"),
                ("median cut",
                 f"{stats['median_cut_pct']}%" if stats.get("median_cut_pct")
                 else "—")):
            stat_bits += (f'<div class="stat"><b>{v}</b>'
                          f'<span>{_e(label)}</span></div>')

    # ---------------- off-market activity
    off_rows = ""
    for h in offmarket:
        status = ('<span class="badge">likely sold</span>' if h["likely_sold"]
                  else '<span class="badge gray">delisted</span>')
        price = _fmt_r(h["likely_sold_price"] or h["price_zar"])
        off_rows += f"""<tr>
  <td>{_e(h['title'] or h['listing_key'])}</td>
  <td>{status}</td>
  <td class="price">{price}</td>
  <td>{_e((h['delisted_at'] or '')[:10])}</td>
  <td>{_fmt_num(round(h['days_on_market']) if h['days_on_market'] else None)}</td>
  <td>{f"{h['total_cut_pct']}%" if h['total_cut_pct'] else '—'}</td>
</tr>"""
    off_html = ""
    if off_rows:
        off_html = f"""<h2>Recent off-market activity — {_e(subj.get('suburb') or slug)}</h2>
<div class="meta" style="margin-bottom:.4rem">Delisted stock from our own crawl
history. "Likely sold" = vanished while under offer; the price shown is the
asking price at disappearance (a proxy, not a deeds record).</div>
<div class="wrapx"><table><tr><th>Property</th><th>Status</th><th>Last price</th>
<th>Delisted</th><th>DOM</th><th>Total cut</th></tr>{off_rows}</table></div>"""

    body = f"""{_HEADER}
<nav class="crumbs"><a href="/">&larr; dashboard</a> ·
 <a href="/cma">CMA index</a> · group {group_id}
 <button class="noprint" style="float:right;font-size:.68rem"
   onclick="window.print()">Print / save PDF</button></nav>
<main>
<h1 style="font-weight:300;letter-spacing:.02em;font-size:1.5rem;margin:.4rem 0 .1rem">
{_e(subj.get('title') or f"Property group {group_id}")}</h1>
<div class="meta" style="font-size:.85rem">{_e(address_line) or _e(subj.get('suburb') or '')}</div>
<div class="disclaimer">{_e(DISCLAIMER)}</div>

<h2>Subject property</h2>
{identity}

<h2>Prospect verdict</h2>
<div class="cards">
{_score_card(score)}
{_mandate_card(members, score)}
</div>
{f'<div class="cards wide">{evidence_html}</div>' if evidence_html else ''}
{_internal_score_block(score)}

{_deal_signals(members, history, lc)}

<h2>Price guidance</h2>
{band_html}
{f'<ul style="font-size:.78rem;color:#b0b0b8;line-height:1.6;padding-left:1.2rem;margin-top:.7rem">{notes_html}</ul>' if notes_html else ''}

<h2>Comparable properties</h2>
{comps_html}

{f'<h2>Suburb snapshot — {_e(subj.get("suburb") or slug)}</h2><div class="stats">{stat_bits}</div>' if stat_bits else ''}

<h2>Every portal listing for this property ({len(members)})</h2>
<div class="meta" style="margin-bottom:.35rem">One row per portal listing the
crawl holds — the raw record behind the merged view above. Fields differ
between portals; blanks mean that portal never published the field.</div>
{_portal_table(members)}
{_thumbs(members)}
{_description_block(members)}

{_valuation_block(subj, stats, gv_value, gv_roll, erf)}

{_owner_block(conn, group_id)}

{off_html}
</main>"""

    own_fields = [f for f in owners.FIELDS if f != "raw"]
    script = (_OWNER_JS
              .replace("__GID__", str(group_id))
              .replace("__OWN_FIELDS__", json.dumps(own_fields)))
    title = f"CMA — {subj.get('title') or group_id}"
    return _page(title, body, script=script)
