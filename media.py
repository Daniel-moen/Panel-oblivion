"""Mount the vendored Zerko media backend inside this Flask process.

Zerko is an ASGI (FastAPI) application; the prospecting dashboard is WSGI
(Flask). Rather than run two servers and reverse-proxy between them — two
processes to supervise, two ports to secure, and a second copy of every
environment variable — the ASGI app is adapted to WSGI with
``a2wsgi.ASGIMiddleware`` and hung off the same WSGI stack under ``/zerko``
using werkzeug's ``DispatcherMiddleware``.

That keeps the Procfile's "one worker, several threads" shape intact: Zerko's
own background threads (the job manager, ffmpeg workers) live in the same
process as the crawl threads, and the in-memory progress dicts both apps use
stay visible to every request. A second gunicorn worker would break Zerko's
job progress exactly the way it would break ``webapp.job``.

``DispatcherMiddleware`` moves the ``/zerko`` prefix from ``PATH_INFO`` into
``SCRIPT_NAME``, so FastAPI sees the original paths (``/api/videos``,
``/thumbnails/...``). That matters for more than tidiness: Zerko's role gate
(``enforce_role_permissions``) matches ``^/api/`` against the request path, so
a prefix left in place would silently switch every permission rule off.

Everything here is lazy and fail-soft. The media backend needs a dozen
dependencies the prospecting engine does not otherwise use (fastapi,
sqlalchemy, opencv, …) and a footage drive that a hosted deploy does not have.
If any of that is missing the dashboard must still boot and behave exactly as
it did before — so the import happens on the first ``/zerko`` request, its
failure is cached, and it is reported as JSON rather than raised.
"""

from __future__ import annotations

import json
import os
import threading

import config

#: Where the media API is reachable from the browser. The SvelteKit client
#: prepends this to every Zerko path, including the ``/thumbnails/...`` values
#: that come back embedded in API responses.
PREFIX = "/zerko"

# --------------------------------------------------------------- blocked routes
#
# A few upstream endpoints are actively hostile inside a shared process. They
# are refused at the mount rather than edited out of main.py, so the vendored
# source stays close to upstream and the reasoning lives in one place.
_BLOCKED = {
    # The first-run wizard's directory browser lists *any* folder on the host
    # until an account exists. We auto-provision an account (see
    # ``ensure_account``) which makes it 403, but the dashboard has no use for
    # the wizard at all, so it never gets the chance.
    "/api/setup": "The Zerko setup wizard is disabled: this install is "
                  "configured by environment variables.",
    # Server-Sent Events hold a worker thread open for the life of the client.
    # With gunicorn on 8 threads, a handful of open browser tabs would starve
    # the dashboard. The UI polls instead.
    "/api/events": "Server-sent events are disabled here; poll the job "
                   "endpoints instead.",
    # Opens a file manager window on the *server*. Meaningless on Railway and
    # a command-execution surface everywhere else.
    "/api/videos/reveal": "Revealing files on the server is disabled.",
    # Neutered by zerko/updater.py already; refused here too so the reason is
    # visible rather than implied.
    "/api/updates": "Zerko updates ship with this repository.",
}


def _blocked_reason(path: str) -> str | None:
    for prefix, why in _BLOCKED.items():
        if path == prefix or path.startswith(prefix + "/"):
            return why
    if path.endswith("/reveal") and path.startswith("/api/videos/"):
        return _BLOCKED["/api/videos/reveal"]
    return None


# ------------------------------------------------------------------ lazy loading
_lock = threading.Lock()
_state: dict = {"loaded": False, "wsgi": None, "error": None}


def _load() -> dict:
    """Import Zerko and adapt it to WSGI. Cached, including the failure."""
    if _state["loaded"]:
        return _state
    with _lock:
        if _state["loaded"]:
            return _state
        try:
            # zerko/__init__.py redirects every path upstream writes to before
            # any submodule is imported, so this import order matters.
            from a2wsgi import ASGIMiddleware

            from zerko.main import app as zerko_app

            _state["wsgi"] = ASGIMiddleware(zerko_app)
            _state["error"] = None
        except Exception as e:                        # noqa: BLE001 - reported, not raised
            _state["wsgi"] = None
            _state["error"] = f"{type(e).__name__}: {e}"
            print(f"  [media] Zerko backend unavailable — {_state['error']}",
                  flush=True)
        _state["loaded"] = True
        return _state


def available() -> bool:
    return _load()["wsgi"] is not None


def load_error() -> str | None:
    return _load()["error"]


def status() -> dict:
    """What the Media section shows when something is not set up.

    Deliberately answers rather than raises: "no footage drive on this
    deployment" is a normal state for the hosted copy, not an error.
    """
    st = _load()
    out = {
        "backend": bool(st["wsgi"]),
        "backend_error": st["error"],
        "prefix": PREFIX,
        "media_root": {"ok": False, "reason": "backend",
                       "message": "The media backend is not installed."},
    }
    if st["wsgi"]:
        try:
            import zerko
            out["media_root"] = zerko.media_root_state()
            out["data_dir"] = str(zerko.ZERKO_DATA)
        except Exception as e:                        # noqa: BLE001
            out["media_root"] = {"ok": False, "reason": "error",
                                 "message": str(e)}
    return out


# --------------------------------------------------------------- single sign-on
#
# The dashboard already authenticated the person with HTTP basic auth. Making
# them sign in a second time to a bundled subsystem would be theatre, so the
# Flask side mints a Zerko JWT on demand for an account named after the basic
# auth user. The account is created once, with a random password nobody is
# ever told: the only way to obtain a token for it is to already be through
# ``_require_auth``.

def ensure_account(username: str) -> str | None:
    """Create (once) the admin account that mirrors the signed-in dashboard
    user. Returns None on success, or a human-readable reason."""
    if not available():
        return load_error() or "The media backend is not installed."
    try:
        import secrets

        from zerko.auth import get_password_hash
        from zerko.database import SessionLocal, User

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if user is None:
                user = User(
                    username=username,
                    email=f"{username}@oblivion.local",
                    hashed_password=get_password_hash(secrets.token_urlsafe(32)),
                    role="admin",
                    is_active=True,
                )
                db.add(user)
                db.commit()
            elif user.role != "admin" or not user.is_active:
                # Single-role by design: everyone who can open the dashboard
                # can do everything in the media library.
                user.role, user.is_active = "admin", True
                db.commit()
            return None
        finally:
            db.close()
    except Exception as e:                            # noqa: BLE001
        return f"{type(e).__name__}: {e}"


def mint_token(username: str) -> tuple[dict | None, str | None]:
    """A Zerko access token for the signed-in dashboard user.

    Returns ``(payload, error)``. The payload carries the bearer token, the
    prefix every Zerko URL must be built on, and the media-root state, so the
    client bootstraps from a single call.
    """
    problem = ensure_account(username)
    if problem:
        return None, problem
    try:
        from zerko.auth import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token

        made = create_access_token({"sub": username})
        return {
            "token": made["token"],
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "prefix": PREFIX,
            "user": username,
            **status(),
        }, None
    except Exception as e:                            # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


# ------------------------------------------------------------------- the mount

def _json_response(start_response, code: str, body: dict):
    raw = json.dumps(body).encode("utf-8")
    start_response(code, [("Content-Type", "application/json"),
                          ("Content-Length", str(len(raw)))])
    return [raw]


#: Set by webapp.mount(): ``fn(environ) -> bool``, True when the request
#: carries the dashboard's basic-auth credentials.
_authorised = None


def set_guard(fn) -> None:
    """Hand the mount the dashboard's own credential check.

    This is not optional decoration. ``DispatcherMiddleware`` wraps
    ``flask_app.wsgi_app``, which puts it *outside* Flask — so a request for
    ``/zerko/...`` is routed to the media backend before Flask exists, and
    ``@app.before_request`` (``_require_auth``) never runs for it. Mounting
    without re-checking here would publish the entire media API, including the
    unauthenticated ``/thumbnails`` static mount, to anyone who guessed the
    prefix. The dashboard password has to be checked on this side of the
    dispatcher as well, against the same credentials.
    """
    global _authorised
    _authorised = fn


def _norm(path: str) -> str:
    """PATH_INFO with any ``..`` resolved, so a prefix test cannot be walked
    past (``/zerko/api/public/../../api/videos``)."""
    import posixpath

    return posixpath.normpath(path or "/").replace("\\", "/") or "/"


def _valid_zerko_token(environ) -> bool:
    """True when the request carries a Zerko bearer token this app minted.

    There is only one Authorization header, and the two halves of the stack
    want different things in it: the dashboard wants Basic, Zerko wants
    Bearer. A browser attaches Basic automatically to `<img>` and `<video>`
    requests, but any `fetch()` that sets a Bearer token *replaces* it — so a
    gate that only understood Basic would reject every call the Media pages
    make.

    Accepting the bearer is sound because the only way to obtain one is
    /api/media/token, which is itself behind Basic auth. It is verified
    properly rather than waved through: several upstream routes have no auth
    dependency of their own — the /thumbnails static mount most of all — and
    would otherwise be readable by anyone sending the word "Bearer".
    """
    header = environ.get("HTTP_AUTHORIZATION", "")
    if not header.lower().startswith("bearer "):
        return False
    raw = header.split(" ", 1)[1].strip()
    if not raw:
        return False
    try:
        from zerko.auth import ALGORITHM, SECRET_KEY
        from jose import jwt

        claims = jwt.decode(raw, SECRET_KEY, algorithms=[ALGORITHM])
        return bool(claims.get("sub"))
    except Exception:                    # noqa: BLE001 - expired, forged or malformed
        return False


def _gate(environ, start_response):
    """The WSGI callable mounted at /zerko.

    Order matters: authenticate, then refuse the blocked routes, then load
    Zerko. A missing backend becomes a 503 with an explanation rather than a
    traceback — but only for someone already through the door.
    """
    raw = environ.get("PATH_INFO", "") or "/"
    path = _norm(raw)

    # The share API is the one part a client reaches with no password; it
    # authenticates on the share token instead. Everything else needs either
    # the dashboard credentials or a token minted from them — checked here
    # because Flask, and therefore _require_auth, is not in this path.
    if not is_public_path(PREFIX + path) \
            and _authorised is not None \
            and not _authorised(environ) \
            and not _valid_zerko_token(environ):
        raw_body = json.dumps({"detail": "Authentication required."}).encode()
        start_response("401 Unauthorized", [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(raw_body))),
            ("WWW-Authenticate", 'Basic realm="Oblivion Prospect Engine"')])
        return [raw_body]

    why = _blocked_reason(path)
    if why:
        return _json_response(start_response, "403 Forbidden",
                              {"detail": why, "blocked": True})

    st = _load()
    if st["wsgi"] is None:
        return _json_response(start_response, "503 Service Unavailable", {
            "detail": "The media backend is not available in this deployment.",
            "error": st["error"],
            "hint": "Install the requirements (pip install -r requirements.txt) "
                    "and set MEDIA_ROOT to the footage drive.",
        })
    return st["wsgi"](environ, start_response)


def mount(flask_app) -> None:
    """Hang the media backend off an existing Flask app under /zerko."""
    from werkzeug.middleware.dispatcher import DispatcherMiddleware

    flask_app.wsgi_app = DispatcherMiddleware(flask_app.wsgi_app,
                                              {PREFIX: _gate})


# ------------------------------------------------------------- share-link paths
#
# webapp.py's auth gate consults this so the exemption list lives next to the
# code that knows which routes are genuinely public. Both are token-scoped:
# the share token *is* the credential, and Zerko validates it (expiry,
# revocation, optional password, per-IP throttling) on every call.
PUBLIC_PREFIXES = (
    PREFIX + "/api/public/share/",     # clip payload, thumbs, streaming, zip
    PREFIX + "/api/public/files/",     # the general file store's share links
)


def is_public_path(path: str) -> bool:
    """True for the client-facing share routes that must work without the
    dashboard password. Deliberately a prefix match on a short, explicit
    list — anything not named here stays behind basic auth.

    The path is normalised first: without that, ``/zerko/api/public/files/
    ../../api/videos`` would pass a naive ``startswith`` and then be routed,
    after the server resolved it, to an endpoint that is not public at all.
    """
    return _norm(path).startswith(PUBLIC_PREFIXES)
