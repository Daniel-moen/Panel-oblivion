"""LOOM Property Insights client — self-sourced deed lookups (server-side).

This module runs on the server and makes ONLY plain JSON requests to LOOM's
Property Insights API (pi-api.loom.co.za). It never launches a browser.

Auth is a bearer token cached in loom_token.json (or the LOOM_TOKEN env var).
That token is minted out-of-band by loom_login.py — a Playwright script that
drives LOOM's Azure AD B2C login on a trusted machine (your Mac / a scheduled
job) and writes a fresh token here every ~45 min. LOOM's client forbids the
OAuth password grant, so the browser step is unavoidable — but it is isolated
to loom_login.py; everything the web app calls lives here and stays lightweight.

The deed reveal is gated behind LOOM's own POPIA consent step
(MapPropertyReport/SetConsent) — the same consent an agent clicks in the UI.

POPIA note: this mirrors owners.py's discipline — we store only what is needed
to make contact, for the mandate pitch it was collected for. See owners.py.
"""
from __future__ import annotations

import json
import os

import requests

PI_API = "https://pi-api.loom.co.za"
TOKEN_PATH = os.environ.get(
    "LOOM_TOKEN_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "loom_token.json"),
)


class LoomError(Exception):
    """A LOOM lookup failed (no match, API error, bad response)."""


class LoomAuthError(LoomError):
    """No usable token, or LOOM rejected it — loom_login.py must refresh."""


# ------------------------------------------------------------------ token

def _load_token() -> str:
    tok = os.environ.get("LOOM_TOKEN")
    if tok:
        return tok.strip()
    try:
        with open(TOKEN_PATH, encoding="utf-8") as fh:
            return json.load(fh)["access_token"].strip()
    except (FileNotFoundError, KeyError, ValueError):
        raise LoomAuthError(
            "No LOOM token available — run loom_login.py to mint one "
            f"(expected {TOKEN_PATH} or $LOOM_TOKEN)."
        )


def token_status() -> dict:
    """Lightweight health check for the UI: is a token present, how old."""
    if os.environ.get("LOOM_TOKEN"):
        return {"present": True, "source": "env"}
    try:
        with open(TOKEN_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        return {"present": bool(d.get("access_token")),
                "source": "file", "captured_at": d.get("captured_at")}
    except (FileNotFoundError, ValueError):
        return {"present": False}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {_load_token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    return s


def _call(s: requests.Session, method: str, path: str, **kw):
    try:
        r = s.request(method, f"{PI_API}{path}", timeout=40, **kw)
    except requests.RequestException as e:
        raise LoomError(f"network error calling LOOM: {e}") from e
    if r.status_code == 401:
        raise LoomAuthError("LOOM rejected the token (401) — refresh needed.")
    try:
        body = r.json()
    except ValueError:
        raise LoomError(f"non-JSON response from {path} (HTTP {r.status_code}).")
    if isinstance(body, dict) and body.get("error"):
        msg = (body["error"] or {}).get("message") or "LOOM returned an error"
        raise LoomError(msg)
    return body.get("result") if isinstance(body, dict) else body


# ------------------------------------------------------------- API calls

def search_deeds(erf: str, town: str) -> list:
    """Structured deeds search by erf number + town. Returns match rows."""
    payload = {
        "town": (town or "").strip(), "erfNumber": str(erf or "").strip(),
        "ownerId": "", "ownerName": "", "unitnumber": "", "schemename": "",
        "titledeednumber": "", "option": "", "propertyKey": "", "addressid": "",
    }
    return _call(_session(), "POST",
                 "/api/services/app/Search/AdvanceDeedsSearchV2", json=payload) or []


def get_property(property_key: str, unit: str = "00000") -> dict:
    return _call(_session(), "GET",
                 "/api/services/app/MapPropertyReport/GetProperty",
                 params={"propertyId": property_key, "unitNumber": unit,
                         "useGrace": "false", "useLegacy": "false"}) or {}


def reveal_owners(report_id) -> list:
    """The billed/consent reveal: unmasks the registered owner name(s).

    Mirrors the UI's 'Show Details' -> 'Accept Deeds Info Consent' action.
    """
    return _call(_session(), "POST",
                 "/api/services/app/MapPropertyReport/SetConsent",
                 params={"id": report_id}) or []


# --------------------------------------------------------- high-level

def _to_int_price(v):
    if v in (None, "", 0, "0"):
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def fetch_deed(erf: str, town: str, sg26_code: str | None = None,
               reveal: bool = True) -> dict:
    """Resolve one property to its deed + registered owner.

    Returns a dict whose keys line up with owners.FIELDS so the caller can
    persist it straight into owner_details. `reveal=False` skips the POPIA
    consent step and leaves the owner name masked.
    """
    key = unit = None
    rows = search_deeds(erf, town)
    if rows:
        key = rows[0].get("property_key")
        unit = rows[0].get("unit_number") or "00000"
    if not key and sg26_code:
        # Fallback: LOOM's property_key is the SG code trimmed to 21 chars.
        key, unit = sg26_code[:21], "00000"
    if not key:
        raise LoomError(f"LOOM found no deed for erf {erf} in {town}.")

    prop = get_property(key, unit or "00000")
    report = prop.get("report") or {}
    report_id = prop.get("id")
    deeds = report.get("deeds") or {}
    transfer = deeds.get("transfer") or {}
    owners_list = deeds.get("owners") or []

    if reveal and report_id is not None:
        try:
            revealed = reveal_owners(report_id)
            if revealed:
                owners_list = revealed
        except LoomError:
            pass  # keep masked owner rather than fail the whole lookup

    owner = owners_list[0] if owners_list else {}
    bonds = deeds.get("bonds") or []
    bond_holder = (bonds[0].get("bond_holder") or bonds[0].get("bank")
                   if bonds and isinstance(bonds[0], dict) else None)

    return {
        "property_key": key,
        "report_id": report_id,
        "owner_name": owner.get("name"),
        "owner_type": owner.get("type"),
        "phone": owner.get("cell_number"),
        "email": owner.get("email"),
        "deed_number": transfer.get("title_deed"),
        "purchase_price": _to_int_price(transfer.get("sell_price")),
        "purchase_date": transfer.get("registration_date"),
        "bond_holder": bond_holder,
        "deeds_office": transfer.get("office"),
        "town_name": transfer.get("town_name"),
        "raw": json.dumps(deeds)[:6000],
    }
