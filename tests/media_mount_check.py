"""Checks for the /zerko mount: auth gate, blocked routes, role mapping.

Plain script, no pytest needed (the repo has no test runner):

    DATA_DIR=$(mktemp -d) .venv/bin/python tests/media_mount_check.py

It refuses to run without DATA_DIR pointing somewhere disposable, because
importing webapp opens DATA_DIR/prospects.db and Zerko writes its catalogue
under DATA_DIR/media-data. Nothing here crawls or calls out.
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile

data = os.environ.get("DATA_DIR")
if not data or os.path.abspath(data) == os.path.abspath(os.path.dirname(os.path.dirname(__file__))):
    sys.exit("Set DATA_DIR to a scratch directory (e.g. DATA_DIR=$(mktemp -d)).")
os.environ.setdefault("MEDIA_ROOT", tempfile.mkdtemp(prefix="media-root-"))
os.environ["DASHBOARD_USER"] = "owner"
os.environ["DASHBOARD_PASSWORD"] = "check-pass"
os.environ["AUTO_CRAWL"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import media  # noqa: E402
import webapp  # noqa: E402

client = webapp.app.test_client()
BASIC = {"Authorization": "Basic " + base64.b64encode(b"owner:check-pass").decode()}
failures = []


def check(name, cond, extra: object = ""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({extra})" if extra and not cond else ""))
    if not cond:
        failures.append(name)


# --- the gate ---------------------------------------------------------------
r = client.get("/zerko/api/videos")
check("unauthenticated /zerko is 401", r.status_code == 401)
r = client.get("/zerko/thumbnails/x.jpg")
check("unauthenticated /thumbnails is 401", r.status_code == 401)
r = client.get("/zerko/api/videos", headers={"Authorization": "Bearer not.a.jwt"})
check("forged bearer is 401", r.status_code == 401)
r = client.get("/zerko/api/public/files/../../api/videos")
check("public-prefix traversal is not public", r.status_code == 401, r.status_code)

# --- owner token -------------------------------------------------------------
r = client.get("/api/media/token", headers=BASIC)
check("owner can mint a token", r.status_code == 200, r.get_data(as_text=True)[:200])
tok = r.get_json()["token"]
check("owner maps to Zerko admin", r.get_json().get("role") == "admin")
BEARER = {"Authorization": "Bearer " + tok}
me = client.get("/zerko/api/me", headers=BEARER).get_json()
check("Zerko sees the owner as admin", me.get("role") == "admin", me)

status = client.get("/api/media/status", headers=BASIC).get_json()
check("status reports features", isinstance(status.get("features"), dict), status)
check("status reports version 1.4.0", status.get("version") == "1.4.0", status.get("version"))

# --- blocked routes ------------------------------------------------------------
for method, path in [("GET", "/api/setup/status"), ("GET", "/setup"), ("GET", "/api/events"),
                     ("GET", "/api/updates/check"), ("POST", "/api/login"),
                     ("POST", "/api/register"), ("POST", "/api/password-reset"),
                     ("POST", "/api/me/password"), ("POST", "/api/users/1/role"),
                     ("DELETE", "/api/users/1"), ("POST", "/api/users/1/reset-link"),
                     ("POST", "/api/hdr/raw-support/install"), ("POST", "/api/ai/image/install"),
                     ("POST", "/api/videos/1/reveal")]:
    r = client.open("/zerko" + path, method=method, headers=BEARER)
    check(f"{method} {path} blocked", r.status_code == 403 and (r.get_json() or {}).get("blocked"),
          r.status_code)
r = client.get("/zerko/api/users", headers=BEARER)
check("GET /api/users still readable by an admin", r.status_code == 200, r.status_code)

# --- role mapping --------------------------------------------------------------
privs = {"member": ("media",), "boss": ("media", "admin"), "crawler": ("crawl",)}
media.set_privileges(lambda u: privs.get(u, ()))
check("media -> editor", media.zerko_role_for(("media",)) == "editor")
check("media+admin -> admin", media.zerko_role_for(("media", "admin")) == "admin")
check("no media -> no access", media.zerko_role_for(("crawl", "leads")) is None)

payload, err = media.mint_token("member")
check("member gets a token", payload is not None, err)
mb = {"Authorization": "Bearer " + (payload or {}).get("token", "")}
me = client.get("/zerko/api/me", headers=mb).get_json()
check("member is a Zerko editor", me.get("role") == "editor", me)
r = client.post("/zerko/api/trash/empty", headers=mb)
check("editor cannot empty the trash", r.status_code == 403, r.status_code)

payload, err = media.mint_token("crawler")
check("no-media account is refused a token", payload is None and err)

# Privileges change after the token was minted: promoted, then revoked.
privs["member"] = ("media", "admin")
me = client.get("/zerko/api/me", headers=mb).get_json()
check("promotion reaches Zerko without a new token", me.get("role") == "admin", me)
privs["member"] = ("leads",)
r = client.get("/zerko/api/me", headers=mb)
check("revoked media: old token refused at the gate", r.status_code == 401, r.status_code)

print()
print(f"{len(failures)} failure(s)" if failures else "all checks passed")
sys.exit(1 if failures else 0)
