"""Sign-in for the dashboard: cookie sessions and passkeys.

Why this module exists
----------------------
The dashboard used to be HTTP basic auth and nothing else. That is fine for
curl and for cron, and it is kept — every endpoint below still accepts a basic
header — but a browser cannot log *out* of basic auth, cannot remember a
second factor, and on a phone means typing a long password into a portal-data
screen several times a day. So on top of the password there is now:

  * a signed session cookie (`oblivion_session`), so a browser signs in once;
  * WebAuthn passkeys, so signing in again is Touch ID / Windows Hello / a
    phone over QR, with no shared secret travelling anywhere.

Accounts, roles and invites
---------------------------
There is exactly one OWNER (``DASH_USER``): its password is the environment's
``DASHBOARD_PASSWORD`` and is never stored in the database, so basic auth for
curl and cron keeps working byte for byte as it always has. Everyone else is
invited: the owner (or an admin) mints a sign-up token, the invitee opens
``/signup?token=…`` and registers a passkey right there. Non-owner accounts
are PASSKEY-ONLY — there is no member password anywhere in this module, no
hash column, and no password form that a member could use. Losing every
device is recovered by the owner issuing a fresh "re-register" invite scoped
to that existing user, not by a temporary password.

That has one consequence worth stating plainly: a user row is only written
once a passkey actually exists for it. ``POST /api/signup`` validates the
token and hands back registration options; the account, the passkey and the
"this invite is used" flag are all committed together inside
``POST /api/signup/verify``. An abandoned sign-up therefore leaves nothing
behind and burns no token.

Privileges are four flags — ``crawl``, ``leads``, ``media``, ``admin`` — and
everyone signed in can READ everything. Enforcement is server-side only
(``require_priv``); the UI hides what you cannot do as a courtesy, never as a
control.

Why the WSGI gate has to check the cookie too
---------------------------------------------
``media.py`` mounts the vendored Zerko backend at /zerko with
``DispatcherMiddleware``, which wraps ``app.wsgi_app`` and therefore sits
*outside* Flask: a /zerko request is dispatched before Flask exists and
``@app.before_request`` never runs for it. media.set_guard() is handed
``webapp._wsgi_authorised``, which is the only authentication that path gets.
If that function understood basic auth alone, then a browser signed in with a
cookie — and only a cookie, because there is no password in the keychain any
more once passkeys are used — would be refused by the entire media library,
including the unauthenticated /thumbnails static mount it serves. So
``current_user()`` accepts a raw WSGI environ as well as a Flask request, and
parses HTTP_COOKIE itself on that side.

Storage notes
-------------
The signing secret is persisted in the DB (``app_secrets``) rather than
generated per boot: on Railway the DB lives on a volume, so a redeploy keeps
everyone signed in, while a random-per-boot secret would sign everyone out on
every deploy. Sessions are rows rather than self-contained signed blobs so
that "sign out this device" is a real revocation and the account page can list
what is signed in.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from flask import Blueprint, Response, g, jsonify, make_response, redirect, request

import db

# ------------------------------------------------------------------ account
#
# The owner account, read once at import. webapp.py re-exports these so the
# rest of the app keeps its existing names.
DASH_USER = os.environ.get("DASHBOARD_USER", "oblivion")
DASH_PASS = os.environ.get("DASHBOARD_PASSWORD", "")
IS_HOSTED = bool(os.environ.get("PORT") or os.environ.get("RAILWAY_ENVIRONMENT"))

COOKIE_NAME = "oblivion_session"
SESSION_DAYS = 30
RP_NAME = "Oblivion Prospect Engine"

#: The whole privilege vocabulary. Deliberately four flags: everyone signed
#: in can read everything, so these only ever gate *writing* and the one paid
#: surface (crawls). Adding a fifth needs a reason, not a route.
PRIVILEGES = ("crawl", "leads", "media", "admin")
ROLES = ("owner", "admin", "member")

#: Days an invite is good for unless the caller says otherwise.
INVITE_DAYS = 7

#: Paths that must resolve before anyone is signed in. Kept short and literal
#: so the surface can be read at a glance — no wildcards.
PUBLIC_PATHS = frozenset({
    "/login",
    "/logout",                       # revoking a session cannot need a session
    "/favicon.svg",
    # The login page is the app's scene, photograph and all, and the browser
    # fetching it has no session yet — behind the gate the hero would 302 to
    # /login and the card would float on bare graphite. They are decorative
    # JPEGs shipped in the build, carrying no data about anyone.
    "/hero-morning.jpg",
    "/hero-day.jpg",
    "/hero-dusk.jpg",
    "/hero-night.jpg",
    "/api/passkeys/login/options",
    "/api/passkeys/login/verify",
    # Sign-up by invite: the page, and the two halves of the registration
    # ceremony that is the ONLY way a non-owner account comes into existence.
    # Both are throttled per IP exactly as /login is, and both refuse without
    # a live invite token.
    "/signup",
    "/api/signup",
    "/api/signup/verify",
})

bp = Blueprint("auth", __name__)


def credentials_ok(auth) -> bool:
    """The one place the dashboard password is compared.

    Shared with the media mount: DispatcherMiddleware runs outside Flask, so
    that side has to make the same check itself rather than rely on webapp's
    ``_require_auth``.
    """
    return bool(auth and auth.username == DASH_USER
                and hmac.compare_digest(auth.password or "", DASH_PASS))


def basic_ok(environ_or_request) -> bool:
    """credentials_ok() against whatever carries an Authorization header."""
    from werkzeug.datastructures import Authorization

    if isinstance(environ_or_request, dict):
        header = environ_or_request.get("HTTP_AUTHORIZATION", "")
        try:
            return credentials_ok(Authorization.from_header(header))
        except Exception:                # noqa: BLE001 - malformed is simply not authorised
            return False
    return credentials_ok(environ_or_request.authorization)


# ------------------------------------------------------------------- schema
#
# This module owns its own tables (the pattern brief.ensure_schema uses):
# db.SCHEMA already holds the three sign-in tables that predate accounts, and
# the two below plus their migrations are added here so everything about who
# may do what reads in one file.

_USERS_SCHEMA = """
-- One row per person. The OWNER row is bootstrapped from DASHBOARD_USER and
-- authenticates against the environment password, which is deliberately not
-- stored anywhere: basic auth for scripts must keep comparing exactly what it
-- always compared. Every other account is passkey-only — there is no password
-- column at all, so there is nothing to leak, reset or mistype.
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    -- NOCASE: "Sam" and "sam" are one person, and the login/invite paths all
    -- compare with plain '=' and rely on this collation to mean it.
    username     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT,
    role         TEXT NOT NULL DEFAULT 'member'
                 CHECK (role IN ('owner', 'admin', 'member')),
    privileges   TEXT NOT NULL DEFAULT '[]',   -- JSON list; ignored for owner/admin
    created_at   TEXT NOT NULL,
    created_by   INTEGER,
    disabled     INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT
);

-- A sign-up token. Only its sha256 is stored, so the table is useless to
-- anyone who reads it; the raw token exists exactly once, in the response to
-- the POST that created it. `user_id` set = a RE-REGISTER invite: it attaches
-- a new passkey to that existing account (the lost-every-device path) rather
-- than creating one.
CREATE TABLE IF NOT EXISTS invites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash  TEXT NOT NULL UNIQUE,
    role        TEXT NOT NULL DEFAULT 'member',
    privileges  TEXT NOT NULL DEFAULT '[]',
    note        TEXT,
    user_id     INTEGER,
    created_by  INTEGER,
    created_at  TEXT NOT NULL,
    expires_at  TEXT,
    used_at     TEXT,
    used_by     INTEGER,
    revoked     INTEGER NOT NULL DEFAULT 0
);
"""

_schema_lock = threading.Lock()
_schema_done = False


def ensure_schema(conn) -> None:
    """Create the account tables and bring an existing install up to them.

    Idempotent and cheap, but guarded by a process flag anyway because
    session_id() runs on every thumbnail request.

    The migration is the whole point: a deployment that has been running with
    one account already holds passkeys and live sessions, and they must keep
    working across the upgrade. Both tables gain a user_id and every existing
    row is adopted by the owner — the only account that existed when they were
    written.
    """
    global _schema_done
    with _schema_lock:
        # panel.py's DDL declares a vestigial `users(id, name)` that nothing
        # in this repo ever reads or writes — it predates accounts and was
        # never wired up. Clear the name out of the way before claiming it,
        # or CREATE TABLE IF NOT EXISTS silently keeps the wrong shape and
        # every query below fails on a column that is not there. Once ours
        # exists, panel's statement is a no-op forever.
        legacy = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        if legacy and "username" not in legacy:
            try:
                if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                    conn.execute("ALTER TABLE users RENAME TO users_pre_accounts")
                else:
                    conn.execute("DROP TABLE users")
            except Exception:            # noqa: BLE001 - raced, or already moved
                pass
        conn.executescript(_USERS_SCHEMA)
        for table, col in (("passkeys", "user_id"), ("sessions", "user_id")):
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                try:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {col} INTEGER")
                except Exception:        # noqa: BLE001 - raced by another worker
                    pass

        # Owner bootstrap. The username can change (DASHBOARD_USER is an env
        # var); the ROW is the identity, so an existing owner is renamed
        # rather than duplicated, and there is never a second one.
        now = _now()
        owner = conn.execute(
            "SELECT id, username FROM users WHERE role='owner'").fetchone()
        if owner is None:
            conn.execute(
                "INSERT OR IGNORE INTO users (username, display_name, role,"
                " privileges, created_at) VALUES (?,?, 'owner', '[]', ?)",
                (DASH_USER, DASH_USER, now))
            conn.execute("UPDATE users SET role='owner', disabled=0"
                         " WHERE username=?", (DASH_USER,))
        elif owner["username"] != DASH_USER:
            # Only if the new name is free; otherwise leave it alone rather
            # than collide (and say so in the logs nowhere — this is a boot
            # path, and a wrong rename is worse than a stale name).
            clash = conn.execute("SELECT id FROM users WHERE username=?"
                                 " AND id<>?", (DASH_USER, owner["id"])).fetchone()
            if not clash:
                conn.execute("UPDATE users SET username=? WHERE id=?",
                             (DASH_USER, owner["id"]))
        oid = conn.execute(
            "SELECT id FROM users WHERE role='owner'").fetchone()["id"]

        conn.execute("UPDATE passkeys SET user_id=? WHERE user_id IS NULL",
                     (oid,))
        # Sessions carry the username and always have; the id is filled in
        # beside it so a rename never orphans a signed-in browser.
        conn.execute(
            "UPDATE sessions SET user_id = (SELECT u.id FROM users u"
            "  WHERE u.username = sessions.user) WHERE user_id IS NULL")
        conn.commit()
        _schema_done = True


@contextmanager
def _db():
    """db.connect() with the account tables guaranteed to exist."""
    with db.connect() as conn:
        if not _schema_done:
            ensure_schema(conn)
        yield conn


# -------------------------------------------------------------------- users

def _json_list(raw) -> list:
    try:
        got = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    return got if isinstance(got, list) else []


def clean_privileges(raw) -> list:
    """Whatever came in, as an ordered subset of PRIVILEGES."""
    want = {str(p) for p in (raw or []) if isinstance(p, (str, int))}
    return [p for p in PRIVILEGES if p in want]


def effective_privileges(row) -> list:
    """What this account may actually do.

    Owner and admin get everything (an admin IS the people-and-invites
    privilege); a member gets exactly what was ticked for them.
    """
    if not row:
        return []
    if row["role"] in ("owner", "admin"):
        return list(PRIVILEGES)
    return clean_privileges(_json_list(row["privileges"]))


def _user_public(row, passkeys: int | None = None) -> dict:
    out = {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "role": row["role"],
        "privileges": effective_privileges(row),
        "granted": clean_privileges(_json_list(row["privileges"])),
        "is_owner": row["role"] == "owner",
        "disabled": bool(row["disabled"]),
        "created_at": row["created_at"],
        "last_seen_at": row["last_seen_at"],
    }
    if passkeys is not None:
        out["passkeys"] = passkeys
    return out


def _by_username(conn, username: str):
    return conn.execute("SELECT * FROM users WHERE username=?",
                        (username or "",)).fetchone()


def _by_id(conn, uid: int):
    return conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def owner_row(conn):
    return conn.execute("SELECT * FROM users WHERE role='owner'").fetchone()


_USERNAME_OK = set("abcdefghijklmnopqrstuvwxyz0123456789._-")


def clean_username(raw) -> str | None:
    """A username, or None if it is not one. Lowercased; 3-32 plain chars."""
    name = str(raw or "").strip().lower()
    if not 3 <= len(name) <= 32:
        return None
    if not set(name) <= _USERNAME_OK or not name[0].isalnum():
        return None
    return name


# ---------------------------------------------------------- who is calling
#
# One resolution per request, cached on flask.g: the before_request hook, any
# require_priv decorator and the view itself all ask, and three reads of the
# same row per request is three SQLite opens for nothing.

def account():
    """The signed-in user's row as a dict, or None.

    Basic auth is the owner, unchanged and forever — that is what every
    script, cron job and `curl -u` in this repo already sends.
    """
    from flask import has_request_context

    if not has_request_context():
        return None
    cached = getattr(g, "_oblivion_account", False)
    if cached is not False:
        return cached
    acct = _resolve_account()
    try:
        g._oblivion_account = acct
    except RuntimeError:                 # noqa: BLE001 - outside a request ctx
        pass
    return acct


def _resolve_account():
    via, username = None, None
    if basic_ok(request):
        via = "basic"
    elif not DASH_PASS and not IS_HOSTED:
        via = "open"                     # local, no password set
    else:
        username = current_user(request)
        if not username:
            return None
        via = "session"
    with _db() as conn:
        row = (_by_username(conn, username) if username else owner_row(conn))
        if row is None or row["disabled"]:
            return None
        out = _user_public(row)
    out["via"] = via
    return out


def has_priv(flag: str) -> bool:
    acct = account()
    return bool(acct and flag in acct["privileges"])


_priv_cache: dict[str, tuple[float, tuple]] = {}
_priv_lock = threading.Lock()


def privileges_for(username: str) -> tuple:
    """What that username may do, by name alone and briefly cached.

    For the one caller that has no Flask request to hang anything off: the
    /zerko WSGI gate, which runs outside Flask on every thumbnail and video
    range request and knows only the name current_user(environ) gave it.
    """
    now = time.time()
    with _priv_lock:
        hit = _priv_cache.get(username or "")
        if hit and hit[0] > now:
            return hit[1]
    with _db() as conn:
        row = _by_username(conn, username)
    privs = tuple() if not row or row["disabled"] else tuple(
        effective_privileges(row))
    with _priv_lock:
        _priv_cache[username or ""] = (now + 30.0, privs)
    return privs


def forbidden(flag: str):
    """The one shape an unauthorised write ever answers with."""
    return jsonify({"error": "forbidden", "need": flag}), 403


def require_priv(flag: str):
    """Decorator: this route writes, and writing needs `flag`.

    Read routes are never decorated — everyone signed in may read everything.
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            if not has_priv(flag):
                return forbidden(flag)
            return fn(*a, **kw)
        return wrapper
    return deco


# ------------------------------------------------------------------ secret

_secret_lock = threading.Lock()
_secret_cache: bytes | None = None


def _secret() -> bytes:
    """The cookie signing key: the env var if set, else one generated once.

    DASHBOARD_SECRET wins so a deployment can rotate it (or share it across
    replicas that do not share a volume). Without it, a 32-byte secret is
    minted on first use and stored, so restarts do not invalidate cookies.
    """
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache
    with _secret_lock:
        if _secret_cache is not None:
            return _secret_cache
        env = os.environ.get("DASHBOARD_SECRET", "").strip()
        if env:
            _secret_cache = env.encode("utf-8")
            return _secret_cache
        with db.connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_secrets WHERE name='session_secret'").fetchone()
            if row:
                _secret_cache = row["value"].encode("utf-8")
                return _secret_cache
            made = secrets.token_hex(32)
            conn.execute(
                "INSERT OR REPLACE INTO app_secrets (name, value, created_at)"
                " VALUES ('session_secret', ?, ?)", (made, _now()))
            conn.commit()
            _secret_cache = made.encode("utf-8")
            return _secret_cache


def _signer():
    from itsdangerous import URLSafeSerializer

    return URLSafeSerializer(_secret(), salt="oblivion-session")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ----------------------------------------------------------------- sessions
#
# A positive cache in front of the sessions table. The media gate runs
# current_user() on every thumbnail and video-range request, and a SQLite open
# per image is wasteful. 30 seconds is short enough that a stale entry is
# academic, and revoke_session() drops the entry anyway — the only revocations
# that matter happen in this process.
_CACHE_TTL = 30.0
_cache: dict[str, tuple[float, str, str]] = {}
_cache_lock = threading.Lock()


def create_session(user: str, user_agent: str = "",
                   user_id: int | None = None) -> str:
    """Insert a session row and return the value for the cookie.

    `user` stays the username: the /zerko WSGI gate, media.mint_token() and
    the chat sender all read a name, not an id. The id rides along beside it.
    """
    sid = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    with _db() as conn:
        if user_id is None:
            row = _by_username(conn, user)
            user_id = row["id"] if row else None
        conn.execute(
            "INSERT INTO sessions (id, user, user_id, created_at, last_seen_at,"
            " expires_at, user_agent, revoked) VALUES (?,?,?,?,?,?,?,0)",
            (sid, user, user_id, _now(), _now(),
             (now + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             (user_agent or "")[:400]))
        conn.commit()
    return _signer().dumps(sid)


def revoke_session(sid: str) -> None:
    with _db() as conn:
        conn.execute("UPDATE sessions SET revoked=1 WHERE id=?", (sid,))
        conn.commit()
    _forget(lambda cached_sid, _user: cached_sid == sid)


def revoke_user_sessions(conn, user_id: int, username: str = "") -> None:
    """Sign every one of that person's browsers out, now.

    Called when an account is disabled or deleted: a privilege that can be
    revoked only at the next login is not revoked.
    """
    conn.execute("UPDATE sessions SET revoked=1 WHERE user_id=? OR user=?",
                 (user_id, username or ""))
    _forget(lambda _sid, cached_user: cached_user == username or not username)


def _forget(match) -> None:
    """Drop cached session lookups the caller says are stale."""
    with _cache_lock:
        for token, (_, sid, user) in list(_cache.items()):
            if match(sid, user):
                _cache.pop(token, None)


def _cookie_value(src) -> str | None:
    """The raw cookie, from a Flask request or a bare WSGI environ."""
    if isinstance(src, dict):
        raw = src.get("HTTP_COOKIE", "")
        if not raw or COOKIE_NAME not in raw:
            return None
        from http.cookies import SimpleCookie

        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:                # noqa: BLE001 - a malformed jar is no cookie
            return None
        morsel = jar.get(COOKIE_NAME)
        return morsel.value if morsel else None
    return src.cookies.get(COOKIE_NAME)


def _session(src) -> tuple[str | None, str | None]:
    """(session id, username) for the cookie on this request, or (None, None).

    None when the cookie is absent, forged, expired, revoked — or when the
    account behind it has been disabled, which is why the sessions row is read
    with a join rather than on its own: disabling someone must lock them out
    of a browser they are already holding open.
    """
    token = _cookie_value(src)
    if not token:
        return None, None
    now = time.time()
    with _cache_lock:
        hit = _cache.get(token)
        if hit and hit[0] > now:
            return hit[1], hit[2]
    try:
        sid = _signer().loads(token)
    except Exception:                    # noqa: BLE001 - bad signature / tampered
        return None, None
    if not isinstance(sid, str):
        return None, None
    with _db() as conn:
        row = conn.execute(
            "SELECT s.id, s.user, s.expires_at, s.last_seen_at, s.revoked,"
            "       u.id AS uid, u.disabled"
            "  FROM sessions s"
            "  LEFT JOIN users u ON u.id = s.user_id OR u.username = s.user"
            " WHERE s.id=?", (sid,)).fetchone()
        if not row or row["revoked"] or row["uid"] is None or row["disabled"]:
            return None, None
        exp = _parse(row["expires_at"])
        if exp and exp < datetime.now(timezone.utc):
            return None, None
        # last_seen is a "when was this device last here" column for the
        # account page, not an access log — one write every few minutes is
        # plenty, and it keeps static-asset traffic read-only.
        seen = _parse(row["last_seen_at"])
        if not seen or (datetime.now(timezone.utc) - seen).total_seconds() > 300:
            conn.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (_now(), sid))
            conn.execute("UPDATE users SET last_seen_at=? WHERE id=?",
                         (_now(), row["uid"]))
            conn.commit()
    user = row["user"]
    with _cache_lock:
        _cache[token] = (now + _CACHE_TTL, sid, user)
    return sid, user


def session_id(src) -> str | None:
    """Unsign the cookie. None when absent, forged, expired or revoked."""
    return _session(src)[0]


def current_user(src) -> str | None:
    """The signed-in username, or None. Takes a Flask request OR a WSGI environ."""
    return _session(src)[1]


def set_cookie(resp, token: str):
    # Secure when the browser actually reached us over https (which on Railway
    # means reading the forwarded scheme, since TLS stops at the proxy). Tied
    # to the scheme rather than to IS_HOSTED because a Secure cookie set over
    # plain http is never sent back — the sign-in would appear to succeed and
    # then silently not hold.
    secure = _proto_host()[0] == "https"
    resp.set_cookie(COOKIE_NAME, token, max_age=SESSION_DAYS * 86400,
                    httponly=True, samesite="Lax", secure=secure, path="/")
    return resp


def clear_cookie(resp):
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


# ------------------------------------------------------- origin / rp id
#
# Railway terminates TLS at its proxy, so request.scheme is http inside the
# container while the browser saw https. WebAuthn compares the origin byte for
# byte, so the forwarded headers are what count.

def _proto_host() -> tuple[str, str]:
    proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
    host = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
    return proto or request.scheme, host or request.host


def rp_id() -> str:
    env = os.environ.get("PASSKEY_RP_ID", "").strip()
    if env:
        return env
    # The RP id is a domain, never a host:port — Safari rejects the port.
    host = _proto_host()[1]
    return host.rsplit(":", 1)[0] if ":" in host and not host.endswith("]") else host


def expected_origin() -> str:
    proto, host = _proto_host()
    return f"{proto}://{host}"


# --------------------------------------------------------------- challenges
#
# WebAuthn challenges must be remembered by the server between the two halves
# of a ceremony, and the login half happens with no session to hang them on.
# A dict with an expiry is the right size for a single-user dashboard: a
# restart loses at most an in-flight Touch ID prompt.
_CHALLENGE_TTL = 300
_challenges: dict[str, tuple[float, str, bytes]] = {}
_challenge_lock = threading.Lock()


def _stash(kind: str, challenge: bytes) -> str:
    token = secrets.token_urlsafe(18)
    now = time.time()
    with _challenge_lock:
        for k, (exp, _, _) in list(_challenges.items()):
            if exp < now:
                _challenges.pop(k, None)
        _challenges[token] = (now + _CHALLENGE_TTL, kind, challenge)
    return token


def _take(kind: str, token: str) -> bytes | None:
    """One use only — a replayed challenge is not a challenge."""
    with _challenge_lock:
        got = _challenges.pop(token or "", None)
    if not got or got[0] < time.time() or got[1] != kind:
        return None
    return got[2]


# ------------------------------------------------------------ failure limit
#
# Passwords and passkeys share one per-IP counter. Passkey verification is
# already cryptographic, but the password form on the same page is not, and an
# open /login is the one unauthenticated POST on the whole app.
_FAIL_WINDOW = 900
_FAIL_MAX = 10
_fails: dict[str, list[float]] = {}
_fail_lock = threading.Lock()


def _client_ip() -> str:
    fwd = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return fwd or request.remote_addr or "?"


def _throttled() -> bool:
    ip, now = _client_ip(), time.time()
    with _fail_lock:
        hits = [t for t in _fails.get(ip, []) if t > now - _FAIL_WINDOW]
        _fails[ip] = hits
        return len(hits) >= _FAIL_MAX


def _note_failure() -> None:
    ip, now = _client_ip(), time.time()
    with _fail_lock:
        _fails.setdefault(ip, []).append(now)
        _fails[ip] = [t for t in _fails[ip] if t > now - _FAIL_WINDOW]


# ------------------------------------------------------------------- naming

def device_name(ua: str) -> str:
    """"Mac / Safari" from a User-Agent, so a passkey list reads like devices.

    Deliberately crude: it labels a row in a list of at most a handful of
    entries, and the user can type over it.
    """
    ua = ua or ""
    os_name = ("iPhone" if "iPhone" in ua else
               "iPad" if "iPad" in ua else
               "Android" if "Android" in ua else
               "Mac" if "Macintosh" in ua or "Mac OS" in ua else
               "Windows" if "Windows" in ua else
               "Linux" if "Linux" in ua else "Device")
    browser = ("Edge" if "Edg/" in ua else
               "Chrome" if "Chrome" in ua or "CriOS" in ua else
               "Firefox" if "Firefox" in ua or "FxiOS" in ua else
               "Safari" if "Safari" in ua else "Browser")
    return f"{os_name} / {browser}"


def _safe_next(raw: str | None) -> str:
    """Only same-origin relative paths. '//evil.com' is a URL, not a path."""
    nxt = (raw or "").strip()
    if not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt:
        return "/"
    return nxt


# ------------------------------------------------------------------ queries

def _passkey_rows(conn, user_id: int):
    """Only ever your own. An admin manages people, not their devices."""
    return conn.execute(
        "SELECT id, name, created_at, last_used_at FROM passkeys"
        " WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()


def passkey_count(user_id: int | None = None) -> int:
    with _db() as conn:
        if user_id is None:
            return conn.execute("SELECT COUNT(*) FROM passkeys").fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM passkeys WHERE user_id=?",
                            (user_id,)).fetchone()[0]


def _handle(username: str) -> bytes:
    """The WebAuthn user handle for a username.

    Derived from the name rather than the row id on purpose: it is what the
    single-account version already sent, so the owner's existing passkeys keep
    the same account entry in iCloud Keychain / Windows Hello across this
    upgrade instead of appearing a second time.
    """
    return hashlib.sha256(username.encode("utf-8")).digest()


def _registration_options(conn, user_id: int | None, username: str,
                          display_name: str = ""):
    """Shared by "add this device" and the sign-up ceremony.

    resident_key REQUIRED because the login page asks for no username: the
    credential itself has to say who it belongs to.
    """
    from webauthn import generate_registration_options
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.structs import (AuthenticatorSelectionCriteria,
                                          PublicKeyCredentialDescriptor,
                                          ResidentKeyRequirement,
                                          UserVerificationRequirement)

    existing = [] if user_id is None else [
        r["credential_id"] for r in conn.execute(
            "SELECT credential_id FROM passkeys WHERE user_id=?", (user_id,))]
    return generate_registration_options(
        rp_id=rp_id(),
        rp_name=RP_NAME,
        user_id=_handle(username),
        user_name=username,
        user_display_name=display_name or username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # Discoverable, so the login page needs no username typed first.
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
            # attachment deliberately unset: platform (Touch ID, Windows
            # Hello) AND cross-platform (a phone over QR, a YubiKey) both
            # offered, because the dashboard is used from several machines.
        ),
        # Only this user's own credentials: two people sharing a laptop must
        # each be able to register on it.
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c))
                             for c in existing],
    )


def _store_passkey(conn, user_id: int, res, name: str, transports) -> None:
    from webauthn.helpers import bytes_to_base64url

    conn.execute(
        "INSERT OR REPLACE INTO passkeys (credential_id, public_key,"
        " sign_count, transports, aaguid, name, created_at, user_id)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (bytes_to_base64url(res.credential_id), res.credential_public_key,
         res.sign_count, json.dumps(transports or []), res.aaguid,
         name, _now(), user_id))


# --------------------------------------------------------- passkey: register

@bp.post("/api/passkeys/register/options")
def passkey_register_options():
    """Add a device to the account that is already signed in."""
    from webauthn import options_to_json

    acct = account()
    if not acct:
        return jsonify({"error": "auth_required"}), 401
    with _db() as conn:
        opts = _registration_options(conn, acct["id"], acct["username"],
                                     acct["display_name"])
    token = _stash("register", opts.challenge)
    return jsonify({"token": token, "options": json.loads(options_to_json(opts))})


@bp.post("/api/passkeys/register/verify")
def passkey_register_verify():
    from webauthn import verify_registration_response

    acct = account()
    if not acct:
        return jsonify({"error": "auth_required"}), 401
    body = request.get_json(silent=True) or {}
    challenge = _take("register", body.get("token"))
    if challenge is None:
        return jsonify({"error": "challenge_expired"}), 400
    try:
        res = verify_registration_response(
            credential=body.get("credential"),
            expected_challenge=challenge,
            expected_rp_id=rp_id(),
            expected_origin=expected_origin())
    except Exception as e:               # noqa: BLE001 - any failure is one failure
        return jsonify({"error": "verification_failed", "message": str(e)}), 400

    ua = request.headers.get("User-Agent", "")
    name = (body.get("name") or "").strip()[:60] or device_name(ua)
    transports = ((body.get("credential") or {}).get("response") or {}).get("transports")
    with _db() as conn:
        _store_passkey(conn, acct["id"], res, name, transports)
        conn.commit()
    return jsonify({"ok": True, "name": name})


# ------------------------------------------------------------ passkey: login

@bp.post("/api/passkeys/login/options")
def passkey_login_options():
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers.structs import UserVerificationRequirement

    if _throttled():
        return jsonify({"error": "too_many_attempts"}), 429
    opts = generate_authentication_options(
        rp_id=rp_id(),
        # Empty on purpose: the credentials are discoverable, so the browser
        # offers whatever it holds for this domain and nothing here has to
        # leak which passkeys exist to an unauthenticated caller.
        allow_credentials=[],
        user_verification=UserVerificationRequirement.PREFERRED)
    token = _stash("login", opts.challenge)
    return jsonify({"token": token, "options": json.loads(options_to_json(opts))})


@bp.post("/api/passkeys/login/verify")
def passkey_login_verify():
    from webauthn import verify_authentication_response

    if _throttled():
        return jsonify({"error": "too_many_attempts"}), 429
    body = request.get_json(silent=True) or {}
    challenge = _take("login", body.get("token"))
    cred = body.get("credential") or {}
    if challenge is None:
        return jsonify({"error": "challenge_expired"}), 400
    cred_id = cred.get("id") or ""
    with _db() as conn:
        # credential -> passkeys.user_id -> users: the credential is the only
        # thing that says who this is, which is exactly why the page can ask
        # for no username.
        row = conn.execute(
            "SELECT p.id, p.public_key, p.sign_count, p.user_id,"
            "       u.username, u.disabled"
            "  FROM passkeys p LEFT JOIN users u ON u.id = p.user_id"
            " WHERE p.credential_id=?", (cred_id,)).fetchone()
        if not row or row["username"] is None:
            _note_failure()
            return jsonify({"error": "unknown_passkey"}), 400
        if row["disabled"]:
            _note_failure()
            return jsonify({"error": "account_disabled",
                            "message": "That account has been switched off."}), 403
        try:
            res = verify_authentication_response(
                credential=cred,
                expected_challenge=challenge,
                expected_rp_id=rp_id(),
                expected_origin=expected_origin(),
                credential_public_key=row["public_key"],
                credential_current_sign_count=row["sign_count"] or 0)
        except Exception as e:           # noqa: BLE001
            _note_failure()
            return jsonify({"error": "verification_failed", "message": str(e)}), 400
        conn.execute("UPDATE passkeys SET sign_count=?, last_used_at=? WHERE id=?",
                     (res.new_sign_count, _now(), row["id"]))
        conn.commit()
        username, uid = row["username"], row["user_id"]

    token = create_session(username, request.headers.get("User-Agent", ""), uid)
    resp = jsonify({"ok": True, "user": username,
                    "next": _safe_next(body.get("next"))})
    return set_cookie(resp, token)


# ------------------------------------------------------- passkey management

@bp.get("/api/passkeys")
def passkeys_list():
    """Your devices and your signed-in browsers. Never anybody else's."""
    acct = account()
    if not acct:
        return jsonify({"error": "auth_required"}), 401
    here = session_id(request)
    with _db() as conn:
        keys = [dict(r) for r in _passkey_rows(conn, acct["id"])]
        sessions = [{
            "id": r["id"], "created_at": r["created_at"],
            "last_seen_at": r["last_seen_at"], "user_agent": r["user_agent"],
            "label": device_name(r["user_agent"] or ""),
            "current": r["id"] == here,
        } for r in conn.execute(
            "SELECT id, created_at, last_seen_at, user_agent FROM sessions"
            " WHERE revoked=0 AND expires_at > ? AND (user_id=? OR user=?)"
            " ORDER BY last_seen_at DESC",
            (_now(), acct["id"], acct["username"]))]
    return jsonify({"passkeys": keys, "sessions": sessions})


@bp.delete("/api/passkeys/<int:key_id>")
def passkey_delete(key_id: int):
    acct = account()
    if not acct:
        return jsonify({"error": "auth_required"}), 401
    with _db() as conn:
        cur = conn.execute("DELETE FROM passkeys WHERE id=? AND user_id=?",
                           (key_id, acct["id"]))
        conn.commit()
    if not cur.rowcount:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ok": True})


@bp.post("/api/sessions/<sid>/revoke")
def session_revoke(sid: str):
    acct = account()
    if not acct:
        return jsonify({"error": "auth_required"}), 401
    with _db() as conn:
        own = conn.execute(
            "SELECT id FROM sessions WHERE id=? AND (user_id=? OR user=?)",
            (sid, acct["id"], acct["username"])).fetchone()
    if not own:
        return jsonify({"error": "not_found"}), 404
    here = session_id(request)
    revoke_session(sid)
    resp = jsonify({"ok": True, "self": sid == here})
    if sid == here:
        clear_cookie(resp)
    return resp


# ----------------------------------------------------------------- invites
#
# A token is a bearer secret, so only its sha256 is ever stored: the table is
# worthless to anyone who can read it, and the raw string exists exactly once
# — in the body of the POST that created it. There is no "show me that token
# again", by design.

def _token_hash(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def _invite_state(row) -> str:
    if row is None:
        return "unknown"
    if row["revoked"]:
        return "revoked"
    if row["used_at"]:
        return "used"
    exp = _parse(row["expires_at"])
    if exp and exp < datetime.now(timezone.utc):
        return "expired"
    return "ok"


_INVITE_COPY = {
    "unknown": "That sign-up link is not valid.",
    "revoked": "That sign-up link has been withdrawn.",
    "used": "That sign-up link has already been used.",
    "expired": "That sign-up link has expired.",
}


def _invite_for(conn, raw: str):
    """(row, state) for a raw token."""
    row = conn.execute("SELECT * FROM invites WHERE token_hash=?",
                       (_token_hash(raw),)).fetchone() if raw else None
    return row, _invite_state(row)


def _invite_public(row, users: dict) -> dict:
    who = users.get(row["created_by"])
    target = users.get(row["user_id"])
    return {
        "id": row["id"], "role": row["role"],
        "privileges": clean_privileges(_json_list(row["privileges"])),
        "note": row["note"], "created_at": row["created_at"],
        "expires_at": row["expires_at"], "used_at": row["used_at"],
        "revoked": bool(row["revoked"]),
        "state": _invite_state(row),
        "created_by": who["username"] if who else None,
        # A re-register invite belongs to somebody already; say whose.
        "for_user": target["username"] if target else None,
    }


def _usernames(conn) -> dict:
    return {r["id"]: r for r in conn.execute(
        "SELECT id, username, display_name FROM users")}


def _origin() -> str:
    return expected_origin()


def _mint_invite(conn, *, role: str, privileges: list, note: str,
                 days: int, created_by: int, user_id: int | None = None) -> dict:
    raw = secrets.token_urlsafe(24)
    expires = (datetime.now(timezone.utc)
               + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute(
        "INSERT INTO invites (token_hash, role, privileges, note, user_id,"
        " created_by, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
        (_token_hash(raw), role, json.dumps(privileges), note or None,
         user_id, created_by, _now(), expires))
    conn.commit()
    return {"id": cur.lastrowid, "token": raw,
            "url": f"{_origin()}/signup?token={raw}",
            "role": role, "privileges": privileges, "note": note or None,
            "expires_at": expires, "state": "ok"}


@bp.get("/api/invites")
@require_priv("admin")
def invites_list():
    with _db() as conn:
        users = _usernames(conn)
        rows = conn.execute(
            "SELECT * FROM invites ORDER BY used_at IS NOT NULL, revoked,"
            " id DESC").fetchall()
    return jsonify({"invites": [_invite_public(r, users) for r in rows]})


@bp.post("/api/invites")
@require_priv("admin")
def invite_create():
    acct = account()
    body = request.get_json(silent=True) or {}
    role = str(body.get("role") or "member").lower()
    if role not in ("admin", "member"):
        return jsonify({"error": "bad_role"}), 400
    # An admin may hand out member seats; making another admin is the owner's
    # call, the same way an admin cannot promote anyone to admin.
    if role == "admin" and not acct["is_owner"]:
        return jsonify({"error": "forbidden", "need": "owner"}), 403
    try:
        days = max(1, min(int(body.get("days") or INVITE_DAYS), 90))
    except (TypeError, ValueError):
        days = INVITE_DAYS
    privileges = clean_privileges(body.get("privileges"))
    if role == "member" and "admin" in privileges:
        privileges = [p for p in privileges if p != "admin"]
    with _db() as conn:
        made = _mint_invite(conn, role=role, privileges=privileges,
                            note=str(body.get("note") or "").strip()[:200],
                            days=days, created_by=acct["id"])
    # The one and only time the raw token is in a response body.
    return jsonify(made), 201


@bp.delete("/api/invites/<int:invite_id>")
@require_priv("admin")
def invite_revoke(invite_id: int):
    with _db() as conn:
        cur = conn.execute("UPDATE invites SET revoked=1 WHERE id=?",
                           (invite_id,))
        conn.commit()
    if not cur.rowcount:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ok": True})


# ------------------------------------------------------------------- people

def _may_edit(actor: dict, target) -> str | None:
    """None if the edit is allowed, else the reason it is not."""
    if target["role"] == "owner":
        return "The owner account cannot be changed from here."
    if target["role"] == "admin" and not actor["is_owner"]:
        return "Only the owner can change another admin."
    if target["id"] == actor["id"] and not actor["is_owner"]:
        return "You cannot change your own role or privileges."
    return None


@bp.get("/api/users")
@require_priv("admin")
def users_list():
    with _db() as conn:
        counts = {r["user_id"]: r["n"] for r in conn.execute(
            "SELECT user_id, COUNT(*) AS n FROM passkeys GROUP BY user_id")}
        rows = conn.execute(
            "SELECT * FROM users ORDER BY role='owner' DESC, role='admin' DESC,"
            " username").fetchall()
    return jsonify({"users": [_user_public(r, counts.get(r["id"], 0))
                              for r in rows]})


@bp.patch("/api/users/<int:user_id>")
@require_priv("admin")
def user_patch(user_id: int):
    acct = account()
    body = request.get_json(silent=True) or {}
    with _db() as conn:
        target = _by_id(conn, user_id)
        if not target:
            return jsonify({"error": "not_found"}), 404
        why = _may_edit(acct, target)
        if why:
            return jsonify({"error": "forbidden", "message": why}), 403

        sets, vals = [], []
        if "display_name" in body:
            sets.append("display_name=?")
            vals.append(str(body.get("display_name") or "").strip()[:60]
                        or target["username"])
        if "role" in body:
            role = str(body.get("role") or "").lower()
            if role not in ("admin", "member"):
                return jsonify({"error": "bad_role"}), 400
            if not acct["is_owner"]:
                return jsonify({"error": "forbidden",
                                "message": "Only the owner sets roles."}), 403
            sets.append("role=?")
            vals.append(role)
        # A member never carries the 'admin' privilege (same rule as invites):
        # admin is a role, granted by the owner, not a tick box.
        final_role = role if "role" in body else target["role"]
        if "privileges" in body or ("role" in body and final_role == "member"):
            privs = clean_privileges(body.get("privileges") if "privileges" in body
                                     else _json_list(target["privileges"]))
            if final_role == "member":
                privs = [p for p in privs if p != "admin"]
            sets.append("privileges=?")
            vals.append(json.dumps(privs))
        if "disabled" in body:
            sets.append("disabled=?")
            vals.append(1 if body.get("disabled") else 0)
        if not sets:
            return jsonify({"error": "nothing_to_update"}), 400
        conn.execute(f"UPDATE users SET {','.join(sets)} WHERE id=?",
                     vals + [user_id])
        # A privilege you keep until you next sign in is not revoked: switch
        # the account off and every browser holding it goes with it.
        if body.get("disabled"):
            revoke_user_sessions(conn, user_id, target["username"])
        conn.commit()
        fresh = _by_id(conn, user_id)
        n = passkey_count(user_id)
    return jsonify(_user_public(fresh, n))


@bp.delete("/api/users/<int:user_id>")
@require_priv("admin")
def user_delete(user_id: int):
    acct = account()
    with _db() as conn:
        target = _by_id(conn, user_id)
        if not target:
            return jsonify({"error": "not_found"}), 404
        why = _may_edit(acct, target)
        if why:
            return jsonify({"error": "forbidden", "message": why}), 403
        revoke_user_sessions(conn, user_id, target["username"])
        conn.execute("DELETE FROM passkeys WHERE user_id=?", (user_id,))
        conn.execute("UPDATE invites SET revoked=1"
                     " WHERE user_id=? AND used_at IS NULL", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    return jsonify({"ok": True, "deleted": target["username"]})


@bp.post("/api/users/<int:user_id>/reinvite")
@require_priv("admin")
def user_reinvite(user_id: int):
    """A fresh sign-up link for somebody who lost every device.

    This is the whole recovery story for a passkey-only account: no temporary
    password to leak, no reset mail to intercept. The link opens /signup in
    re-register mode — no name fields, one passkey prompt — and attaches the
    new credential to the account that already exists.
    """
    acct = account()
    body = request.get_json(silent=True) or {}
    try:
        days = max(1, min(int(body.get("days") or 2), 30))
    except (TypeError, ValueError):
        days = 2
    with _db() as conn:
        target = _by_id(conn, user_id)
        if not target:
            return jsonify({"error": "not_found"}), 404
        if target["role"] == "owner":
            return jsonify({"error": "forbidden",
                            "message": "The owner signs in with the "
                                       "environment password."}), 403
        if target["role"] == "admin" and not acct["is_owner"]:
            return jsonify({"error": "forbidden",
                            "message": "Only the owner can do that."}), 403
        made = _mint_invite(
            conn, role=target["role"],
            privileges=clean_privileges(_json_list(target["privileges"])),
            note=f"Re-register {target['username']}", days=days,
            created_by=acct["id"], user_id=user_id)
    return jsonify({**made, "for_user": target["username"]}), 201


# ------------------------------------------------------------------ sign-up
#
# The ONLY way a non-owner account comes into existence, and it is passkey
# first: /api/signup validates the token and hands back registration options,
# /api/signup/verify writes the user, the credential, the session and the
# "invite used" flag in one transaction. Abandon the page half way and
# nothing was created and no token was spent.

_SIGNUP_TTL = 600
_signups: dict[str, tuple[float, bytes, dict]] = {}
_signup_lock = threading.Lock()


def _stash_signup(challenge: bytes, data: dict) -> str:
    token = secrets.token_urlsafe(18)
    now = time.time()
    with _signup_lock:
        for k, (exp, _, _) in list(_signups.items()):
            if exp < now:
                _signups.pop(k, None)
        _signups[token] = (now + _SIGNUP_TTL, challenge, data)
    return token


def _take_signup(token: str):
    with _signup_lock:
        got = _signups.pop(token or "", None)
    if not got or got[0] < time.time():
        return None
    return got[1], got[2]


@bp.post("/api/signup")
def api_signup():
    """Step one: check the invite, reserve the name, return passkey options."""
    from webauthn import options_to_json

    if _throttled():
        return jsonify({"error": "too_many_attempts"}), 429
    body = request.get_json(silent=True) or {}
    raw = str(body.get("token") or "").strip()
    with _db() as conn:
        invite, state = _invite_for(conn, raw)
        if state != "ok":
            _note_failure()
            return jsonify({"error": "invite_" + state,
                            "message": _INVITE_COPY[state]}), 400

        if invite["user_id"]:
            # Re-register: the account exists, only the device is new.
            target = _by_id(conn, invite["user_id"])
            if not target or target["disabled"]:
                return jsonify({"error": "invite_unknown",
                                "message": _INVITE_COPY["unknown"]}), 400
            username = target["username"]
            display = target["display_name"] or username
            opts = _registration_options(conn, target["id"], username, display)
            data = {"invite": invite["id"], "user_id": target["id"],
                    "username": username, "display_name": display}
        else:
            username = clean_username(body.get("username"))
            if not username:
                return jsonify({
                    "error": "bad_username",
                    "message": "Pick 3–32 letters, numbers, dots, dashes or "
                               "underscores."}), 400
            if username == DASH_USER.lower() or _by_username(conn, username):
                return jsonify({"error": "username_taken",
                                "message": "That username is taken."}), 409
            display = str(body.get("display_name") or "").strip()[:60] or username
            opts = _registration_options(conn, None, username, display)
            data = {"invite": invite["id"], "user_id": None,
                    "username": username, "display_name": display,
                    "role": invite["role"],
                    "privileges": clean_privileges(_json_list(invite["privileges"]))}

    token = _stash_signup(opts.challenge, data)
    return jsonify({"token": token, "username": username,
                    "display_name": display,
                    "mode": "reregister" if data["user_id"] else "new",
                    "options": json.loads(options_to_json(opts))})


@bp.post("/api/signup/verify")
def api_signup_verify():
    """Step two: the passkey exists, so now the account does too."""
    from webauthn import verify_registration_response

    if _throttled():
        return jsonify({"error": "too_many_attempts"}), 429
    body = request.get_json(silent=True) or {}
    got = _take_signup(body.get("token"))
    if got is None:
        return jsonify({"error": "challenge_expired",
                        "message": "That took too long — start again."}), 400
    challenge, data = got
    try:
        res = verify_registration_response(
            credential=body.get("credential"),
            expected_challenge=challenge,
            expected_rp_id=rp_id(),
            expected_origin=expected_origin())
    except Exception as e:               # noqa: BLE001
        _note_failure()
        return jsonify({"error": "verification_failed", "message": str(e)}), 400

    ua = request.headers.get("User-Agent", "")
    name = (body.get("name") or "").strip()[:60] or device_name(ua)
    transports = ((body.get("credential") or {}).get("response") or {}).get("transports")
    with _db() as conn:
        # The invite is re-checked here, not only in step one: two tabs, a
        # slow Touch ID prompt and a revoke in between are all real.
        invite = conn.execute("SELECT * FROM invites WHERE id=?",
                              (data["invite"],)).fetchone()
        if _invite_state(invite) != "ok":
            state = _invite_state(invite)
            return jsonify({"error": "invite_" + state,
                            "message": _INVITE_COPY[state]}), 400
        uid = data["user_id"]
        if uid is None:
            if _by_username(conn, data["username"]):
                return jsonify({"error": "username_taken",
                                "message": "That username is taken."}), 409
            cur = conn.execute(
                "INSERT INTO users (username, display_name, role, privileges,"
                " created_at, created_by) VALUES (?,?,?,?,?,?)",
                (data["username"], data["display_name"], data["role"],
                 json.dumps(data["privileges"]), _now(), invite["created_by"]))
            uid = cur.lastrowid
        _store_passkey(conn, uid, res, name, transports)
        conn.execute("UPDATE invites SET used_at=?, used_by=? WHERE id=?",
                     (_now(), uid, invite["id"]))
        conn.commit()
        username = _by_id(conn, uid)["username"]

    token = create_session(username, ua, uid)
    resp = jsonify({"ok": True, "user": username, "next": "/"})
    return set_cookie(resp, token)


@bp.post("/logout")
def logout():
    sid = session_id(request)
    if sid:
        revoke_session(sid)
    # A form post (the login page's fallback) wants a page back; fetch() from
    # the account page wants nothing at all.
    if "text/html" in (request.headers.get("Accept") or "") \
            and not request.is_json:
        return clear_cookie(make_response(redirect("/login")))
    return clear_cookie(make_response("", 204))


@bp.get("/api/me")
def api_me():
    """Who the caller is, what they may do, and how they got in.

    `user` is kept as the username for the callers that predate accounts.
    """
    acct = account()
    if not acct:
        return jsonify({"error": "auth_required"}), 401
    via = {"session": "passkey_or_password"}.get(acct["via"], acct["via"])
    return jsonify({**acct, "via": via, "user": acct["username"],
                    "passkeys": passkey_count(acct["id"])})


@bp.patch("/api/me")
def api_me_patch():
    """Your own display name, and nothing else.

    Everything that carries authority — role, privileges, disabled — is an
    admin's to set, including on your own row; what you are CALLED is yours.
    """
    acct = account()
    if not acct:
        return jsonify({"error": "auth_required"}), 401
    body = request.get_json(silent=True) or {}
    if "display_name" not in body:
        return jsonify({"error": "nothing_to_update"}), 400
    name = str(body.get("display_name") or "").strip()[:60] or acct["username"]
    with _db() as conn:
        conn.execute("UPDATE users SET display_name=? WHERE id=?",
                     (name, acct["id"]))
        conn.commit()
        fresh = _by_id(conn, acct["id"])
    # The same shape GET /api/me answers with, so the page can assign it
    # straight over its copy.
    via = {"session": "passkey_or_password"}.get(acct["via"], acct["via"])
    return jsonify({**_user_public(fresh, passkey_count(acct["id"])),
                    "via": via, "user": fresh["username"]})


# --------------------------------------------------------------- login page
#
# Self-contained by necessity, not by taste: /_app (the SvelteKit bundle) is
# behind the auth gate, so a login page built from it could never load for
# someone who is not yet signed in. Inline CSS and JS, one file, no imports.

_SCENE_CSS = """  /* Studio Glass, hand-inlined. This page cannot import ui/src/lib/mc.css
     — the bundle lives behind the auth gate — so the subset it needs (the
     --mc-* tokens, the backdrop, the glass card, .mg-btn, .mg-input,
     .mg-strip, .mg-label) is copied here. If the vocabulary changes there,
     change it here. Always dark: the card is a pane of strong glass floating
     over the photograph of the hour (__HERO__), on deep graphite so a slow
     photo never shows as a white flash. */
  :root {
    --mc-bg: #111113;
    --mc-glass-strong: rgba(14, 14, 18, 0.74);
    --mc-glass-soft: rgba(255, 255, 255, 0.06);
    --mc-glass-hover: rgba(255, 255, 255, 0.1);
    --mc-glass-line: rgba(255, 255, 255, 0.12);
    --mc-glass-line2: rgba(255, 255, 255, 0.22);
    --mc-surface: var(--mc-glass-soft);
    --mc-raised: var(--mc-glass-hover);
    --mc-inset: rgba(8, 8, 10, 0.6);
    --mc-line: var(--mc-glass-line);
    --mc-line2: var(--mc-glass-line2);
    --mc-ink: #f3f3f4;
    --mc-ink2: #a7a7b0;
    --mc-ink3: #6d6d78;
    --mc-accent: #3ecf8e;
    --mc-crit: #f26d64;
    --mc-font: 'Inter', -apple-system, BlinkMacSystemFont, system-ui, 'Segoe UI', sans-serif;
    --mc-mono: 'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace;
    --mc-ease: cubic-bezier(0.2, 0.8, 0.2, 1);
    --mc-blur: 28px;
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html { min-height: 100%; background: var(--mc-bg); }
  body, .mg-scene {
    margin: 0; min-height: 100vh; min-height: 100svh; position: relative;
    color-scheme: dark; color: var(--mc-ink);
    font-family: var(--mc-font); font-size: 14px; line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    background: var(--mc-bg);
    background-image: radial-gradient(120% 90% at 50% 0%, #1b1b21 0%, #111113 45%, #0a0a0c 100%);
    display: grid; place-items: center;
    padding: 32px 16px calc(32px + env(safe-area-inset-bottom, 0px));
  }
  :focus-visible { outline: 2px solid rgba(62, 207, 142, 0.7); outline-offset: 2px; }
  a { color: var(--mc-ink2); text-decoration: underline; text-decoration-color: var(--mc-line2);
      text-underline-offset: 3px; }
  a:hover { color: var(--mc-ink); }

  /* the photograph: full bleed, a 90s drift, a veil, and a scrim at each end */
  .backdrop { position: fixed; inset: 0; z-index: 0; overflow: hidden; pointer-events: none; }
  .shot {
    position: absolute; inset: 0; background: url(/hero-__HERO__.jpg) center / cover no-repeat;
    animation: mg-drift 90s ease-in-out infinite alternate; will-change: transform;
  }
  .dim { position: absolute; inset: 0; background: rgba(6, 6, 8, 0.2); }
  .top { position: absolute; left: 0; right: 0; top: 0; height: 32%;
         background: linear-gradient(180deg, rgba(0, 0, 0, 0.55), transparent); }
  .bot { position: absolute; left: 0; right: 0; bottom: 0; height: 42%;
         background: linear-gradient(0deg, rgba(0, 0, 0, 0.7), transparent); }
  @keyframes mg-drift { from { transform: scale(1); } to { transform: scale(1.06); } }
  @keyframes mg-rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }

  /* the card: strong glass, a lit top edge, 22px corners */
  .mg-glass-strong {
    background: var(--mc-glass-strong);
    border: 1px solid var(--mc-glass-line);
    border-radius: 22px;
    box-shadow: 0 24px 64px -16px rgba(0, 0, 0, 0.65), inset 0 1px 0 rgba(255, 255, 255, 0.07);
    -webkit-backdrop-filter: blur(var(--mc-blur)) saturate(150%);
    backdrop-filter: blur(var(--mc-blur)) saturate(150%);
  }
  .card {
    position: relative; z-index: 1; width: 100%; max-width: 400px;
    padding: 28px 28px 24px;
    animation: mg-rise 0.32s var(--mc-ease) both;
  }

  /* wordmark: a green dot and the name */
  .logo { display: flex; align-items: center; gap: 8px; margin-bottom: 28px; }
  .mark { width: 8px; height: 8px; border-radius: 50%; background: var(--mc-accent); flex: none; }
  .name { font: 600 14px/1 var(--mc-font); letter-spacing: -0.01em; color: var(--mc-ink); }
  .sub { margin-left: 2px; font: 500 11px/1 var(--mc-font); letter-spacing: 0.01em; color: var(--mc-ink3); }

  h1 { margin: 0 0 4px; font: 650 22px/1.2 var(--mc-font); letter-spacing: -0.02em;
       color: var(--mc-ink); }
  .who { margin: 0 0 20px; font: 400 13px/1.5 var(--mc-font); color: var(--mc-ink2); }
  button, input { font: inherit; }

  /* .mg-strip.crit — the error: a slim red-tinted notice */
  .mg-strip {
    display: flex; align-items: flex-start; gap: 10px;
    padding: 10px 14px; margin-bottom: 16px; border-radius: 14px;
    background: var(--mc-glass-soft); border: 1px solid var(--mc-glass-line);
    font: 400 12.5px/1.5 var(--mc-font); color: var(--mc-ink2);
  }
  .mg-strip.crit { background: rgba(242, 109, 100, 0.14); border-color: rgba(242, 109, 100, 0.3);
                   color: var(--mc-crit); }

  /* .mg-btn — a 44px pill. `.primary` is the white one. */
  .mg-btn {
    display: inline-flex; align-items: center; justify-content: center; gap: 8px;
    flex: none; height: 44px; padding: 0 20px;
    border: 1px solid transparent; border-radius: 9999px; background: none;
    color: var(--mc-ink); font: 500 14px/1 var(--mc-font); letter-spacing: -0.005em;
    white-space: nowrap; cursor: pointer; user-select: none; -webkit-user-select: none;
    transition: background 0.15s, border-color 0.15s, color 0.15s, transform 0.12s var(--mc-ease);
  }
  .mg-btn:active:not(:disabled) { transform: scale(0.97); }
  .mg-btn:disabled { opacity: 0.4; pointer-events: none; }
  .mg-btn.primary { background: var(--mc-ink); color: var(--mc-bg); font-weight: 600; }
  .mg-btn.primary:hover { background: #ffffff; }
  .mg-btn.secondary { background: var(--mc-glass-soft); border-color: var(--mc-glass-line); color: var(--mc-ink); }
  .mg-btn.secondary:hover { background: var(--mc-glass-hover); border-color: var(--mc-glass-line2); }
  .mg-btn.lg { min-height: 44px; font-size: 14px; }

  /* The passkey sign-in is the secondary: frosted, its hint as a second line
     inside it (the script toggles the one node). The password submit under
     it is the white primary. */
  #pk { width: 100%; flex-direction: column; gap: 4px; height: auto; min-height: 56px;
        padding: 10px 20px; line-height: 1.25; white-space: normal; text-align: center;
        background: var(--mc-glass-soft); border-color: var(--mc-glass-line); color: var(--mc-ink);
        font-weight: 600; }
  #pk:hover { background: var(--mc-glass-hover); border-color: var(--mc-glass-line2); }
  #pk small { font: 400 12px/1.35 var(--mc-font); letter-spacing: 0; color: var(--mc-ink3); }

  /* the divider: two hairlines and a quiet word */
  .or { display: flex; align-items: center; gap: 12px; margin: 18px 0 16px;
        color: var(--mc-ink3); font: 500 11px/1 var(--mc-font); letter-spacing: 0.01em; }
  .or::before, .or::after { content: ''; flex: 1; height: 1px; background: var(--mc-glass-line); }

  /* .mg-label + .mg-input — a frosted field with a lit hairline on focus */
  .mg-label { display: block; font: 500 11px/1.4 var(--mc-font); letter-spacing: 0.01em;
              color: var(--mc-ink3); margin-bottom: 8px; }
  .mg-input {
    width: 100%; height: 44px; padding: 0 14px;
    background: var(--mc-glass-soft); border: 1px solid var(--mc-glass-line);
    border-radius: 14px; color: var(--mc-ink);
    font: 400 15px/1 var(--mc-font); outline: none;
    transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
  }
  .mg-input::placeholder { color: var(--mc-ink3); }
  .mg-input:hover { border-color: var(--mc-glass-line2); }
  .mg-input:focus { border-color: var(--mc-glass-line2); background: rgba(255, 255, 255, 0.08);
                    box-shadow: 0 0 0 3px rgba(62, 207, 142, 0.14); }
  .mg-btn.go { width: 100%; margin-top: 12px; background: var(--mc-ink); color: var(--mc-bg);
        border-color: transparent; font-weight: 600; }
  .mg-btn.go:hover { background: #ffffff; border-color: transparent; }

  .foot { margin: 20px 0 0; padding-top: 16px; border-top: 1px solid var(--mc-glass-line);
          font: 400 12px/1.5 var(--mc-font); color: var(--mc-ink3); }
  .foot + .foot { margin-top: 8px; padding-top: 0; border-top: 0; }

  @media (max-width: 440px) {
    body { padding: 20px 16px calc(20px + env(safe-area-inset-bottom, 0px)); }
    .card { padding: 24px 20px 20px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .shot { animation: none; }
    .card { animation: none; opacity: 1; transform: none; }
    .mg-btn:active:not(:disabled) { transform: none; }
  }
"""


_LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="color-scheme" content="dark" />
<title>Sign in · Oblivion</title>
<link rel="icon" href="/favicon.svg" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..800&family=IBM+Plex+Mono:wght@400;600&display=swap" rel="stylesheet" />
<style>
__CSS__</style>
</head>
<body class="mg-scene">
  <div class="backdrop" aria-hidden="true">
    <div class="shot"></div>
    <div class="dim"></div>
    <div class="top"></div>
    <div class="bot"></div>
  </div>

  <main class="card mg-glass-strong">
    <div class="logo"><span class="mark"></span>
      <span class="name">Oblivion</span><span class="sub">Prospect Engine</span></div>
    <h1>Sign in</h1>
    <p class="who">Signing in as __USER__</p>

    <div id="err" class="mg-strip crit" style="display:__ERRSHOW__">__ERROR__</div>

    <button class="mg-btn primary lg" id="pk" style="display:none" type="button">
      Sign in with passkey
      <small>Touch ID, Windows Hello, or your phone</small>
    </button>

    <div class="or" id="or" style="display:none">or</div>

    <form method="post" action="/login">
      <input type="hidden" name="next" value="__NEXT__" />
      <input type="hidden" name="username" value="__USER__" />
      <label class="mg-label" for="pw">Password</label>
      <input id="pw" class="mg-input" type="password" name="password"
             autocomplete="current-password" autofocus required />
      <button class="mg-btn secondary go" type="submit">Sign in</button>
    </form>

    <p class="foot">Scripts and curl still use HTTP basic auth with the same
      password.</p>
  </main>
<script>
  var NEXT = __NEXTJSON__;
  var err = document.getElementById('err');
  function fail(msg) { err.textContent = msg; err.style.display = ''; }

  // base64url <-> ArrayBuffer. Written out rather than pulled from a library:
  // this page must stand alone, with no bundle behind the auth gate.
  function b64uToBuf(s) {
    s = String(s).replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    var bin = atob(s), buf = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return buf.buffer;
  }
  function bufToB64u(b) {
    var bytes = new Uint8Array(b), s = '';
    for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, '');
  }

  if (window.PublicKeyCredential) {
    document.getElementById('pk').style.display = '';
    document.getElementById('or').style.display = '';
  }

  document.getElementById('pk').addEventListener('click', async function () {
    var btn = this;
    btn.disabled = true;
    err.style.display = 'none';
    try {
      var r = await fetch('/api/passkeys/login/options', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      var got = await r.json();
      if (!r.ok) throw new Error(got.error === 'too_many_attempts'
        ? 'Too many attempts. Wait a few minutes.' : (got.message || got.error));
      var o = got.options;
      o.challenge = b64uToBuf(o.challenge);
      (o.allowCredentials || []).forEach(function (c) { c.id = b64uToBuf(c.id); });
      // mediation 'optional' lets the browser fill silently when it can.
      var cred = await navigator.credentials.get({ publicKey: o, mediation: 'optional' });
      if (!cred) throw new Error('cancelled');
      var payload = {
        id: cred.id, rawId: bufToB64u(cred.rawId), type: cred.type,
        authenticatorAttachment: cred.authenticatorAttachment || undefined,
        clientExtensionResults: cred.getClientExtensionResults(),
        response: {
          clientDataJSON: bufToB64u(cred.response.clientDataJSON),
          authenticatorData: bufToB64u(cred.response.authenticatorData),
          signature: bufToB64u(cred.response.signature),
          userHandle: cred.response.userHandle ? bufToB64u(cred.response.userHandle) : null
        }
      };
      var v = await fetch('/api/passkeys/login/verify', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: got.token, credential: payload, next: NEXT }) });
      var out = await v.json();
      if (!v.ok || !out.ok) throw new Error(out.message || out.error || 'rejected');
      location.href = out.next || NEXT || '/';
    } catch (e) {
      btn.disabled = false;
      var m = String(e && e.message || e);
      if (e && (e.name === 'NotAllowedError' || m === 'cancelled')) {
        fail('No passkey on this device yet. Sign in with your password, then '
           + 'add this device from Account.');
      } else { fail(m); }
    }
  });
</script>
</body>
</html>
"""


def _render_login(next_path: str, error: str = "") -> Response:
    import html as _html

    # The hero is picked here rather than in the browser: the same four files
    # and the same thresholds as components/glass/Backdrop.svelte (20-05
    # night, before 10 morning, before 17 day, else dusk), so the sign-in is
    # lit like the hour you opened it — and the photo is in the HTML, not one frame later.
    hour = datetime.now().hour
    hero = ("night" if hour >= 20 or hour < 5 else "morning" if hour < 10
            else "day" if hour < 17 else "dusk")

    # __CSS__ first: the stylesheet itself carries the __HERO__ placeholder.
    page = (_LOGIN_HTML
            .replace("__CSS__", _SCENE_CSS)
            .replace("__HERO__", hero)
            .replace("__USER__", _html.escape(DASH_USER))
            .replace("__NEXTJSON__", json.dumps(next_path))
            .replace("__NEXT__", _html.escape(next_path, quote=True))
            .replace("__ERRSHOW__", "" if error else "none")
            .replace("__ERROR__", _html.escape(error)))
    return Response(page, 200, {"Content-Type": "text/html; charset=utf-8",
                                "Cache-Control": "no-store"})


def _no_password_page() -> Response:
    return Response(
        "DASHBOARD_PASSWORD is not set. Refusing to serve the prospect "
        "dashboard unauthenticated on a public host.\n"
        "Set it with:  railway variables --set DASHBOARD_PASSWORD=...",
        503, {"Content-Type": "text/plain"})


@bp.get("/login")
def login_page():
    if IS_HOSTED and not DASH_PASS:
        return _no_password_page()
    nxt = _safe_next(request.args.get("next"))
    if session_id(request) or basic_ok(request) or not DASH_PASS:
        return redirect(nxt)
    return _render_login(nxt)


@bp.post("/login")
def login_submit():
    from werkzeug.datastructures import Authorization

    if IS_HOSTED and not DASH_PASS:
        return _no_password_page()
    nxt = _safe_next(request.form.get("next"))
    if _throttled():
        return _render_login(nxt, "Too many attempts. Wait a few minutes and try again.")
    # The password form is the OWNER's door and only the owner's: every other
    # account is passkey-only, so there is no member password to get wrong
    # here and no username to guess. They use the button above it.
    supplied = request.form.get("password") or ""
    if not credentials_ok(Authorization("basic", {"username": DASH_USER,
                                                  "password": supplied})):
        _note_failure()
        return _render_login(nxt, "That password is not right.")
    with _db() as conn:
        owner = owner_row(conn)
    token = create_session(owner["username"],
                           request.headers.get("User-Agent", ""), owner["id"])
    # The nudge: someone who just typed a password and owns no passkey is one
    # Touch ID prompt away from never typing it again. Send them to Account
    # once; every later sign-in goes where they were headed.
    dest = "/account?welcome=1" if passkey_count(owner["id"]) == 0 else nxt
    return set_cookie(make_response(redirect(dest)), token)


# -------------------------------------------------------------- signup page
#
# The same scene as /login — same photograph, same card, same type — because
# it is the same front door: _SCENE_CSS is shared verbatim, and only the
# handful of rules this page adds live below. Self-contained for the same
# reason /login is: /_app sits behind the gate, so an invitee could never load
# the bundle.

_SIGNUP_CSS = """
  /* the invite's terms, read once and never interacted with */
  .terms { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 20px; }
  .term {
    display: inline-flex; align-items: center; gap: 6px; height: 26px; padding: 0 10px;
    border-radius: 9999px; background: var(--mc-glass-soft);
    border: 1px solid var(--mc-glass-line); color: var(--mc-ink2);
    font: 500 12px/1 var(--mc-font); text-transform: capitalize;
  }
  .term.ok { background: rgba(62, 207, 142, 0.12);
             border-color: rgba(62, 207, 142, 0.32); color: var(--mc-accent); }
  .field { margin-bottom: 16px; }
  .hint { margin: 6px 0 0; font: 400 12px/1.5 var(--mc-font); color: var(--mc-ink3); }
  #username { font-family: var(--mc-mono); font-size: 14px; }
  #go { width: 100%; margin-top: 4px; flex-direction: column; gap: 4px;
        height: auto; min-height: 56px; padding: 10px 20px; line-height: 1.25;
        white-space: normal; text-align: center; }
  #go small { font: 400 12px/1.35 var(--mc-font); letter-spacing: 0;
              color: rgba(17, 17, 19, 0.6); }
  #done { display: none; }
"""

_SIGNUP_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="color-scheme" content="dark" />
<title>__TITLE__ · Oblivion</title>
<link rel="icon" href="/favicon.svg" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300..800&family=IBM+Plex+Mono:wght@400;600&display=swap" rel="stylesheet" />
<style>
__CSS____SIGNUP_CSS__</style>
</head>
<body class="mg-scene">
  <div class="backdrop" aria-hidden="true">
    <div class="shot"></div>
    <div class="dim"></div>
    <div class="top"></div>
    <div class="bot"></div>
  </div>

  <main class="card mg-glass-strong">
    <div class="logo"><span class="mark"></span>
      <span class="name">Oblivion</span><span class="sub">Prospect Engine</span></div>
    <h1>__H1__</h1>
    <p class="who">__SUB__</p>

    <div id="err" class="mg-strip crit" style="display:__ERRSHOW__">__ERROR__</div>

    __BODY__
  </main>
<script>
  var STATE = __STATE__;
  var err = document.getElementById('err');
  function fail(msg) { err.textContent = msg; err.style.display = ''; }

  // base64url <-> ArrayBuffer, written out rather than imported: this page
  // must stand alone (see /login, which carries the same forty lines).
  function b64uToBuf(s) {
    s = String(s).replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    var bin = atob(s), buf = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return buf.buffer;
  }
  function bufToB64u(b) {
    var bytes = new Uint8Array(b), s = '';
    for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, '');
  }

  // A rough name for this device, so the passkey list reads like devices.
  function deviceName() {
    var ua = navigator.userAgent;
    var os = /iPhone/.test(ua) ? 'iPhone' : /iPad/.test(ua) ? 'iPad'
      : /Android/.test(ua) ? 'Android' : /Macintosh|Mac OS/.test(ua) ? 'Mac'
      : /Windows/.test(ua) ? 'Windows' : /Linux/.test(ua) ? 'Linux' : 'Device';
    var br = /Edg\\//.test(ua) ? 'Edge' : /Chrome|CriOS/.test(ua) ? 'Chrome'
      : /Firefox|FxiOS/.test(ua) ? 'Firefox' : /Safari/.test(ua) ? 'Safari' : 'Browser';
    return os + ' / ' + br;
  }

  var go = document.getElementById('go');
  if (go && !window.PublicKeyCredential) {
    go.disabled = true;
    fail('This browser cannot create a passkey. Open the link on a phone or '
       + 'a laptop with Touch ID, a fingerprint reader or Windows Hello.');
  }

  // The username field follows the display name until it is typed in, so the
  // common case is one field, not two.
  var nameEl = document.getElementById('display_name');
  var userEl = document.getElementById('username');
  var typed = false;
  if (userEl) userEl.addEventListener('input', function () { typed = true; });
  if (nameEl && userEl) {
    nameEl.addEventListener('input', function () {
      if (typed) return;
      userEl.value = nameEl.value.toLowerCase().replace(/[^a-z0-9._-]+/g, '.')
        .replace(/^[._-]+|[._-]+$/g, '').slice(0, 32);
    });
  }

  if (go) go.addEventListener('click', async function () {
    go.disabled = true;
    err.style.display = 'none';
    try {
      var payload = { token: STATE.token };
      if (STATE.mode === 'new') {
        payload.display_name = (nameEl.value || '').trim();
        payload.username = (userEl.value || '').trim();
        if (!payload.username) throw new Error('Pick a username first.');
      }
      var r = await fetch('/api/signup', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload) });
      var got = await r.json();
      if (!r.ok) throw new Error(got.message || got.error || 'rejected');

      var o = got.options;
      o.challenge = b64uToBuf(o.challenge);
      o.user.id = b64uToBuf(o.user.id);
      (o.excludeCredentials || []).forEach(function (c) { c.id = b64uToBuf(c.id); });
      var cred = await navigator.credentials.create({ publicKey: o });
      if (!cred) throw new Error('cancelled');
      var res = cred.response;
      var out = {
        id: cred.id, rawId: bufToB64u(cred.rawId), type: cred.type,
        authenticatorAttachment: cred.authenticatorAttachment || undefined,
        clientExtensionResults: cred.getClientExtensionResults(),
        response: {
          clientDataJSON: bufToB64u(res.clientDataJSON),
          attestationObject: bufToB64u(res.attestationObject),
          transports: res.getTransports ? res.getTransports() : []
        }
      };
      var v = await fetch('/api/signup/verify', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: got.token, credential: out, name: deviceName() }) });
      var fin = await v.json();
      if (!v.ok || !fin.ok) throw new Error(fin.message || fin.error || 'rejected');
      location.href = fin.next || '/';
    } catch (e) {
      go.disabled = false;
      var m = String(e && e.message || e);
      if (e && e.name === 'InvalidStateError') {
        fail('This device already holds a passkey for that account. Just sign in.');
      } else if (e && (e.name === 'NotAllowedError' || m === 'cancelled')) {
        fail('The passkey prompt was dismissed. Tap the button to try again.');
      } else { fail(m); }
    }
  });
</script>
</body>
</html>
"""


def _signup_body(mode: str, username: str, terms: str) -> str:
    """The card's middle: the fields (or none) and the one button."""
    if mode == "reregister":
        return (terms + """
    <button class="mg-btn primary lg" id="go" type="button">
      Add this device
      <small>Touch ID, Windows Hello, or a security key</small>
    </button>
    <p class="foot">Signing in as __USERNAME__. The old devices stay removed
      until you delete them from Account.</p>""")
    return (terms + """
    <div class="field">
      <label class="mg-label" for="display_name">Your name</label>
      <input id="display_name" class="mg-input" type="text" autocomplete="name"
             placeholder="Sam Cele" autofocus maxlength="60" />
    </div>
    <div class="field">
      <label class="mg-label" for="username">Username</label>
      <input id="username" class="mg-input" type="text" autocomplete="username"
             placeholder="sam" maxlength="32" spellcheck="false" />
      <p class="hint">Lower case letters, numbers, dots, dashes.</p>
    </div>

    <button class="mg-btn primary lg" id="go" type="button">
      Create account with passkey
      <small>Touch ID, Windows Hello, or a security key</small>
    </button>
    <p class="foot">There is no password: this dashboard signs you in with the
      device in your hand.</p>""")


def _render_signup(*, mode: str, token: str, username: str = "",
                   role: str = "member", privileges=(), note: str = "",
                   error: str = "") -> Response:
    import html as _html

    hour = datetime.now().hour
    hero = ("night" if hour >= 20 or hour < 5 else "morning" if hour < 10
            else "day" if hour < 17 else "dusk")

    if error:
        h1, sub, body = "That link did not work", "", """
    <p class="foot">Ask whoever invited you for a fresh link — a sign-up link
      is good for one account and expires.</p>
    <p class="foot"><a href="/login">Back to sign in</a></p>"""
        state = {"mode": "dead", "token": ""}
    else:
        chips = "".join(
            f'<span class="term">{_html.escape(p)}</span>' for p in privileges)
        terms = (f'<div class="terms"><span class="term ok">'
                 f'{_html.escape(role)}</span>{chips}</div>'
                 if (role or chips) else "")
        if note:
            terms += f'<p class="who">“{_html.escape(note)}”</p>'
        if mode == "reregister":
            h1 = "Add a device"
            sub = (f"A new passkey for {_html.escape(username)}. "
                   "The account and everything on it stays as it was.")
        else:
            h1 = "Create your account"
            sub = "One passkey and you are in — no password to remember."
        body = _signup_body(mode, username, terms)
        state = {"mode": mode, "token": token}

    page = (_SIGNUP_HTML
            .replace("__CSS__", _SCENE_CSS)
            .replace("__SIGNUP_CSS__", _SIGNUP_CSS)
            .replace("__HERO__", hero)
            .replace("__TITLE__", "Sign up")
            .replace("__H1__", h1)
            .replace("__SUB__", sub)
            .replace("__BODY__", body)
            .replace("__USERNAME__", _html.escape(username))
            .replace("__STATE__", json.dumps(state))
            .replace("__ERRSHOW__", "" if error else "none")
            .replace("__ERROR__", _html.escape(error)))
    return Response(page, 200 if not error else 200,
                    {"Content-Type": "text/html; charset=utf-8",
                     "Cache-Control": "no-store"})


@bp.get("/signup")
def signup_page():
    """The invitee's front door. Public, and useless without a live token."""
    raw = (request.args.get("token") or "").strip()
    if not raw:
        return _render_signup(mode="dead", token="",
                              error="This page needs a sign-up link.")
    with _db() as conn:
        invite, state = _invite_for(conn, raw)
        if state != "ok":
            return _render_signup(mode="dead", token="",
                                  error=_INVITE_COPY[state])
        username = ""
        if invite["user_id"]:
            target = _by_id(conn, invite["user_id"])
            if not target or target["disabled"]:
                return _render_signup(mode="dead", token="",
                                      error=_INVITE_COPY["unknown"])
            username = target["username"]
        privileges = clean_privileges(_json_list(invite["privileges"]))
        if invite["role"] in ("owner", "admin"):
            privileges = [p for p in PRIVILEGES]
        note = "" if invite["user_id"] else (invite["note"] or "")
    return _render_signup(
        mode="reregister" if username else "new", token=raw,
        username=username, role=invite["role"], privileges=privileges,
        note=note)
