"""Street address / erf number resolution against the public cadastre.

The City of Cape Town publishes its full cadastre (every land parcel with erf
number, official address and official suburb) as an open ArcGIS feature
service. That turns the CMA/Lightstone prep problem — "what is the address and
erf number of this listing?" — into a lookup:

  1. address    portal published a street address -> parcel by street + number
  2. point      portal leaked coordinates -> parcel under the (fuzzed) pin,
                sanity-checked against the advertised erf size
  3. size       address withheld -> every parcel in the suburb whose size is
                within ERF_SIZE_TOL of the advertised erf; usually collapses a
                whole suburb to a handful of candidates
  4. AI locate  (on demand, dashboard button) a vision model reads the listing
                photos + description and ranks the size candidates against
                satellite crops of each parcel

Erf numbers, parcel boundaries and official addresses are public record; the
owner lookup itself stays in the licensed deeds tool (CMA/Lightstone) — this
module's job is to hand it the exact search key.

Coverage: two cadastres, chosen per suburb. The City of Cape Town service
stops at the metro boundary, so Stellenbosch, the Winelands, the Overberg,
the Garden Route and the West Coast fall through to the Western Cape
provincial cadastre, which covers the whole province. The provincial layer
publishes no street fields, so outside the metro resolution runs off the map
pin and the erf size rather than the address — steps 2 and 3 above, not 1.
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import sqlite3
import threading
import time
import urllib.parse

import requests

import config
import db

PARCELS_URL = ("https://services6.arcgis.com/nyYfO9SxHU2ChQd9/arcgis/rest/"
               "services/Property/FeatureServer/0/query")

# The Western Cape's own cadastre (AfriGIS Erven, via the provincial spatial
# data warehouse). It covers the whole province — Saldanha Bay, Overstrand,
# Stellenbosch, Knysna and the metro alike — where the City of Cape Town
# service stops at the metro boundary. That is the difference between
# resolving an erf in Langebaan and returning `no_coverage`, which is what
# most of the configured areas were getting.
#
# It is the fallback rather than the primary because it publishes no street
# fields: erf number, SG code, portion, suburb, town and area, but no address.
# CoCT's address layer stays the best first move inside the metro; everywhere
# else resolution runs off coordinates and erf size.
WC_PARCELS_URL = ("https://gis.westerncape.gov.za/server2/rest/services/"
                  "SpatialDataWarehouse/AfriGIS_PlanningCadastre/"
                  "MapServer/0/query")
# X/Y are the parcel centroid in WGS84 and are not optional: they carry the
# candidate coordinates the AI locator needs to pull a satellite crop of each
# parcel, and they anchor the area conversion in _wc_row().
WC_OUT_FIELDS = "SG_CODE,ERF_NO,PORTION,SUBURB,TOWN,S12_NAME,Shape_Area,X,Y"
WORLD_IMAGERY = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                 "World_Imagery/MapServer/export")

OUT_FIELDS = ("SG26_CODE,PRTY_NMBR,ADR_NO,ADR_NO_SFX,STR_NAME,"
              "LU_STR_NAME_TYPE,OFC_SBRB_NAME,LU_LGL_STS_DSCR,Shape__Area")

# Advertised erf sizes are usually the exact SG figure, but portals sometimes
# round or quote the floor area; a hit within ADDRESS_SIZE_TOL confirms an
# address/point match, ERF_SIZE_TOL drives candidate discovery.
ADDRESS_SIZE_TOL = 0.12
ERF_SIZE_TOL = 0.06
MAX_CANDIDATES = 40          # stored; the AI locator reads the closest few

_REQUEST_GAP = 0.25          # polite spacing between cadastre requests
_last_request = [0.0]
_req_lock = threading.Lock()

# sources/base.py normalises "Avenue" -> "ave" etc; the cadastre stores the
# type separately ("BLAIR" + "Road"), so both sides reduce to (name, type).
_TYPE_ABBREV = {
    "rd": "road", "st": "street", "ave": "avenue", "dr": "drive",
    "cres": "crescent", "cl": "close", "ln": "lane", "blvd": "boulevard",
    "pl": "place", "terr": "terrace", "sq": "square", "way": "way",
    "steps": "steps", "mews": "mews",
}


# ------------------------------------------------------------------ helpers

def _norm(s: str | None) -> str:
    """Collapse to bare uppercase alnum words: "Gordon's Bay" == "GORDONS BAY"."""
    return re.sub(r"[^A-Z0-9]+", " ", (s or "").upper()).strip()


def _compact(s: str | None) -> str:
    return _norm(s).replace(" ", "")


def _mercator_k(lat: float) -> float:
    """Web-Mercator area inflation at this latitude (Shape__Area is in 3857)."""
    return 1.0 / math.cos(math.radians(abs(lat))) ** 2


def _true_area(shape_area: float, lat: float) -> float:
    return shape_area / _mercator_k(lat)


def _suburb_matches(listing_suburb: str | None, ofc_name: str | None) -> bool:
    a, b = _norm(listing_suburb), _norm(ofc_name)
    if not a or not b:
        return False
    return a in b or b in a


def _parcel_address(attrs: dict) -> str:
    no = attrs.get("ADR_NO")
    sfx = (attrs.get("ADR_NO_SFX") or "").strip()
    name = (attrs.get("STR_NAME") or "").title()
    typ = (attrs.get("LU_STR_NAME_TYPE") or "").strip()
    num = f"{no}{sfx}" if no else ""
    return " ".join(p for p in (num, name, typ) if p)


def _centroid(geometry: dict | None) -> tuple[float | None, float | None]:
    """Bounding-box centre of the parcel outline (fine at erf scale)."""
    if not geometry:
        return None, None
    try:
        ring = geometry["rings"][0]
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return (min(ys) + max(ys)) / 2, (min(xs) + max(xs)) / 2
    except (KeyError, IndexError, TypeError):
        return None, None


def _sg26_parse(code: str | None) -> tuple[str | None, str | None]:
    """Erf and portion out of the 26-char Surveyor-General code."""
    if not code or len(code) < 20:
        return None, None
    erf = code[8:16].lstrip("0") or "0"
    portion = code[16:20].lstrip("0")
    return erf, portion or None


# ------------------------------------------------------------ cadastre client

def _query(where: str, *, geometry: dict | None = None,
           return_geometry: bool = False, limit: int = 500) -> list[dict]:
    """Query the Land Parcels layer; returns [{attrs..., 'lat','lng'}]."""
    params = {
        "where": where or "1=1",
        "outFields": OUT_FIELDS,
        "returnGeometry": "true" if return_geometry else "false",
        "resultRecordCount": str(limit),
        "f": "json",
    }
    if return_geometry:
        params["outSR"] = "4326"
        params["geometryPrecision"] = "6"
    if geometry is not None:
        params.update(geometry)

    with _req_lock:
        wait = _last_request[0] + _REQUEST_GAP - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()

    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(PARCELS_URL, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(data["error"].get("message", "arcgis error"))
            out = []
            for f in data.get("features", []):
                rec = dict(f.get("attributes") or {})
                rec["lat"], rec["lng"] = _centroid(f.get("geometry"))
                out.append(rec)
            return out
        except Exception as e:            # noqa: BLE001 - retry then surface
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"cadastre query failed: {last_err}")


def _wc_query(where: str | None = None, *, geometry: dict | None = None,
              limit: int = 500) -> list[dict]:
    """Query the provincial cadastre, returning CoCT-shaped rows.

    The two services describe the same thing with different field names, so
    the provincial rows are translated here rather than teaching the resolver
    about a second schema — everything downstream (size checks, candidate
    rows, the AI locator) then works unchanged on either source.

    One real difference has to be absorbed: the provincial layer is projected
    in UTM 34S, so its Shape_Area is already true square metres, while CoCT's
    is Web Mercator and gets divided by the latitude factor. The value is
    pre-inflated by that same factor here so `_true_area` gives the true area
    back for both.
    """
    params = {
        "outFields": WC_OUT_FIELDS,
        "returnGeometry": "false",
        "resultRecordCount": str(limit),
        "f": "json",
    }
    params["where"] = where or "1=1"
    if geometry is not None:
        params.update(geometry)

    with _req_lock:
        wait = _last_request[0] + _REQUEST_GAP - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()

    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(WC_PARCELS_URL, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(data["error"].get("message", "arcgis error"))
            return [_wc_row(f.get("attributes") or {})
                    for f in data.get("features", [])]
        except Exception as e:                # noqa: BLE001 - retry then surface
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"provincial cadastre query failed: {last_err}")


def _wc_row(a: dict) -> dict:
    """One provincial parcel in the City of Cape Town's field names."""
    lat, lng = a.get("Y"), a.get("X")
    area = a.get("Shape_Area") or 0.0
    # Undo nothing, pre-apply everything: _true_area() will divide this by the
    # Mercator factor, so multiply it in first to end up back at true m².
    inflated = area * _mercator_k(lat if lat is not None else -33.95)
    erf = str(a.get("ERF_NO") or "").strip() or None
    portion = (str(a.get("PORTION") or "").strip().lstrip("0") or None)
    return {
        "PRTY_NMBR": erf,
        "SG26_CODE": a.get("SG_CODE"),
        "OFC_SBRB_NAME": a.get("SUBURB") or a.get("TOWN"),
        "Shape__Area": inflated,
        # No street fields exist on this layer, so an address can never be
        # rendered from it; _parcel_address() returns "" and callers show the
        # suburb instead.
        "ADR_NO": None, "ADR_NO_SFX": None, "STR_NAME": None,
        "LU_STR_NAME_TYPE": None,
        "lat": lat, "lng": lng,
        "_portion": portion,
        "_town": a.get("TOWN"),
        "_municipality": a.get("S12_NAME"),
    }


def _wc_point_query(lat: float, lng: float, envelope_m: float = 0.0) -> list[dict]:
    if envelope_m:
        dlat = envelope_m / 111_320
        dlng = envelope_m / (111_320 * max(math.cos(math.radians(lat)), 0.1))
        geom = {
            "geometry": json.dumps({
                "xmin": lng - dlng, "ymin": lat - dlat,
                "xmax": lng + dlng, "ymax": lat + dlat,
                "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryEnvelope",
        }
    else:
        geom = {
            "geometry": json.dumps({"x": lng, "y": lat,
                                    "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryPoint",
        }
    geom.update({"inSR": "4326", "spatialRel": "esriSpatialRelIntersects"})
    return _wc_query(geometry=geom)


def _point_query(lat: float, lng: float, envelope_m: float = 0.0) -> list[dict]:
    if envelope_m:
        dlat = envelope_m / 111_320
        dlng = envelope_m / (111_320 * math.cos(math.radians(abs(lat))))
        geom = {
            "geometry": f"{lng - dlng},{lat - dlat},{lng + dlng},{lat + dlat}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        }
    else:
        geom = {
            "geometry": f"{lng},{lat}", "geometryType": "esriGeometryPoint",
            "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        }
    return _query("1=1", geometry=geom, return_geometry=True, limit=100)


_suburb_known: dict[str, bool] = {}


def _suburb_in_coverage(suburb: str) -> bool:
    """Is this suburb genuinely inside the City of Cape Town cadastre?

    The keyword is only the server-side filter; the decision is made on the
    names it returns. Asking "did anything come back?" is what made Paarl and
    Stellenbosch look like metro suburbs — the LIKE matched CoCT parcels
    called PAARL FARMS and STELLENBOSCH UNIV, both of which are Cape Town
    properties that merely share a word with a town 60 km away. A listing in
    the town of Stellenbosch would then have been resolved to an erf on the
    university's Cape Town holdings and handed to the deeds tool as fact.

    So the official name must actually *be* the suburb, allowing for CoCT's
    combined names ("CAMPS BAY / BAKOVEN"). Anything else belongs to the
    provincial cadastre, which covers those towns properly.
    """
    key = _suburb_key(suburb)
    if not key:
        return False
    if key not in _suburb_known:
        rows = _query(f"OFC_SBRB_NAME LIKE '%{key}%'", limit=50)
        want = _norm(suburb)
        _suburb_known[key] = any(
            want == _norm(part)
            for r in rows
            for part in str(r.get("OFC_SBRB_NAME") or "").split("/"))
    return _suburb_known[key]


def _suburb_key(suburb: str | None) -> str:
    """Longest word of the suburb name — the LIKE anchor for server-side filters."""
    words = _norm(suburb).split()
    words = [w for w in words if w not in ("THE", "BAY", "WEST", "EAST", "UPPER")]
    return max(words, key=len) if words else ""


# ------------------------------------------------------------ address parsing

_ADDR_RE = re.compile(r"^(\d+)\s*([a-z])?\s+(.+)$")


def _parse_address(addr: str) -> tuple[int, str, str, str] | None:
    """'8a blair rd' -> (8, 'a', 'blair', 'road'); type may be ''."""
    m = _ADDR_RE.match(addr.strip().lower())
    if not m:
        return None
    number = int(m.group(1))
    suffix = m.group(2) or ""
    rest = m.group(3).split()
    typ = ""
    if len(rest) > 1 and rest[-1] in _TYPE_ABBREV:
        typ = _TYPE_ABBREV[rest[-1]]
        rest = rest[:-1]
    return number, suffix, " ".join(rest), typ


def _match_street(parsed_name: str, parsed_type: str, attrs: dict) -> bool:
    """Parcel street equals the parsed one, tolerating type-in-name quirks."""
    cad_name = _compact(attrs.get("STR_NAME"))
    cad_type = _compact(attrs.get("LU_STR_NAME_TYPE"))
    want = _compact(parsed_name)
    if not cad_name or not want:
        return False
    if cad_name == want:
        return not parsed_type or not cad_type or \
            _compact(parsed_type) == cad_type
    # listing kept the type inside the name ("fourth beach rd" vs FOURTH BEACH)
    return cad_name + cad_type == want + _compact(parsed_type) or \
        cad_name == want + _compact(parsed_type)


# ------------------------------------------------------------------ resolver

def _resolution(status, method=None, parcel=None, lat_hint=-33.95, note=None,
                candidates=None):
    out = {"status": status, "method": method, "note": note,
           "erf_number": None, "portion": None, "sg26_code": None,
           "official_address": None, "official_suburb": None,
           "parcel_area_m2": None, "latitude": None, "longitude": None,
           "candidates": json.dumps(candidates) if candidates else None}
    if parcel:
        erf, portion = _sg26_parse(parcel.get("SG26_CODE"))
        out.update(
            erf_number=parcel.get("PRTY_NMBR") or erf, portion=portion,
            sg26_code=parcel.get("SG26_CODE"),
            official_address=_parcel_address(parcel),
            official_suburb=(parcel.get("OFC_SBRB_NAME") or "").title(),
            parcel_area_m2=round(_true_area(parcel["Shape__Area"],
                                            parcel.get("lat") or lat_hint), 1),
            latitude=parcel.get("lat"), longitude=parcel.get("lng"))
    return out


def _candidate_row(p: dict, lat_hint: float) -> dict:
    erf, portion = _sg26_parse(p.get("SG26_CODE"))
    return {"erf": p.get("PRTY_NMBR") or erf, "portion": portion,
            "address": _parcel_address(p),
            "suburb": (p.get("OFC_SBRB_NAME") or "").title(),
            "area_m2": round(_true_area(p["Shape__Area"],
                                        p.get("lat") or lat_hint), 1),
            "lat": p.get("lat"), "lng": p.get("lng"),
            "sg26_code": p.get("SG26_CODE")}


def _resolve_provincial(suburb, lat, lng, erf_size, lat_hint, size_ok) -> dict:
    """Resolve against the provincial cadastre (everything outside the metro).

    Mirrors the point and size layers of resolve_group(); there is no address
    layer because the provincial service publishes no street fields.
    """
    # ---- map pin
    if lat and lng:
        rows = _wc_point_query(lat, lng)
        if rows and size_ok(rows[0]):
            return _resolution("ok" if erf_size else "check", "point", rows[0],
                               lat_hint,
                               note=None if erf_size else
                               "from map pin only — no erf size to verify")
        if rows:
            # The pin sits inside a real parcel but the advertised size
            # disagrees. That is worth surfacing rather than discarding: the
            # portal's erf figure is often the rounded or the wrong one.
            p = rows[0]
            area = _true_area(p["Shape__Area"], p.get("lat") or lat_hint)
            return _resolution(
                "check", "point", p, lat_hint,
                note=f"map pin falls in erf {p.get('PRTY_NMBR')} "
                     f"({area:.0f} m²) but the listing says "
                     f"{erf_size:.0f} m² — verify")
        near = [r for r in _wc_point_query(lat, lng, envelope_m=120)
                if size_ok(r, ERF_SIZE_TOL)]
        if len(near) == 1:
            return _resolution("check", "point", near[0], lat_hint,
                               note="pin was on a neighbour; nearest "
                                    "size-matching parcel chosen — verify")
        if near:
            cands = sorted((_candidate_row(p, lat_hint) for p in near),
                           key=lambda c: abs(c["area_m2"] - (erf_size or 0))
                           )[:MAX_CANDIDATES]
            return _resolution("candidates", "point",
                               note=f"{len(near)} size-matching parcels near "
                                    "the map pin", candidates=cands,
                               lat_hint=lat_hint)

    # ---- erf-size scan of the suburb
    if erf_size and suburb:
        key = _suburb_key(suburb).replace("'", "''")
        lo = erf_size * (1 - ERF_SIZE_TOL)
        hi = erf_size * (1 + ERF_SIZE_TOL)
        # Shape_Area is true m² on this layer, so the bounds go in unscaled.
        rows = _wc_query(f"(UPPER(SUBURB) LIKE '%{key}%' OR "
                         f"UPPER(TOWN) LIKE '%{key}%') AND "
                         f"Shape_Area >= {lo:.1f} AND Shape_Area <= {hi:.1f}")
        if rows:
            cands = sorted((_candidate_row(p, lat_hint) for p in rows),
                           key=lambda c: abs(c["area_m2"] - erf_size)
                           )[:MAX_CANDIDATES]
            return _resolution(
                "candidates", "size",
                note=f"{len(rows)} parcels in {suburb} within "
                     f"±{ERF_SIZE_TOL:.0%} of {erf_size:.0f} m² "
                     "(provincial cadastre)",
                candidates=cands, lat_hint=lat_hint)
        return _resolution("no_match", "size",
                           note=f"no parcel in {suburb} within "
                                f"±{ERF_SIZE_TOL:.0%} of {erf_size:.0f} m² "
                                "(provincial cadastre)")

    return _resolution("no_data", note="no coordinates or erf size published "
                       "— sectional title? try the scheme name in the deeds "
                       "tool")


def resolve_group(members: list[dict]) -> dict:
    """Resolve one physical property (all portal listings of it) to a parcel.

    Members need: suburb, street_address, latitude, longitude, erf_size_m2.
    """
    suburb = next((m["suburb"] for m in members if m.get("suburb")), "")
    address = next((m["street_address"] for m in members
                    if m.get("street_address")), None)
    lat = next((m["latitude"] for m in members if m.get("latitude")), None)
    lng = next((m["longitude"] for m in members if m.get("longitude")), None)
    erf_size = next((m["erf_size_m2"] for m in members
                     if m.get("erf_size_m2")), None)
    lat_hint = lat or -33.95

    def size_ok(parcel, tol=ADDRESS_SIZE_TOL):
        if not erf_size:
            return True
        area = _true_area(parcel["Shape__Area"], parcel.get("lat") or lat_hint)
        return abs(area - erf_size) <= tol * erf_size

    if not _suburb_in_coverage(suburb):
        # Outside the metro the provincial cadastre takes over. It has no
        # street fields, so the address layer below is unavailable and
        # resolution runs off the map pin and the erf size.
        return _resolve_provincial(suburb, lat, lng, erf_size, lat_hint, size_ok)

    # ---- layer 1: published street address
    parsed = _parse_address(address) if address else None
    if parsed:
        number, suffix, name, typ = parsed
        first = _norm(name).split()[0].replace("'", "''") if _norm(name) else ""
        rows = _query(f"ADR_NO = {number} AND UPPER(STR_NAME) LIKE '{first}%'",
                      return_geometry=True)
        rows = [r for r in rows if _match_street(name, typ, r)]
        in_suburb = [r for r in rows if _suburb_matches(suburb,
                                                        r.get("OFC_SBRB_NAME"))]
        pool = in_suburb or rows
        if suffix:
            with_sfx = [r for r in pool
                        if (r.get("ADR_NO_SFX") or "").strip().lower() == suffix]
            pool = with_sfx or pool
        if len(pool) > 1 and erf_size:
            sized = [r for r in pool if size_ok(r)]
            pool = sized or pool
        if len(pool) == 1:
            p = pool[0]
            if not in_suburb:
                return _resolution("check", "address", p, lat_hint,
                                   note="street found outside the listed "
                                        "suburb — verify")
            if size_ok(p):
                return _resolution("ok", "address", p, lat_hint)
            return _resolution(
                "check", "address", p, lat_hint,
                note=f"parcel is {_true_area(p['Shape__Area'], lat_hint):.0f} m² "
                     f"but listing says {erf_size:.0f} m² — verify")
        if len(pool) > 1:
            cands = [_candidate_row(p, lat_hint) for p in pool[:MAX_CANDIDATES]]
            return _resolution("candidates", "address", note="address matches "
                               f"{len(pool)} parcels", candidates=cands,
                               lat_hint=lat_hint)

    # ---- layer 2: portal coordinates (pins are fuzzed -> verify by size)
    if lat and lng:
        rows = _point_query(lat, lng)
        if rows and size_ok(rows[0]):
            return _resolution("ok" if erf_size else "check", "point", rows[0],
                               lat_hint,
                               note=None if erf_size else
                               "from map pin only — no erf size to verify")
        near = [r for r in _point_query(lat, lng, envelope_m=120)
                if size_ok(r, ERF_SIZE_TOL)]
        if len(near) == 1:
            return _resolution("check", "point", near[0], lat_hint,
                               note="pin was on a neighbour; nearest "
                                    "size-matching parcel chosen — verify")
        if near:
            cands = sorted(
                (_candidate_row(p, lat_hint) for p in near),
                key=lambda c: abs(c["area_m2"] - erf_size))[:MAX_CANDIDATES]
            return _resolution("candidates", "point",
                               note=f"{len(near)} size-matching parcels near "
                                    "the map pin", candidates=cands,
                               lat_hint=lat_hint)

    # ---- layer 3: erf-size scan of the suburb
    if erf_size:
        key = _suburb_key(suburb).replace("'", "''")
        k = _mercator_k(lat_hint)
        lo = erf_size * (1 - ERF_SIZE_TOL) * k
        hi = erf_size * (1 + ERF_SIZE_TOL) * k
        rows = _query(f"OFC_SBRB_NAME LIKE '%{key}%' AND "
                      f"Shape__Area >= {lo:.1f} AND Shape__Area <= {hi:.1f}",
                      return_geometry=True)
        rows = [r for r in rows if _suburb_matches(suburb,
                                                   r.get("OFC_SBRB_NAME"))]
        if rows:
            cands = sorted(
                (_candidate_row(p, lat_hint) for p in rows),
                key=lambda c: abs(c["area_m2"] - erf_size))[:MAX_CANDIDATES]
            return _resolution(
                "candidates", "size",
                note=f"{len(rows)} parcels in {suburb} within "
                     f"±{ERF_SIZE_TOL:.0%} of {erf_size:.0f} m²",
                candidates=cands, lat_hint=lat_hint)
        return _resolution("no_match", "size",
                           note=f"no parcel in {suburb} within "
                                f"±{ERF_SIZE_TOL:.0%} of {erf_size:.0f} m²")

    return _resolution("no_data", note="no address, coordinates or erf size "
                       "published — sectional title? try the scheme name in "
                       "the deeds tool")


# ------------------------------------------------------------- bulk resolve

GROUPS_QUERY = """
SELECT l.listing_key, l.source, l.url, l.suburb, l.suburb_slug, l.title,
       l.street_address, l.latitude, l.longitude, l.erf_size_m2,
       l.photo_count, l.description, l.property_type,
       s.sellable, g.group_id
FROM listings l
LEFT JOIN scores s ON s.listing_key = l.listing_key
LEFT JOIN property_groups g ON g.listing_key = l.listing_key
"""


def _groups(conn: sqlite3.Connection, sellable_only: bool = False) -> dict:
    grouped: dict = {}
    for r in conn.execute(GROUPS_QUERY):
        gid = r["group_id"] if r["group_id"] is not None \
            else f"solo-{r['listing_key']}"
        grouped.setdefault(gid, []).append(dict(r))
    if sellable_only:
        grouped = {gid: ms for gid, ms in grouped.items()
                   if any(m.get("sellable") == 1 for m in ms)}
    return grouped


def resolve_all(conn: sqlite3.Connection | None = None, *,
                sellable_only: bool = False, force: bool = False,
                log=print, stop: threading.Event | None = None) -> dict:
    """Resolve every property group we can; write erf_lookup rows.

    Every group by default — the erf is the key to GV values, CMA comps and
    the deeds tool, so it is wanted whether or not the AI thinks the mandate
    is winnable. Pass sellable_only=True for the old, narrower sweep.
    """
    ctx = None
    if conn is None:
        ctx = db.connect()
        conn = ctx.__enter__()
    try:
        grouped = _groups(conn, sellable_only)
        done = {r["listing_key"]: r["status"] for r in
                conn.execute("SELECT listing_key, status FROM erf_lookup")}
        stats = {"groups": len(grouped), "resolved": 0, "check": 0,
                 "candidates": 0, "unresolved": 0, "skipped": 0}
        for gid, members in grouped.items():
            if stop is not None and stop.is_set():
                break
            keys = [m["listing_key"] for m in members]
            if not force and all(done.get(k) in
                                 ("ok", "check", "candidates", "confirmed")
                                 for k in keys):
                stats["skipped"] += 1
                continue
            label = members[0].get("title") or keys[0]
            try:
                res = resolve_group(members)
            except Exception as e:        # noqa: BLE001 - keep the batch going
                log(f"  erf: {label}: {type(e).__name__}: {e}")
                continue
            _write(conn, keys, gid, res)
            conn.commit()
            if res["status"] in ("ok", "confirmed"):
                stats["resolved"] += 1
                log(f"  erf {res['erf_number']:>6}  {res['official_address']}"
                    f"  ({members[0].get('suburb')})")
            elif res["status"] == "check":
                stats["check"] += 1
                log(f"  erf {res['erf_number']:>6}? {res['official_address']}"
                    f"  — {res['note']}")
            elif res["status"] == "candidates":
                stats["candidates"] += 1
                n = len(json.loads(res["candidates"] or "[]"))
                log(f"  {n:>3} candidates      {label[:60]}")
            else:
                stats["unresolved"] += 1
        return stats
    finally:
        if ctx is not None:
            ctx.__exit__(None, None, None)


def resolve_one(conn: sqlite3.Connection, listing_key: str) -> dict:
    """Force re-resolution of just the group holding listing_key.

    The per-listing "re-evaluate" button calls this after refetching the
    portal pages, so a corrected erf size (e.g. the hectare fix) or a new
    street address immediately re-runs the cadastre match without a full
    resolve_all sweep.
    """
    grouped = _groups(conn, sellable_only=False)
    for gid, members in grouped.items():
        if any(m["listing_key"] == listing_key for m in members):
            res = resolve_group(members)
            _write(conn, [m["listing_key"] for m in members], gid, res)
            conn.commit()
            return res
    raise ValueError("unknown listing")


def _write(conn, keys: list[str], gid, res: dict,
           keep_ai: bool = False) -> None:
    for k in keys:
        conn.execute(
            """INSERT INTO erf_lookup (listing_key, group_id, status, method,
                   erf_number, portion, sg26_code, official_address,
                   official_suburb, parcel_area_m2, latitude, longitude,
                   note, candidates, looked_up_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(listing_key) DO UPDATE SET
                   group_id=excluded.group_id, status=excluded.status,
                   method=excluded.method, erf_number=excluded.erf_number,
                   portion=excluded.portion, sg26_code=excluded.sg26_code,
                   official_address=excluded.official_address,
                   official_suburb=excluded.official_suburb,
                   parcel_area_m2=excluded.parcel_area_m2,
                   latitude=excluded.latitude, longitude=excluded.longitude,
                   note=excluded.note, candidates=excluded.candidates,
                   looked_up_at=datetime('now')""" +
            ("" if keep_ai else
             ", ai_status=NULL, ai_best=NULL, ai_at=NULL"),
            (k, str(gid), res["status"], res["method"], res["erf_number"],
             res["portion"], res["sg26_code"], res["official_address"],
             res["official_suburb"], res["parcel_area_m2"], res["latitude"],
             res["longitude"], res["note"], res["candidates"]))


def confirm(conn: sqlite3.Connection, listing_key: str, erf: str) -> dict:
    """User accepted a candidate — promote it to the resolved parcel."""
    row = conn.execute("SELECT group_id, candidates, ai_best FROM erf_lookup"
                       " WHERE listing_key = ?", (listing_key,)).fetchone()
    if not row:
        raise ValueError("no lookup for this listing")
    cands = json.loads(row["candidates"] or "[]")
    pick = next((c for c in cands if str(c.get("erf")) == str(erf)), None)
    if not pick:
        raise ValueError(f"erf {erf} is not among the stored candidates")
    res = {"status": "confirmed", "method": "ai_confirmed",
           "erf_number": pick["erf"], "portion": pick.get("portion"),
           "sg26_code": pick.get("sg26_code"),
           "official_address": pick["address"],
           "official_suburb": pick["suburb"],
           "parcel_area_m2": pick["area_m2"], "latitude": pick.get("lat"),
           "longitude": pick.get("lng"),
           "note": "confirmed from AI photo match",
           "candidates": row["candidates"]}
    keys = [r["listing_key"] for r in conn.execute(
        "SELECT listing_key FROM erf_lookup WHERE group_id = ?",
        (row["group_id"],))] or [listing_key]
    _write(conn, keys, row["group_id"], res, keep_ai=True)
    conn.commit()
    return res


# --------------------------------------------------------------- AI locator

AI_PHOTOS = 20               # listing photos sent to the vision model
AI_CANDIDATES = 12           # satellite crops sent to the vision model

# Ordinals as portals write them vs how the cadastre spells street names
_ORDINALS = {"1st": "first", "2nd": "second", "3rd": "third", "4th": "fourth",
             "5th": "fifth", "6th": "sixth", "7th": "seventh",
             "8th": "eighth", "9th": "ninth", "10th": "tenth"}


_suburb_streets: dict[str, list[str]] = {}


def _streets_in_suburb(suburb: str) -> list[str]:
    """Distinct cadastre street names for a suburb (cached)."""
    key = _suburb_key(suburb)
    if not key:
        return []
    if key not in _suburb_streets:
        params = {"where": f"OFC_SBRB_NAME LIKE '%{key}%'",
                  "outFields": "STR_NAME", "returnDistinctValues": "true",
                  "returnGeometry": "false", "f": "json"}
        try:
            r = requests.get(PARCELS_URL, params=params, timeout=30)
            feats = r.json().get("features", [])
            _suburb_streets[key] = sorted(
                {f["attributes"]["STR_NAME"] for f in feats
                 if f["attributes"].get("STR_NAME")})
        except Exception:                 # noqa: BLE001 - clue mining only
            return []
    return _suburb_streets[key]


def _street_candidates(suburb: str, text: str, erf_size: float | None,
                       lat_hint: float) -> tuple[list[dict], list[str]]:
    """Parcels on any street the listing text mentions by name.

    The size filter can miss the real stand (portals mis-state erf sizes), but
    when the copy says "on Geneva Drive" or "above 3rd Beach", every parcel on
    the matching street is worth showing the vision model.
    """
    low = " " + _norm(text).lower() + " "
    for abbr, word in _ORDINALS.items():
        low = low.replace(f" {abbr} ", f" {word} ")
    mentioned = [s for s in _streets_in_suburb(suburb)
                 if len(s) >= 5 and f" {s.lower()} " in low]
    out: list[dict] = []
    for name in mentioned[:3]:
        esc_name = name.replace("'", "''")
        rows = _query(f"UPPER(STR_NAME) = '{esc_name.upper()}'",
                      return_geometry=True)
        rows = [r for r in rows
                if _suburb_matches(suburb, r.get("OFC_SBRB_NAME"))]
        if erf_size:
            rows = [r for r in rows
                    if abs(_true_area(r["Shape__Area"], lat_hint) - erf_size)
                    <= 0.25 * erf_size]
        out.extend(_candidate_row(r, lat_hint) for r in rows)
    return out, mentioned

def _listing_photos(members: list[dict], log=print) -> list[str]:
    """Best-effort gallery URLs from the richest portal page (cached fetch)."""
    import photos
    for m in sorted(members, key=lambda m: -(m.get("photo_count") or 0)):
        try:
            urls = photos.for_listing(m["source"], m["url"], log=log)
        except Exception as e:            # noqa: BLE001
            log(f"  photos: {m['source']} fetch failed: {e}")
            continue
        if urls:
            return urls[:AI_PHOTOS * 2]
    return []


def _download_b64(url: str, referer: str | None = None,
                  max_bytes: int = 3_000_000) -> str | None:
    try:
        headers = {"User-Agent": config.USER_AGENT}
        if referer:
            headers["Referer"] = referer
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        if len(r.content) > max_bytes or len(r.content) < 4_000:
            return None
        mime = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
        if not mime.startswith("image/"):
            return None
        return f"data:{mime};base64,{base64.b64encode(r.content).decode()}"
    except Exception:                     # noqa: BLE001
        return None


def _satellite_b64(lat: float, lng: float, area_m2: float | None) -> str | None:
    half = max(38.0, 1.7 * math.sqrt(area_m2 or 700))
    dlat = half / 111_320
    dlng = half / (111_320 * math.cos(math.radians(abs(lat))))
    bbox = f"{lng - dlng},{lat - dlat},{lng + dlng},{lat + dlat}"
    url = (f"{WORLD_IMAGERY}?bbox={urllib.parse.quote(bbox)}&bboxSR=4326"
           f"&size=512,512&format=jpg&f=image")
    return _download_b64(url)


_LOCATE_PROMPT = """\
You are an aerial-imagery analyst helping a Cape Town estate agency find which \
exact land parcel a property listing refers to. The listing hides its street \
address, but we know the suburb and the erf (plot) size, and the numbered \
satellite crops below show every parcel in that suburb whose size matches.

Work in this order:
1. Read the listing description for location clues (street names, \
"corner of", landmarks, "walking distance to", view directions).
2. Examine EVERY listing photo and build a fingerprint: roof \
shape/colour/material, pool size RELATIVE to the stand plus its shape \
(square/rectangular/L/kidney) and position, building footprint and levels, \
driveway position, vegetation, slope, view direction, distance to coastline, \
distinctive neighbours. Aerial/drone photos are the most valuable.
3. Compare that fingerprint against each numbered satellite crop, \
feature by feature. The parcel is centred in its crop.
4. Score every candidate 0-100.

Hard rules:
- A text clue locates a street or an area, NEVER a specific stand. Two \
neighbours on the named street both satisfy the clue — only visual evidence \
separates them. Never let a street clue outweigh a visual contradiction.
- The POOL TEST is the strongest single check: a pool whose size relative \
to the plot, shape, or position clearly differs from the photos is close to \
a veto for that candidate. Say explicitly for your top pick whether the \
pool matches.
- Reward multiple independent matching features; punish every contradiction.
- Satellite imagery can predate a renovation. If a mismatch could plausibly \
be construction-related, say so and lower confidence rather than forcing \
the match.

Reply with JSON only:
{"street_clues": "clues found in the text, or ''",
 "fingerprint": "2-3 sentence property fingerprint from the photos",
 "has_aerial": true/false,
 "ranking": [{"n": <crop number>, "erf": "<erf>", "score": 0-100,
              "reasons": "specific visual evidence, contradictions included"}],
 "best": {"n": <crop number>, "erf": "<erf>", "confidence": 0-100,
          "verdict": "why this parcel; explicitly state whether the pool \
and roof match, or why unsure"}}
If nothing matches convincingly, set best.confidence below 40 and say so.\
"""

_VERIFY_PROMPT = """\
You are adversarially verifying a colleague's identification of a property. \
They claim the listing shown in the photos is the parcel in satellite crop A. \
Crops B and C (if present) are the strongest rival candidates.

Your job is to try to BREAK the identification. Go feature by feature — pool \
(size relative to stand, shape, position), roof (shape, colour, material), \
building footprint and levels, driveway, vegetation, slope, coastline \
distance, neighbours — and list concrete matches and concrete contradictions \
you can actually see. Do not be polite about it; a wrong contact costs the \
agency real money.

Reply with JSON only:
{"matches": ["specific visible agreements"],
 "contradictions": ["specific visible disagreements"],
 "verdict": "confirm" | "reject" | "uncertain",
 "better": "B" | "C" | null,
 "confidence": 0-100,
 "reason": "one or two sentences"}\
"""


def _openai_client():
    import os
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set — the AI locator needs "
                           "a vision-capable model")
    from openai import OpenAI
    return OpenAI()


def ai_locate_all(log=print, stop: threading.Event | None = None) -> dict:
    """AI photo-locate every group stuck at 'candidates' status.

    The cadastre narrows a property to a candidate list; the vision model
    picks the stand from the listing photos vs satellite crops. Runs once per
    group (skips groups already located), sequentially — each call downloads
    a photo gallery, so parallelism would hammer the portals.
    """
    if not (os.environ.get("OPENAI_API_KEY") or "").strip():
        log("  ai-locate: no OPENAI_API_KEY — skipping photo location")
        return {"groups": 0, "located": 0, "errors": 0, "skipped": 0}
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT group_id, MIN(listing_key) AS k FROM erf_lookup
               WHERE status = 'candidates'
                 AND (ai_status IS NULL OR ai_status = '')
               GROUP BY group_id""").fetchall()
    stats = {"groups": len(rows), "located": 0, "errors": 0, "skipped": 0}
    if rows:
        log(f"  ai-locate: {len(rows)} properties with candidate lists")
    for r in rows:
        if stop is not None and stop.is_set():
            break
        try:
            verdict = ai_locate(r["k"], log=log)
            if (verdict.get("best") or {}).get("erf") is not None:
                stats["located"] += 1
        except Exception as e:            # noqa: BLE001 - keep the batch going
            stats["errors"] += 1
            log(f"  ai-locate: {r['k']}: {type(e).__name__}: {e}")
    return stats


def ai_locate(listing_key: str, log=print) -> dict:
    """Rank the stored candidates for this property with a vision model."""
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM erf_lookup WHERE listing_key = ?",
                           (listing_key,)).fetchone()
        grouped = _groups(conn, sellable_only=False)
        members = next((ms for ms in grouped.values()
                        if any(m["listing_key"] == listing_key for m in ms)),
                       None)
        if not members:
            raise ValueError("unknown listing")
        if row is None or not row["candidates"]:
            res = resolve_group(members)
            _write(conn, [m["listing_key"] for m in members],
                   row["group_id"] if row else "solo", res)
            conn.commit()
            if not res["candidates"]:
                raise RuntimeError(res["note"] or
                                   "no candidate parcels to match against")
            candidates = json.loads(res["candidates"])
        else:
            candidates = json.loads(row["candidates"])

    erf_size = next((m["erf_size_m2"] for m in members
                     if m.get("erf_size_m2")), None)
    suburb = next((m["suburb"] for m in members if m.get("suburb")), "")
    desc = max((m.get("description") or "" for m in members), key=len)
    lat_hint = next((c["lat"] for c in candidates if c.get("lat")), -33.95)

    # Streets named in the copy widen the net: the size filter can miss the
    # real stand when a portal mis-states the erf, but "on Geneva Drive"
    # makes every parcel on Geneva Drive worth a look.
    clue_text = " ".join([desc] + [m.get("title") or "" for m in members])
    street_cands, streets = _street_candidates(suburb, clue_text,
                                               erf_size, lat_hint)
    have = {str(c["erf"]) for c in candidates}
    extra = [c for c in street_cands if str(c["erf"]) not in have]
    if extra:
        log(f"  ai-locate: +{len(extra)} parcels from streets in the copy "
            f"({', '.join(s.title() for s in streets)})")
        candidates = candidates + extra
        with db.connect() as conn:
            conn.execute(
                "UPDATE erf_lookup SET candidates=? WHERE group_id = "
                "(SELECT group_id FROM erf_lookup WHERE listing_key=?)",
                (json.dumps(candidates), listing_key))
            conn.commit()

    def closeness(c):
        return abs((c.get("area_m2") or 0) - erf_size) if erf_size else 0

    def on_named_street(c):
        return any(s.lower() in (c.get("address") or "").lower()
                   for s in streets)

    sel = (sorted([c for c in candidates if on_named_street(c)], key=closeness)
           + sorted([c for c in candidates if not on_named_street(c)],
                    key=closeness))[:AI_CANDIDATES]

    log(f"  ai-locate: {len(sel)} candidates, fetching listing photos…")
    photo_urls = _listing_photos(members, log=log)
    # Thumbnail-size crops hide pool edges and roof detail — analyse big.
    photo_urls = [u.replace("/Crop600x400", "/Ensure1280x720")
                  for u in photo_urls]
    base = config.SOURCES.get(members[0]["source"], {}).get("base_url")
    shots = [b for b in (_download_b64(u, referer=base) for u in photo_urls)
             if b][:AI_PHOTOS]
    if not shots:
        raise RuntimeError("could not fetch any listing photos")

    log(f"  ai-locate: {len(shots)} photos; fetching satellite crops…")
    photo_content: list[dict] = [
        {"type": "text", "text": f"LISTING PHOTOS ({len(shots)}):"}]
    for b in shots:
        photo_content.append({"type": "image_url", "image_url": {"url": b}})

    content: list[dict] = [{"type": "text", "text":
        f"PROPERTY: {suburb}; advertised erf size "
        f"{erf_size:.0f} m²." if erf_size else f"PROPERTY: {suburb}."}]
    content.append({"type": "text",
                    "text": "LISTING DESCRIPTION:\n" + (desc[:4000] or "—")})
    content.extend(photo_content)
    sat_ok, crops = [], {}
    for i, c in enumerate(sel, 1):
        if c.get("lat") is None:
            continue
        b = _satellite_b64(c["lat"], c["lng"], c.get("area_m2"))
        if not b:
            continue
        sat_ok.append((i, c))
        crops[i] = b
        content.append({"type": "text", "text":
                        f"CANDIDATE {i}: erf {c['erf']}, {c['address']}, "
                        f"{c['suburb']}, {c['area_m2']:.0f} m²"})
        content.append({"type": "image_url", "image_url": {"url": b}})
    if not sat_ok:
        raise RuntimeError("could not fetch satellite imagery for candidates")

    log(f"  ai-locate: asking {config.OPENAI_MODEL} "
        f"({len(shots)} photos vs {len(sat_ok)} parcels)…")
    client = _openai_client()
    verdict = _vision_json(client, _LOCATE_PROMPT, content)
    verdict["candidates_seen"] = [c["erf"] for _, c in sat_ok]
    # Models tend to echo the whole candidate label into "erf"; the crop
    # number is the reliable key, so rewrite erf from it.
    by_n = {i: c for i, c in sat_ok}
    for entry in (verdict.get("ranking") or []) + [verdict.get("best") or {}]:
        if isinstance(entry, dict) and entry.get("n") in by_n:
            entry["erf"] = by_n[entry["n"]]["erf"]

    # ---- adversarial verification of the top pick --------------------------
    best = verdict.get("best") or {}
    n_best = best.get("n")
    if n_best in by_n:
        rivals = [e["n"] for e in sorted(
            (e for e in verdict.get("ranking") or []
             if isinstance(e, dict) and e.get("n") in by_n
             and e.get("n") != n_best),
            key=lambda e: -(e.get("score") or 0))][:2]
        log(f"  ai-locate: verifying erf {best.get('erf')} adversarially…")
        vcontent = list(photo_content)
        for label, n in [("A (the claimed parcel)", n_best)] + \
                [(l, n) for l, n in zip("BC", rivals)]:
            c = by_n[n]
            vcontent.append({"type": "text", "text":
                             f"CROP {label}: erf {c['erf']}, {c['address']}, "
                             f"{c['area_m2']:.0f} m²"})
            vcontent.append({"type": "image_url",
                             "image_url": {"url": crops[n]}})
        try:
            ver = _vision_json(client, _VERIFY_PROMPT, vcontent)
        except Exception as e:            # noqa: BLE001 - verify is optional
            ver = {"verdict": "error", "reason": str(e)}
        verdict["verify"] = ver
        v = ver.get("verdict")
        if v == "reject":
            swap = {"B": 0, "C": 1}.get(ver.get("better") or "")
            if swap is not None and swap < len(rivals):
                c = by_n[rivals[swap]]
                verdict["best"] = best = {
                    "n": rivals[swap], "erf": c["erf"],
                    "confidence": min(int(ver.get("confidence") or 50), 60),
                    "verdict": "verifier overruled the first pick: "
                               + (ver.get("reason") or "")}
            else:
                best["confidence"] = min(int(best.get("confidence") or 0), 30)
                best["verdict"] = ("REJECTED on verification: "
                                   + (ver.get("reason") or "")
                                   + " | originally: "
                                   + (best.get("verdict") or ""))
        elif v == "uncertain":
            best["confidence"] = min(int(best.get("confidence") or 0), 55)
            best["verdict"] = ((best.get("verdict") or "")
                               + " | verifier unsure: "
                               + (ver.get("reason") or ""))

    with db.connect() as conn:
        conn.execute(
            "UPDATE erf_lookup SET ai_status='done', ai_best=?, "
            "ai_at=datetime('now') WHERE group_id = "
            "(SELECT group_id FROM erf_lookup WHERE listing_key=?)",
            (json.dumps(verdict), listing_key))
        conn.commit()
    log(f"  ai-locate: best erf {best.get('erf')} "
        f"at {best.get('confidence')}% — {best.get('verdict')}")
    return verdict


def _vision_json(client, system: str, content: list[dict]) -> dict:
    try:
        resp = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": content}],
            response_format={"type": "json_object"})
    except Exception:                     # noqa: BLE001 - older vision fallback
        resp = client.chat.completions.create(
            model=config.OPENAI_FALLBACK_MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": content}],
            response_format={"type": "json_object"})
    out = json.loads(resp.choices[0].message.content)
    out["model"] = resp.model
    return out
