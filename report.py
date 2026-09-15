"""Ranked HTML prospect report.

By default this shows only properties Oblivion can actually win business on —
anything established as a live sole/exclusive mandate is filtered out rather
than merely ranked low. Pass include_sole=True (CLI: `report --all`) to review
what was excluded and why.
"""

from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime

import lifecycle
import scorer
from sources.base import canonical_agency

QUERY = """
SELECT l.*, s.prospect_score, s.luxury_fit, s.open_mandate_confidence,
       s.marketing_weakness, s.tier, s.reasoning, s.pitch_angle, s.red_flags,
       s.scored_by, s.mandate_verdict, s.sellable, s.mandate_expiry_note,
       g.group_id, g.agency_count, g.source_count, g.match_evidence,
       lc.status AS lifecycle_status, lc.delisted_at, lc.relisted_at,
       lc.days_on_market AS crawl_dom
FROM listings l
JOIN scores s ON s.listing_key = l.listing_key
JOIN property_groups g ON g.listing_key = l.listing_key
LEFT JOIN listing_lifecycle lc ON lc.listing_key = l.listing_key
-- rentals are a separate book: not mandates to win, never scored, never here
WHERE l.listing_type = 'sale'
-- already-prospected properties (per the team's tracker) are out, including
-- sibling listings of the same physical property on other portals
  AND NOT EXISTS (
        SELECT 1 FROM property_groups g2
        JOIN listings l2 ON l2.listing_key = g2.listing_key
        JOIN tracker t2 ON t2.listing_number = l2.source_id
        WHERE g2.group_id = g.group_id
          AND l2.source = 'property24' AND t2.prospected = 1)
ORDER BY s.prospect_score DESC, l.price_zar DESC
"""

TIER_COLORS = {"hot": "#c0392b", "warm": "#d68910", "cold": "#6b6b73"}
MANDATE_COLORS = {
    "open": "#1e8449", "probably_open": "#148f77", "unknown": "#5d5d66",
    "probably_sole": "#a04000", "sole": "#922b21",
}


def _fmt_price(p):
    return f"R {p:,.0f}".replace(",", " ") if p else "POA"


def _collect(conn: sqlite3.Connection, include_sole: bool):
    """One row per physical property, with every portal listing attached."""
    rows = conn.execute(QUERY).fetchall()
    groups: dict[int, list] = {}
    for r in rows:
        groups.setdefault(r["group_id"], []).append(r)

    out = []
    for members in groups.values():
        best = max(members, key=lambda m: (m["photo_count"] or 0,
                                           len(m["description"] or "")))
        if not include_sole and best["sellable"] == 0:
            continue
        agencies = sorted({m["agency"].strip() for m in members
                           if m["agency"] and m["agency"].strip()})
        # Distinct *brands* decide whether this counts as multi-agency proof.
        brands = {b for b in (canonical_agency(m["agency"]) for m in members) if b}
        # Proof provenance: when the open-mandate claim rests on multiple
        # brands, show how recently EACH brand's listing was confirmed live —
        # the proof is only as fresh as its stalest brand.
        proof = []
        if len(brands) > 1:
            freshest: dict[str, datetime] = {}
            for m in members:
                b = canonical_agency(m["agency"])
                seen = scorer._parse_date(m["last_seen"])
                if b and seen and (b not in freshest or seen > freshest[b]):
                    freshest[b] = seen
            now = scorer._utcnow()
            proof = sorted(
                ((b, (now - t).total_seconds() / 3600.0)
                 for b, t in freshest.items()), key=lambda x: -x[1])
        out.append({"best": best, "members": members, "agencies": agencies,
                    "brand_count": len(brands), "proof": proof})
    out.sort(key=lambda g: (-(g["best"]["prospect_score"] or 0),
                            -(g["best"]["price_zar"] or 0)))
    return out


def _erf_line(er) -> str:
    """CMA/Lightstone-ready line: the resolved parcel, or where the hunt is."""
    if er is None or not er["status"]:
        return ""
    st = er["status"]
    if st in ("ok", "confirmed", "check"):
        erf = er["erf_number"] + (f"/{er['portion']}" if er["portion"] else "")
        area = f" · {er['parcel_area_m2']:.0f} m²" if er["parcel_area_m2"] else ""
        note = (f'<div class="note">verify: {html.escape(er["note"])}</div>'
                if st == "check" and er["note"] else "")
        return (f'<div class="erfline"><b>ERF {html.escape(erf)}</b> · '
                f'{html.escape(er["official_address"] or "")} · '
                f'{html.escape(er["official_suburb"] or "")}{area}{note}</div>')
    if st == "candidates":
        try:
            n = len(json.loads(er["candidates"] or "[]"))
        except (ValueError, TypeError):
            n = 0
        return (f'<div class="erfline cand">{n} candidate erven — '
                'run AI locate on the dashboard</div>')
    return (f'<div class="erfline none">{html.escape(er["note"] or st)}</div>')


def _age_label(hours: float) -> str:
    return f"{hours:.0f}h" if hours < 48 else f"{hours / 24.0:.0f}d"


def _deal_strip(members, cuts: dict) -> str:
    """The deal signals the DB already held but the report never showed."""
    parts = []
    if any(m["under_offer"] for m in members):
        parts.append('<b class="uo">UNDER OFFER</b>')
    pct = max((cuts.get(m["listing_key"], {}).get("total_cut_pct", 0.0)
               for m in members), default=0.0)
    moves = max((cuts.get(m["listing_key"], {}).get("price_changes", 0)
                 for m in members), default=0)
    if pct > 0:
        parts.append(f"price cut {pct:.1f}%"
                     + (f" over {moves} moves" if moves > 1 else ""))
    elif any(m["price_reduced"] for m in members):
        parts.append("price reduced")

    listed = None
    for m in members:
        dt = scorer._parse_date(m["listing_date"])
        if dt and (listed is None or dt < listed):
            listed = dt
    days, floor = ((datetime.now() - listed).days, "") if listed else (None, "")
    if days is None:
        crawl = max((m["crawl_dom"] or 0 for m in members), default=0)
        if crawl >= 1:
            days, floor = int(crawl), "+"    # first-sighting floor, not exact
    if days and days >= 30:
        parts.append(f"{days}{floor}d on market")

    rel = next((m for m in members if m["lifecycle_status"] == "relisted"), None)
    if rel:
        gone = scorer._parse_date(rel["delisted_at"])
        back = scorer._parse_date(rel["relisted_at"])
        gap = (f" after {(back - gone).days}d off-market"
               if gone and back else "")
        parts.append(f"relisted{gap} — possible failed mandate")
    return f'<div class="deal">{" · ".join(parts)}</div>' if parts else ""


def generate(conn: sqlite3.Connection, out_path: str = "prospects.html",
             include_sole: bool = False) -> str:
    lifecycle.ensure_table(conn)     # the LEFT JOIN needs the table to exist
    cuts = scorer.price_cut_history(conn)
    entries = _collect(conn, include_sole)
    erf_rows = {r["listing_key"]: r
                for r in conn.execute("SELECT * FROM erf_lookup")}
    erf_ready = len({r["group_id"] for r in erf_rows.values()
                     if r["status"] in ("ok", "check", "confirmed")})
    excluded = conn.execute(
        "SELECT COUNT(DISTINCT g.group_id) FROM scores s"
        " JOIN property_groups g ON g.listing_key = s.listing_key"
        " WHERE s.sellable = 0").fetchone()[0]

    developments = conn.execute(
        "SELECT COUNT(DISTINCT g.group_id) FROM listings l"
        " JOIN property_groups g ON g.listing_key = l.listing_key"
        " WHERE l.is_development = 1").fetchone()[0]
    hot = sum(1 for e in entries if e["best"]["tier"] == "hot")
    multi = sum(1 for e in entries if e["brand_count"] > 1)

    body_rows = []
    for e in entries:
        r, members, agencies = e["best"], e["members"], e["agencies"]
        tier = r["tier"] or "cold"
        verdict = r["mandate_verdict"] or "unknown"
        colour = TIER_COLORS.get(tier, "#6b6b73")
        mcolour = MANDATE_COLORS.get(verdict, "#5d5d66")

        portals = " ".join(
            f'<a class="portal" href="{html.escape(m["url"])}" target="_blank" '
            f'rel="noopener">{html.escape(m["source"])}</a>' for m in members)

        if e["brand_count"] > 1:
            agency_html = (f'<span class="badge open">{e["brand_count"]} agencies</span>'
                           f'<div class="meta">{html.escape(", ".join(agencies))}</div>')
        else:
            agency_html = f'<div class="meta">{html.escape(agencies[0] if agencies else "—")}</div>'

        note = r["mandate_expiry_note"] or ""
        evidence = ""
        try:
            ev = json.loads(r["match_evidence"] or "[]")
            if ev:
                evidence = f'<div class="ev">matched: {html.escape("; ".join(ev[:2]))}</div>'
        except (ValueError, TypeError):
            pass

        deal_html = _deal_strip(members, cuts)
        proof_html = ""
        if e["proof"]:
            worst = e["proof"][0][1]
            cls = "proof stale" if worst > 72 else "proof"
            seen = " · ".join(f"{html.escape(b)} {_age_label(h)} ago"
                              for b, h in e["proof"])
            proof_html = f'<div class="{cls}">proof last seen: {seen}</div>'

        beds = f'{int(r["bedrooms"])} bed' if r["bedrooms"] else ""
        addr = html.escape(r["street_address_raw"] or r["street_address"] or "")
        erf_html = _erf_line(erf_rows.get(r["listing_key"]))
        photo = ""
        purl = next((m["photo_url"] for m in members
                     if m["photo_url"] and m["photo_url"] != "-"), None)
        if purl:
            photo = (f'<a href="{html.escape(r["url"])}" target="_blank" '
                     f'rel="noopener" tabindex="-1"><img class="thumb" '
                     f'loading="lazy" src="{html.escape(purl)}" alt=""></a>')
        body_rows.append(f"""
        <tr>
          <td><span class="tier" style="background:{colour}">{tier.upper()}</span>
              <div class="score">{r["prospect_score"]}</div>
              <div class="meta">{html.escape((r["scored_by"] or "").split(":")[0])}</div></td>
          <td class="prop"><div class="propwrap">{photo}<div>
              <a href="{html.escape(r["url"])}" target="_blank" rel="noopener">
                {html.escape(r["title"] or r["source_id"])}</a>
              {'<span class="devbadge">DEVELOPMENT</span>' if r["is_development"] else ''}
              <div class="meta">{html.escape(r["suburb"] or "")}
                {' · ' + html.escape(r["property_type"]) if r["property_type"] else ''}
                {' · ' + beds if beds else ''}
                {' · ' + str(r["photo_count"]) + ' photos' if r["photo_count"] else ''}</div>
              {f'<div class="meta addr">{addr}</div>' if addr else ''}
              {erf_html}
              <div class="portals">{portals}</div>
              {evidence}{deal_html}</div></div></td>
          <td class="price">{_fmt_price(r["price_zar"])}</td>
          <td><span class="mv" style="background:{mcolour}">{verdict.replace("_", " ")}</span>
              {agency_html}
              {proof_html}
              {f'<div class="note">{html.escape(note)}</div>' if note else ''}</td>
          <td class="nums">{r["luxury_fit"]} / {r["open_mandate_confidence"]} / {r["marketing_weakness"]}</td>
          <td class="small">{html.escape(r["pitch_angle"] or r["reasoning"] or "")}
              {f'<div class="flag">{html.escape(r["red_flags"])}</div>' if r["red_flags"] else ''}</td>
        </tr>""")

    doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Oblivion Estates — Prospects</title>
<style>
 :root {{ color-scheme: dark; }}
 body {{ font-family: -apple-system, BlinkMacSystemFont, Helvetica, sans-serif;
        margin: 0; background:#0d0d0f; color:#e8e8e8; }}
 header {{ padding: 1.6rem 2rem 1rem; border-bottom:1px solid #26262b; }}
 h1 {{ font-weight: 300; letter-spacing: .25em; font-size: 1.05rem; margin:0 0 .8rem; }}
 .stats {{ display:flex; gap:2rem; flex-wrap:wrap; }}
 .stat b {{ display:block; font-size:1.5rem; font-weight:650; color:#e8c47a; }}
 .stat span {{ font-size:.7rem; color:#888; text-transform:uppercase; letter-spacing:.12em; }}
 .wrap {{ padding: 1rem 1.4rem 3rem; overflow-x:auto; }}
 table {{ border-collapse: collapse; width: 100%; min-width: 1000px; }}
 th, td {{ text-align:left; padding:.65rem .8rem; border-bottom:1px solid #222;
          vertical-align: top; font-size:.85rem; }}
 th {{ color:#888; font-size:.68rem; text-transform:uppercase; letter-spacing:.12em;
      position:sticky; top:0; background:#0d0d0f; }}
 a {{ color:#e8c47a; text-decoration:none; }}
 a:hover {{ text-decoration:underline; }}
 .tier {{ color:#fff; font-size:.6rem; padding:2px 6px; border-radius:3px; letter-spacing:.08em; }}
 .score {{ font-size:1.35rem; font-weight:650; line-height:1.3; }}
 .meta {{ color:#8b8b93; font-size:.73rem; margin-top:.15rem; }}
 .addr {{ color:#6e6e77; font-style:italic; }}
 .price {{ white-space:nowrap; font-weight:600; }}
 .nums {{ white-space:nowrap; color:#bbb; }}
 .prop {{ max-width:38rem; }}
 .propwrap {{ display:flex; gap:.65rem; }}
 .propwrap > div {{ min-width:0; }}
 .thumb {{ width:108px; height:80px; object-fit:cover; border-radius:5px; flex:none;
          background:#1a1a1f; border:1px solid #2c2c33; }}
 .small {{ color:#9a9aa2; font-size:.78rem; max-width:24rem; }}
 .badge.open {{ background:#1e8449; color:#fff; padding:2px 6px; border-radius:3px; font-size:.65rem; }}
 .mv {{ color:#fff; padding:2px 7px; border-radius:3px; font-size:.65rem; letter-spacing:.04em; }}
 .portals {{ margin-top:.35rem; display:flex; gap:.3rem; flex-wrap:wrap; }}
 .portal {{ font-size:.62rem; background:#1c1c22; border:1px solid #32323a;
           padding:1px 6px; border-radius:10px; color:#a9a9b4; }}
 .ev {{ color:#5f7f6a; font-size:.66rem; margin-top:.3rem; }}
 .erfline {{ margin-top:.35rem; font-size:.72rem; color:#c8b07e; background:#16140e;
            border:1px solid #3a3320; border-radius:5px; padding:.3rem .5rem;
            display:inline-block; }}
 .erfline b {{ color:#e8c47a; }}
 .erfline.cand {{ color:#9a9aa2; background:#131318; border-color:#2c2c33; }}
 .erfline.none {{ color:#666; background:transparent; border-style:dashed;
                 border-color:#26262b; }}
 .note {{ color:#d6a95a; font-size:.7rem; margin-top:.35rem; }}
 .deal {{ color:#c98f4e; font-size:.7rem; margin-top:.35rem; }}
 .deal .uo {{ background:#7a2f2a; color:#fff; padding:1px 5px; border-radius:3px;
             font-size:.62rem; letter-spacing:.05em; }}
 .proof {{ color:#5f7f6a; font-size:.66rem; margin-top:.3rem; }}
 .proof.stale {{ color:#b08a45; }}
 .flag {{ color:#b4645a; font-size:.7rem; margin-top:.3rem; }}
 .devbadge {{ background:#4a3a6b; color:#fff; padding:1px 6px; border-radius:3px;
             font-size:.6rem; letter-spacing:.05em; margin-left:.3rem; }}
 .empty {{ padding:4rem; text-align:center; color:#666; }}
</style></head><body>
<header>
 <h1>OBLIVION ESTATES — PROSPECT ENGINE</h1>
 <div class="stats">
   <div class="stat"><b>{len(entries)}</b><span>sellable properties</span></div>
   <div class="stat"><b>{hot}</b><span>hot</span></div>
   <div class="stat"><b>{multi}</b><span>multi-agency (open proof)</span></div>
   <div class="stat"><b>{erf_ready}</b><span>erf resolved (CMA-ready)</span></div>
   <div class="stat"><b>{excluded}</b><span>excluded: sole mandate</span></div>
   <div class="stat"><b>{developments}</b><span>excluded: developments</span></div>
   <div class="stat"><b>{datetime.now():%d %b %H:%M}</b><span>generated</span></div>
 </div>
</header>
<div class="wrap">
{'<div class="empty">No prospects yet — run a scrape.</div>' if not entries else f'''
<table>
<tr><th>Score</th><th>Property</th><th>Price</th><th>Mandate / agencies</th>
<th>Lux / Open / Weak</th><th>Pitch angle</th></tr>
{''.join(body_rows)}
</table>'''}
</div></body></html>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return out_path
