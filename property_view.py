"""The full-page property dossier: /property/<listing_key>.

The SvelteKit route ui/src/routes/property/[...key] is not prerendered (a
listing key is data, not a file), so the page itself is the 200.html SPA
shell, which reads the real URL — the same arrangement /leads/properties/<gid>
uses. Everything the page shows that the prospect row (GET
/api/prospect/<key>) does not already carry comes from two read-only calls
here:

  GET /api/property/<key>/extra   every member listing of the property group
                                  with agent, dates and lifecycle; the price
                                  history; stored contacts and the group's
                                  activity log.
  GET /api/property/<key>/photos  the gallery: every member's hero, then the
                                  photos on the cached listing pages; ?live=1
                                  may fetch one page when none is cached.
  GET /api/property/<key>/parcel  the resolved erf's outline (WGS84 rings)
                                  from the City of Cape Town cadastre, or the
                                  provincial one outside the metro — one
                                  lazy ArcGIS call, remembered in memory.

Auth is the app-wide before_request in webapp.py; nothing here writes.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import threading

import requests
from flask import Blueprint, jsonify, redirect, send_from_directory

import config
import db

bp = Blueprint("property_view", __name__)

_UI_BUILD = os.path.join(config.ROOT, "ui", "build")

# Gallery size cap. Portal pages also carry "similar listings" thumbnails;
# a listing's own stated photo_count trims most of those, this trims the rest.
_MAX_PHOTOS = 40


# ------------------------------------------------------------------ pages

@bp.get("/property")
def property_index():
    return redirect("/prospects")


@bp.get("/property/<path:_key>")
def property_page(_key):
    # Never prerendered: the SPA shell reads the real URL (see module doc).
    return send_from_directory(_UI_BUILD, "200.html")


# ------------------------------------------------------------------- data

def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def _members(conn, listing_key: str) -> tuple[str | None, list[dict]]:
    """(group id as the rest of the app spells it, member listing rows)."""
    g = conn.execute("SELECT group_id FROM property_groups WHERE listing_key = ?",
                     (listing_key,)).fetchone()
    try:
        has_cycle = bool(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'listing_lifecycle'").fetchone())
    except Exception:                                   # noqa: BLE001
        has_cycle = False
    cycle_cols = (", ll.status AS lifecycle, ll.delisted_at, ll.relisted_at,"
                  " ll.days_on_market AS lifecycle_dom, ll.likely_sold"
                  if has_cycle else "")
    cycle_join = (" LEFT JOIN listing_lifecycle ll ON ll.listing_key = l.listing_key"
                  if has_cycle else "")
    cols = ("l.listing_key, l.source, l.source_id, l.url, l.price_zar, l.agency,"
            " l.agent_name, l.listing_date, l.first_seen, l.last_seen,"
            " l.photo_count, l.photo_url, l.under_offer, l.price_reduced,"
            " l.mandate_explicit, l.title" + cycle_cols)
    if g and g["group_id"] is not None:
        rows = _rows(conn.execute(
            f"SELECT {cols} FROM listings l{cycle_join} WHERE l.listing_key IN "
            "(SELECT listing_key FROM property_groups WHERE group_id = ?)"
            " ORDER BY l.first_seen", (g["group_id"],)))
        return str(g["group_id"]), rows
    rows = _rows(conn.execute(
        f"SELECT {cols} FROM listings l{cycle_join} WHERE l.listing_key = ?",
        (listing_key,)))
    return (f"solo-{listing_key}" if rows else None), rows


def _cached_html(source: str, url: str) -> str | None:
    """The listing page from the crawl cache, whatever its age (CDN image
    URLs are stable). Never touches the network."""
    import hashlib
    digest = hashlib.sha256(url.encode()).hexdigest()[:32]
    base = os.path.join(config.CACHE_DIR, source, digest + ".html")
    for path, opener in ((base + ".gz", gzip.open), (base, open)):
        try:
            with opener(path, "rt", encoding="utf-8") as f:
                return f.read()
        except Exception:                               # noqa: BLE001
            continue
    return None


# Page furniture the generic image scrape picks up: favicons and theme art,
# agency documents, and anything that is plainly an icon by its size tag.
_JUNK = re.compile(r"/theme-settings/|/documents/|/undefined/|_t_w_(?:16|32|48|64|96|180)_h_|"
                   r"logo|icon|avatar|placeholder", re.I)
# Prop Data CDNs (many portals share one) publish each photo at several
# sizes: <id>_t_w_320_h_240.jpg, <id>_t_c_w_1200_h_630.jpg … one per photo.
_VARIANT = re.compile(r"_t(?:_c)?_w_(\d+)_h_\d+(?=\.\w+(?:$|\?))")


def _clean(urls: list[str]) -> list[str]:
    best: dict[str, tuple[int, str]] = {}
    order: list[str] = []
    for u in urls:
        if _JUNK.search(u):
            continue
        m = _VARIANT.search(u)
        base = _VARIANT.sub("", u) if m else u
        w = int(m.group(1)) if m else 0
        # the biggest copy up to 1600 px; a bare original beats nothing
        score = w if w <= 1600 else 1
        if base not in best:
            order.append(base)
            best[base] = (score, u)
        elif score > best[base][0]:
            best[base] = (score, u)
    return [best[b][1] for b in order]


def _gallery(members: list[dict], live: bool = False) -> tuple[list[dict], bool]:
    """(photos, complete). Every member's hero first, so the gallery opens on
    the best shot of each portal, then each cached page's own gallery,
    richest page first. With `live`, ONE page — the richest member on an
    enabled portal — may be fetched when nothing is cached, through the
    crawler's own fetcher (its throttle, its cache, one fetch per portal at
    a time), the same trade /api/photo already makes for a thumbnail."""
    import photos
    out, seen = [], set()

    def add(url, m):
        key = _VARIANT.sub("", url or "")
        if url and url != photos.NO_PHOTO and key not in seen:
            seen.add(key)
            out.append({"url": url, "source": m["source"],
                        "listing_key": m["listing_key"]})

    for m in members:
        add((m.get("photo_url") or "").strip(), m)
    found_page = False
    ranked = sorted(members, key=lambda m: -(m.get("photo_count") or 0))
    for m in ranked:
        if len(out) >= _MAX_PHOTOS:
            break
        html = _cached_html(m["source"], m["url"])
        if html:
            found_page = True
            _add_page(photos, m, html, add)
    if live and not found_page:
        import httpclient
        for m in ranked:
            src = m["source"]
            if not config.SOURCES.get(src, {}).get("enabled") or src not in photos._fetch_locks:
                continue
            try:
                with photos._fetch_locks[src]:
                    html = httpclient.Fetcher(src).get(m["url"])
            except Exception:                           # noqa: BLE001
                html = None
            if html:
                found_page = True
                _add_page(photos, m, html, add)
            break                                       # one live fetch at most
    return out[:_MAX_PHOTOS], found_page


def _add_page(photos, m, html, add):
    try:
        urls = photos.extract(m["source"], html)
    except Exception:                                   # noqa: BLE001
        return
    cap = m.get("photo_count") or 24
    for u in _clean(urls)[:max(cap, 1)]:
        add(u, m)


@bp.get("/api/property/<path:listing_key>/photos")
def api_property_photos(listing_key):
    """The gallery. ?live=1 allows the one page fetch described above."""
    from flask import request
    with db.connect() as conn:
        _gid, members = _members(conn, listing_key)
    if not members:
        return jsonify({"error": "not_found"}), 404
    photos_, complete = _gallery(members, live=request.args.get("live") == "1")
    return jsonify({"photos": photos_, "from_pages": complete})


@bp.get("/api/property/by-group/<gid>")
def api_property_by_group(gid):
    """The listing key the property page opens for a group id — for callers
    that only hold the group (a chat attachment, Mia). The member the prospect
    list itself shows: most photos, then the longest description. Always 200;
    `listing_key` is null for an unknown group."""
    if gid.startswith("solo-"):
        return jsonify({"listing_key": gid[5:]})
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT l.listing_key, l.photo_count, length(l.description) AS dl"
            " FROM listings l JOIN property_groups g ON g.listing_key = l.listing_key"
            " WHERE CAST(g.group_id AS TEXT) = ?", (str(gid),)).fetchall()
    if not rows:
        return jsonify({"listing_key": None})
    best = max(rows, key=lambda m: ((m["photo_count"] or 0), (m["dl"] or 0)))
    return jsonify({"listing_key": best["listing_key"]})


@bp.get("/api/property/capabilities")
def api_property_capabilities():
    """What the owner & deed section can offer on this server: whether the
    agents blueprint (stream C, /api/agent/tasks) is registered, and whether
    a LOOM token is on file. Asked once, so the page never probes a route
    that is not there."""
    from flask import current_app
    import loom
    agents = any(str(r.rule).startswith("/api/agent/tasks")
                 for r in current_app.url_map.iter_rules())
    try:
        tok = loom.token_status()
    except Exception:                                   # noqa: BLE001
        tok = {"present": False}
    return jsonify({"agents": agents, "loom": bool(tok.get("present")),
                    "loom_captured_at": tok.get("captured_at")})


@bp.get("/api/property/<path:listing_key>/extra")
def api_property_extra(listing_key):
    with db.connect() as conn:
        gid, members = _members(conn, listing_key)
        if not members:
            return jsonify({"error": "not_found"}), 404
        keys = [m["listing_key"] for m in members]
        qs = ",".join("?" * len(keys))
        try:
            history = _rows(conn.execute(
                f"SELECT listing_key, price_zar, observed_at FROM price_history"
                f" WHERE listing_key IN ({qs}) ORDER BY observed_at", keys))
        except Exception:                               # noqa: BLE001
            history = []
        contacts, activities = [], []
        try:
            contacts = _rows(conn.execute(
                "SELECT id, role, name, phone, email, company, provider"
                " FROM contacts WHERE group_id = ? ORDER BY id", (gid,)))
        except Exception:                               # noqa: BLE001
            pass
        try:
            activities = _rows(conn.execute(
                "SELECT id, kind, payload, occurred_at, actor FROM activities"
                " WHERE group_id = ? ORDER BY occurred_at DESC, id DESC LIMIT 40",
                (gid,)))
            for a in activities:
                try:
                    a["payload"] = json.loads(a["payload"] or "{}")
                except ValueError:
                    a["payload"] = {}
        except Exception:                               # noqa: BLE001
            pass
    # Which book the row lives in, so the page asks /api/prospect/<key>
    # the right way first: the rent book, or the sole-inclusive sale book
    # when a member was scored as a sole mandate.
    try:
        with db.connect() as conn:
            lt = conn.execute("SELECT listing_type FROM listings WHERE listing_key = ?",
                              (listing_key,)).fetchone()
            sole = conn.execute(
                f"SELECT 1 FROM scores WHERE sellable = 0 AND listing_key IN ({qs})",
                keys).fetchone()
    except Exception:                                   # noqa: BLE001
        lt, sole = None, None
    book = {"type": (lt["listing_type"] if lt else None) or "sale", "sole": bool(sole)}
    for m in members:
        m["has_photo"] = (m.pop("photo_url", None) or "-").strip() not in ("", "-")
    return jsonify({"group_id": gid, "book": book, "listings": members,
                    "price_history": history,
                    "contacts": contacts, "activities": activities})


# ----------------------------------------------------------------- parcel

_parcel_cache: dict[tuple, dict | None] = {}
_parcel_lock = threading.Lock()


def _arcgis_rings(url: str, lat: float, lng: float) -> list | None:
    params = {
        "where": "1=1",
        "geometry": json.dumps({"x": lng, "y": lat, "spatialReference": {"wkid": 4326}}),
        "geometryType": "esriGeometryPoint", "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
        "returnGeometry": "true", "outSR": "4326", "geometryPrecision": "6",
        "resultRecordCount": "3", "f": "json",
    }
    r = requests.get(url, params=params, timeout=12)
    r.raise_for_status()
    data = r.json()
    for f in data.get("features") or []:
        rings = (f.get("geometry") or {}).get("rings")
        if rings:
            # ArcGIS rings are [x=lng, y=lat]; Leaflet wants [lat, lng].
            return [[[pt[1], pt[0]] for pt in ring] for ring in rings]
    return None


@bp.get("/api/property/<path:listing_key>/parcel")
def api_property_parcel(listing_key):
    import erf
    with db.connect() as conn:
        row = conn.execute(
            "SELECT erf_number, latitude AS erf_lat, longitude AS erf_lng, status"
            " FROM erf_lookup WHERE listing_key = ?", (listing_key,)).fetchone()
        if row is None or row["erf_lat"] is None:
            # erf resolution is written per group; any member speaks for all
            row = conn.execute(
                "SELECT e.erf_number, e.latitude AS erf_lat, e.longitude AS erf_lng,"
                " e.status FROM erf_lookup e"
                " JOIN property_groups p ON p.listing_key = e.listing_key"
                " WHERE p.group_id = (SELECT group_id FROM property_groups"
                "                     WHERE listing_key = ?)"
                " AND e.latitude IS NOT NULL LIMIT 1", (listing_key,)).fetchone() or row
    if not row or row["erf_lat"] is None or row["status"] not in ("ok", "confirmed", "check"):
        return jsonify({"rings": None, "reason": "no_erf"})
    key = (round(row["erf_lat"], 6), round(row["erf_lng"], 6))
    with _parcel_lock:
        if key in _parcel_cache:
            return jsonify({"rings": _parcel_cache[key], "erf": row["erf_number"]})
    rings = None
    for url in (erf.PARCELS_URL, erf.WC_PARCELS_URL):
        try:
            rings = _arcgis_rings(url, row["erf_lat"], row["erf_lng"])
        except Exception:                               # noqa: BLE001
            rings = None
        if rings:
            break
    with _parcel_lock:
        if len(_parcel_cache) > 2000:
            _parcel_cache.clear()
        _parcel_cache[key] = rings
    return jsonify({"rings": rings, "erf": row["erf_number"]})
