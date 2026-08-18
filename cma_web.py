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

import cma
import lifecycle
import owners
import valuations

DISCLAIMER = ("Comparative market analysis for guidance only — not a formal "
              "valuation; only a registered professional valuer may issue a "
              "valuation (SA Property Valuers Profession Act).")

_TIER_ORDER = {"hot": 0, "warm": 1, "cold": 2}


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


def render_report(conn: sqlite3.Connection, group_id: int) -> str | None:
    """The full CMA report page; None when the group doesn't exist."""
    data = cma.analyse(conn, group_id)
    if data is None:
        return None
    subj = data["subject"]
    band = data["price_range"]
    stats = data["suburb_stats"] or {}
    asking = subj.get("price_zar")

    # GV value with roll, via valuations (market_value 0/None = no anchor)
    val = valuations.for_groups(conn).get(str(group_id))
    gv_value = (val or {}).get("market_value")
    gv_roll = (val or {}).get("roll")

    # parcel centroid for the satellite link (same pattern as the dashboard)
    ll = conn.execute(
        "SELECT latitude, longitude FROM erf_lookup WHERE group_id = ?"
        " AND latitude IS NOT NULL AND longitude IS NOT NULL LIMIT 1",
        (str(group_id),)).fetchone()

    # best-scored member's pitch angle (internal aid)
    score_row = conn.execute(
        """SELECT s.pitch_angle, s.reasoning, s.tier, s.prospect_score
           FROM scores s JOIN property_groups g ON g.listing_key = s.listing_key
           WHERE g.group_id = ?
           ORDER BY (s.prospect_score IS NULL), s.prospect_score DESC
           LIMIT 1""", (group_id,)).fetchone()

    slug = subj.get("suburb_slug")
    offmarket = lifecycle.history_comps(conn, slug, limit=8) if slug else []

    # ---------------- subject block
    erf_label = subj["erf_number"] or ""
    address_line = " · ".join(x for x in (
        subj.get("official_address"),
        f"Erf {erf_label}" if erf_label else None,
        subj.get("official_suburb") or subj.get("suburb")) if x)

    photo = ""
    if subj.get("photo_url") and subj["photo_url"] != "-":
        photo = (f'<img src="{_e(subj["photo_url"])}" alt="" '
                 f'style="width:280px;max-width:100%;height:200px;object-fit:cover;'
                 f'border-radius:6px;border:1px solid #2c2c33" '
                 f'onerror="this.remove()">')
    elif subj.get("listing_key"):
        photo = (f'<img src="/api/photo/{_e(subj["listing_key"])}" alt="" '
                 f'style="width:280px;max-width:100%;height:200px;object-fit:cover;'
                 f'border-radius:6px;border:1px solid #2c2c33" '
                 f'onerror="this.remove()">')

    size_bits = []
    if subj.get("floor_size_m2"):
        size_bits.append(f"{_fmt_area(subj['floor_size_m2'])} floor")
    if subj.get("erf_size_m2"):
        size_bits.append(f"{_fmt_area(subj['erf_size_m2'])} erf")

    dom = subj.get("days_on_market")
    dom_txt = (f"{dom} days on market "
               f"<span class='meta'>({_e(subj.get('days_on_market_basis'))})"
               f"</span>" if dom is not None else "days on market unknown")

    hist_rows = ""
    seen_prices = []
    for h in subj.get("price_history") or []:
        if h["price_zar"] in seen_prices:
            continue
        seen_prices.append(h["price_zar"])
        hist_rows += (f'<div class="meta">{_e(h["observed_at"])} — '
                      f'{_fmt_r(h["price_zar"])}</div>')
    cut = subj.get("price_cut")
    if cut:
        hist_rows += (f'<div style="color:#d6a95a;font-size:.75rem;'
                      f'margin-top:.2rem">moved {_fmt_r(cut["first_price"])} '
                      f'&rarr; {_fmt_r(cut["latest_price"])} '
                      f'({cut["cut_pct"]}%)</div>')

    portals = " ".join(
        f'<a class="noprint" href="{_e(u)}" target="_blank" rel="noopener" '
        f'style="font-size:.66rem;background:#1c1c22;border:1px solid #32323a;'
        f'padding:1px 8px;border-radius:9px">{_e(u.split("/")[2].replace("www.", ""))}</a>'
        for u in subj.get("urls") or [])
    sat = (f' <a class="noprint" href="{_sat_url(ll["latitude"], ll["longitude"])}"'
           f' target="_blank" rel="noopener">satellite view</a>' if ll else "")

    gv_html = ""
    if gv_value:
        ratio = (f' · asking is <b>{asking / gv_value:.2f}&times;</b> GV'
                 if asking else "")
        gv_html = (f'<div style="margin-top:.5rem">Municipal GV '
                   f'<b>{_fmt_r(gv_value)}</b> '
                   f'<span class="meta">({_e(gv_roll)} roll)</span>{ratio}</div>')

    # ---------------- price guidance
    band_html = ""
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
    comps_html = (f"""<table><tr><th>Property</th><th>Suburb</th><th>Price</th>
<th>Size</th><th>R/m²</th><th>Beds</th><th>Status</th><th>Price move</th>
<th>Similar</th></tr>{comp_rows}</table>""" if comp_rows
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
<table><tr><th>Property</th><th>Status</th><th>Last price</th>
<th>Delisted</th><th>DOM</th><th>Total cut</th></tr>{off_rows}</table>"""

    # ---------------- internal pitch block
    pitch_html = ""
    if score_row and (score_row["pitch_angle"] or score_row["reasoning"]):
        tier_badge = (f'<span class="tier {_e(score_row["tier"])}">'
                      f'{_e(score_row["tier"]).upper()}</span> '
                      f'<b>{score_row["prospect_score"]}</b>'
                      if score_row["tier"] else "")
        pitch_html = f"""<div class="internal">
<span class="tag">Internal — not for the seller · pitch angle</span>
<div style="margin-bottom:.4rem">{tier_badge}</div>
{f'<div style="font-size:.9rem;margin-bottom:.4rem">{_e(score_row["pitch_angle"])}</div>' if score_row["pitch_angle"] else ''}
{f'<div class="meta">{_e(score_row["reasoning"])}</div>' if score_row["reasoning"] else ''}
</div>"""

    agencies = ", ".join(subj.get("agencies") or []) or "—"
    beds = _fmt_num(subj.get("beds"))
    baths = _fmt_num(subj.get("baths"))

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
<div style="display:flex;gap:1.4rem;flex-wrap:wrap">
  {photo}
  <div style="flex:1;min-width:260px">
    <div class="price" style="font-size:1.6rem">{_fmt_r(asking)}</div>
    <div style="margin-top:.35rem">{beds} bed · {baths} bath
      {(' · ' + ' · '.join(size_bits)) if size_bits else ''}</div>
    <div style="margin-top:.35rem">{dom_txt}</div>
    <div style="margin-top:.35rem" class="meta">Marketed by: {_e(agencies)}</div>
    <div class="portals" style="margin-top:.45rem;display:flex;gap:.3rem;flex-wrap:wrap">{portals}{sat}</div>
    {gv_html}
    <div style="margin-top:.6rem">{hist_rows}</div>
  </div>
</div>

<h2>Price guidance</h2>
{band_html}
{f'<ul style="font-size:.78rem;color:#b0b0b8;line-height:1.6;padding-left:1.2rem;margin-top:.7rem">{notes_html}</ul>' if notes_html else ''}

<h2>Comparable properties</h2>
{comps_html}

{f'<h2>Suburb snapshot — {_e(subj.get("suburb") or slug)}</h2><div class="stats">{stat_bits}</div>' if stat_bits else ''}

{off_html}

{pitch_html}
{_owner_block(conn, group_id)}
</main>"""

    own_fields = [f for f in owners.FIELDS if f != "raw"]
    script = (_OWNER_JS
              .replace("__GID__", str(group_id))
              .replace("__OWN_FIELDS__", json.dumps(own_fields)))
    title = f"CMA — {subj.get('title') or group_id}"
    return _page(title, body, script=script)
