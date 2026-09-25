"""Team chat: channels, attachments, @mentions. The contract is docs/CHAT.md.

The floating chat on every page is the team talking to each other (Agent Z is
/api/agent, a different thing). Polling, not sockets: the Procfile runs one
gunicorn worker with a handful of threads and a held-open socket per browser
would eat a thread each. The one polled call is ``GET /api/chat/sync``; it is
built to be cheap — an indexed ``rev`` range, one grouped unread count and one
mention count — and never joins the listings tables: attachments are
validated and enriched once, at post time, and stored as a JSON snapshot.

``rev`` is a global, strictly increasing change counter. Every insert, edit
and delete assigns ``MAX(rev)+1`` inside the same write statement, under
``BEGIN IMMEDIATE``, so revs are assigned and committed in the same order and
a client holding cursor N can never miss a later change with a rev <= N.

Security posture: the body is plain text and is stored and returned as text —
nothing in here ever produces HTML. SQL is parameterised throughout; the only
string-built SQL is a run of ``?`` placeholders.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from flask import Blueprint, jsonify, request

import auth
import config
import db
import team

bp = Blueprint("chat", __name__)

BODY_MAX = 2000
MAX_ATTACHMENTS = 6
URL_MAX = 2048
TITLE_MAX = 200
CAPTION_MAX = 200
CHANNEL_NAME_MAX = 40
CLIENT_ID_MAX = 64
MAX_MENTION_IDS = 20
#: SQLite INTEGER is signed 64-bit: every id we accept must fit, or binding it
#: raises OverflowError (a 500) instead of a clean 404/400.
INT_MAX = 2 ** 63 - 1
#: property_info asks in chunks of this many gids (SQLite's variable limit).
PROPERTY_CHUNK = 500
PAGE_DEFAULT = 50
PAGE_MAX = 200
SYNC_MAX = 200
MENTIONS_DEFAULT = 30
MENTIONS_MAX = 100
COMPAT_TAIL = 100
EDIT_WINDOW = timedelta(minutes=15)
PREVIEW_LEN = 120

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_channels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('general', 'topic', 'property')),
    property_gid INTEGER,
    created_by   INTEGER,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    archived_at  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_channels_gid
    ON chat_channels(property_gid) WHERE kind = 'property';

CREATE TABLE IF NOT EXISTS chat_messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id    INTEGER NOT NULL,
    user_id       INTEGER,              -- NULL on rows migrated from team_chat
    legacy_sender TEXT,                 -- team_chat.sender on those rows
    body          TEXT NOT NULL DEFAULT '',
    attachments   TEXT NOT NULL DEFAULT '[]',   -- enriched snapshots (JSON)
    mentions      TEXT NOT NULL DEFAULT '[]',   -- user ids (JSON)
    client_id     TEXT,
    rev           INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    edited_at     TEXT,
    deleted_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_channel ON chat_messages(channel_id, id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_rev ON chat_messages(rev);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_client
    ON chat_messages(user_id, client_id) WHERE client_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS chat_mentions (
    message_id INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, message_id)
);
-- Unread-mention counts are a range per (user, channel): message_id > last read.
CREATE INDEX IF NOT EXISTS idx_chat_mentions_user_chan
    ON chat_mentions(user_id, channel_id, message_id);
-- Delete clears a message's mention rows by message_id.
CREATE INDEX IF NOT EXISTS idx_chat_mentions_message ON chat_mentions(message_id);

-- channel_id 0 is the user's baseline (see docs/CHAT.md).
CREATE TABLE IF NOT EXISTS chat_reads (
    user_id      INTEGER NOT NULL,
    channel_id   INTEGER NOT NULL,
    last_read_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, channel_id)
);
"""

#: app_state key bumped on every channel create / rename / archive, so the
#: client can tell from one sync that its channel list is stale.
_STAMP_KEY = "chat_channels_stamp"
#: app_state key: the highest team_chat id already copied into #general.
_LEGACY_KEY = "chat.legacy_migrated_upto"

_schema_lock = threading.Lock()
_schema_done = False


def ensure_schema(conn) -> None:
    """Create the tables, seed #general, copy team_chat in. Idempotent.

    Runs once per process (the boot block in webapp.py); every step is safe to
    repeat, and it commits before returning so no lock outlives it.
    """
    global _schema_done
    if _schema_done:
        return
    with _schema_lock:
        if _schema_done:
            return
        conn.executescript(_SCHEMA)
        _ensure_name_index(conn)
        now = _stamp()
        conn.execute(
            "INSERT OR IGNORE INTO chat_channels (slug, name, kind, created_at,"
            " updated_at) VALUES ('general', 'general', 'general', ?, ?)", (now, now))
        conn.commit()
        _migrate_legacy(conn)
        _schema_done = True


def _ensure_name_index(conn) -> None:
    """UNIQUE lower(name) among #general + topics (property channels may share
    an address). Skipped, not fatal, if existing rows already clash — the
    application-level check still holds for new names."""
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_channels_name"
            " ON chat_channels(lower(name)) WHERE kind != 'property'")
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()


def _migrate_legacy(conn) -> None:
    """Copy team_chat into #general, once, then only what is new.

    The first copy keeps team_chat's ids and sets rev = id (so a cached old
    client's ``?after=<id>`` still lines up). It is recorded by a marker in
    app_state — the highest team_chat id copied. A later boot copies only
    team_chat rows past the marker (written by an old container still serving
    an old client during a deploy overlap) with FRESH ids and revs above every
    existing rev, so a syncing client sees them, then advances the marker.
    All under BEGIN IMMEDIATE, so two booting processes cannot both copy.
    """
    has_legacy = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='team_chat'").fetchone()
    if not has_legacy:
        return
    _begin_write(conn)
    try:
        gen = conn.execute("SELECT id FROM chat_channels WHERE slug='general'").fetchone()[0]
        top = conn.execute("SELECT COALESCE(MAX(id), 0) FROM team_chat").fetchone()[0]
        marker = db.get_state(conn, _LEGACY_KEY)
        upto = int(marker) if marker is not None and marker.isdigit() else None
        if upto is None:
            empty = conn.execute("SELECT 1 FROM chat_messages LIMIT 1").fetchone() is None
            if empty:
                conn.execute(
                    "INSERT INTO chat_messages (id, channel_id, user_id, legacy_sender,"
                    " body, attachments, mentions, client_id, rev, created_at)"
                    " SELECT id, ?, NULL, sender, body, '[]', '[]', NULL, id, created_at"
                    " FROM team_chat WHERE id <= ? ORDER BY id", (gen, top))
                pending = []
            else:
                # chat_messages already has rows (a build from before the
                # marker existed copied some). Copy only the team_chat rows
                # not already there as the same legacy row, with fresh ids.
                pending = conn.execute(
                    "SELECT t.* FROM team_chat t WHERE t.id <= ? AND NOT EXISTS ("
                    " SELECT 1 FROM chat_messages m WHERE m.id = t.id"
                    " AND m.user_id IS NULL AND m.legacy_sender IS t.sender"
                    " AND m.created_at IS t.created_at) ORDER BY t.id", (top,)).fetchall()
        else:
            pending = conn.execute(
                "SELECT * FROM team_chat WHERE id > ? AND id <= ? ORDER BY id",
                (upto, top)).fetchall()
        for r in pending:
            conn.execute(
                "INSERT INTO chat_messages (channel_id, user_id, legacy_sender, body,"
                " attachments, mentions, client_id, rev, created_at) VALUES"
                " (?, NULL, ?, ?, '[]', '[]', NULL,"
                " (SELECT COALESCE(MAX(rev), 0) + 1 FROM chat_messages), ?)",
                (gen, r["sender"], r["body"], r["created_at"]))
        new_marker = max(top, upto or 0)
        if new_marker != upto:
            conn.execute(
                "INSERT OR REPLACE INTO app_state (key, value, updated_at)"
                " VALUES (?, ?, datetime('now'))", (_LEGACY_KEY, str(new_marker)))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _now() -> datetime:
    """The clock. A function so tests can move time (the edit window)."""
    return datetime.now(timezone.utc)


def _stamp(dt: datetime | None = None) -> str:
    return (dt or _now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(ts):
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class _Conn:
    """db.connect() with the chat tables guaranteed to exist."""

    def __init__(self):
        self._cm = db.connect()

    def __enter__(self):
        conn = self._cm.__enter__()
        if not _schema_done:
            ensure_schema(conn)
        return conn

    def __exit__(self, *exc):
        return self._cm.__exit__(*exc)


def _begin_write(conn) -> None:
    """Take the write lock now, so MAX(rev) is read under it."""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")


# ----------------------------------------------------------------- errors

class Bad(Exception):
    def __init__(self, message: str, code: str = "bad_request", status: int = 400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def _err(code: str, message: str, status: int = 400):
    return jsonify({"error": code, "message": message}), status


def _unauth():
    return jsonify({"error": "auth_required"}), 401


def _int(raw, name: str, *, minimum: int = 0, maximum: int = INT_MAX) -> int:
    """A strict int: True/False/floats/'1.5' are refused."""
    if isinstance(raw, bool):
        raise Bad(f"{name} must be an integer")
    if isinstance(raw, int):
        val = raw
    elif isinstance(raw, str) and re.fullmatch(r"\s*-?\d{1,19}\s*", raw):
        val = int(raw)
    else:
        raise Bad(f"{name} must be an integer")
    if val < minimum or val > maximum:
        raise Bad(f"{name} is out of range")
    return val


def _arg_int(name: str, default=None, *, minimum: int = 0, maximum: int = INT_MAX):
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    return _int(raw, name, minimum=minimum, maximum=maximum)


# ------------------------------------------------------------ sanitising

# C0 controls and DEL, minus tab and newline: a message may be several lines,
# but nothing in it should be able to move a cursor or ring a terminal bell.
_CTRL = {c: None for c in list(range(32)) + [127] if c not in (9, 10)}

# Invisible characters that can disguise text: bidi embeddings/overrides/
# isolates and marks (a "Trojan Source" style reorder of what is shown),
# zero-width spaces/joiners, the BOM, and the C1 control block.
_BIDI = [*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200E, 0x200F, 0x061C]
_ZERO_WIDTH = [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF]
_C1 = list(range(0x80, 0xA0))
_ZWJ = 0x200D     # kept in bodies: emoji sequences (family, flags) need it

#: For message bodies: U+2028/2029 become newlines, ZWJ survives.
_BODY_TABLE = {**_CTRL, **{c: None for c in _BIDI + _ZERO_WIDTH + _C1 if c != _ZWJ},
               0x2028: "\n", 0x2029: "\n"}
#: For one-line fields (names, titles, captions): everything invisible goes,
#: ZWJ included, and line/paragraph separators become spaces.
_LINE_TABLE = {**_CTRL, **{c: None for c in _BIDI + _ZERO_WIDTH + _C1},
               0x2028: " ", 0x2029: " "}


def clean_body(value) -> str:
    """The old _chat_body, without the silent truncation (over-long is a 400),
    plus the invisible-character strip above."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.translate(_BODY_TABLE).strip()
    # A body of nothing but joiners and space is an empty body.
    return text if text.replace(chr(_ZWJ), "").strip() else ""


def _one_line(value, limit: int) -> str:
    text = str(value or "").translate(_LINE_TABLE)
    return " ".join(text.split())[:limit]


def _one_line_strict(value, limit: int, name: str) -> str:
    if value is not None and not isinstance(value, str):
        raise Bad(f"{name} must be text")
    text = " ".join(str(value or "").translate(_LINE_TABLE).split())
    if len(text) > limit:
        raise Bad(f"{name} is longer than {limit} characters")
    return text


# ----------------------------------------------------------------- people

def _users(conn) -> dict:
    """id → user row, every account (disabled ones too: old messages)."""
    return {r["id"]: r for r in conn.execute(
        "SELECT id, username, display_name, role, privileges, disabled FROM users")}


def _display(u) -> str:
    return u["display_name"] or u["username"]


def _user_obj(u) -> dict:
    name = _display(u)
    return {"id": u["id"], "username": u["username"], "display_name": name,
            "initials": team._initials(name)}


def is_admin_account(u) -> bool:
    """THE chat admin rule, the same one team._actor applies to the caller:
    the account holds the ``admin`` privilege (owner/admin roles always do).
    Used for stored authors (edit re-scans) so both paths agree."""
    return u is not None and "admin" in auth.effective_privileges(u)


# --------------------------------------------------------------- mentions

_WORD = re.compile(r"\w")


def parse_mentions(body: str, users: dict, sender_id: int, sender_admin: bool) -> set:
    """User ids named in the body as @username / @Display Name / @everyone.

    Case-insensitive, longest name first, and a match must end at a non-word
    character (or the end) so @sam does not fire inside @samantha. An '@'
    glued to a word (an email address) is not a mention. @everyone / @here
    only count from an owner or admin. The sender is never included.
    """
    active = [u for u in users.values() if not u["disabled"]]
    names: list[tuple[str, object]] = []
    for u in active:
        for n in {u["username"], _display(u)}:
            if n:
                names.append((n.lower(), u["id"]))
    if sender_admin:
        names += [("everyone", "*"), ("here", "*")]
    names.sort(key=lambda t: -len(t[0]))
    low = body.lower()
    out: set = set()
    i = low.find("@")
    while i != -1:
        if i > 0 and _WORD.match(low[i - 1]):
            i = low.find("@", i + 1)
            continue
        rest = low[i + 1:]
        hit = None
        for name, uid in names:
            if rest.startswith(name):
                end = len(name)
                if end == len(rest) or not _WORD.match(rest[end]):
                    hit = (name, uid)
                    break
        if hit:
            if hit[1] == "*":
                out.update(u["id"] for u in active)
            else:
                out.add(hit[1])
            i = low.find("@", i + 1 + len(hit[0]))
        else:
            i = low.find("@", i + 1)
    out.discard(sender_id)
    return out


def _named_in(low_body: str, u) -> bool:
    """Does the (lower-cased) body carry @username or @Display Name for u, as a
    whole token (not glued to a word before, ends at a non-word char)?"""
    for n in {u["username"], _display(u)}:
        if not n:
            continue
        tok = "@" + n.lower()
        i = low_body.find(tok)
        while i != -1:
            end = i + len(tok)
            if (i == 0 or not _WORD.match(low_body[i - 1])) and \
                    (end == len(low_body) or not _WORD.match(low_body[end])):
                return True
            i = low_body.find(tok, i + 1)
    return False


def _explicit_mentions(raw, users: dict, body: str = "", sender_admin: bool = True) -> set:
    """The client's explicit mention ids (from the @ picker), validated.

    An admin's list is taken as sent. Anyone else's is kept only for users
    whose @username / @Display Name token is actually in the body — the
    picker always inserts one — so a member cannot ping people silently.
    """
    if raw in (None, ""):
        return set()
    if not isinstance(raw, list):
        raise Bad("mentions must be a list of user ids", "bad_mention")
    if len(raw) > MAX_MENTION_IDS:
        raise Bad(f"at most {MAX_MENTION_IDS} mentions", "bad_mention")
    out = set()
    for item in raw:
        try:
            uid = _int(item, "mention")
        except Bad:
            raise Bad(f"mention {str(item)[:20]!r} is not a user id", "bad_mention")
        u = users.get(uid)
        if u is None or u["disabled"]:
            raise Bad(f"mention: user {uid} is not an active user", "bad_mention")
        out.add(uid)
    if not sender_admin:
        low = body.lower()
        out = {uid for uid in out if _named_in(low, users[uid])}
    return out


# ------------------------------------------------------------ attachments

_TIER_RANK = {"hot": 0, "warm": 1, "cold": 2}


def property_info(conn, gids) -> dict:
    """group id → {label, suburb, price_zar, tier, photo_url}, for the gids
    that exist in property_groups. One query per 500 gids; label/suburb/price from the
    best-addressed, most recently seen listing, the first real photo ('-' is
    the "page has none" placeholder), and the best tier across the group."""
    gids = sorted({int(g) for g in gids})
    out: dict = {}
    for i in range(0, len(gids), PROPERTY_CHUNK):
        _property_chunk(conn, gids[i:i + PROPERTY_CHUNK], out)
    return out


def _property_chunk(conn, gids: list, out: dict) -> None:
    if not gids:
        return
    q = ",".join("?" * len(gids))
    try:
        rows = conn.execute(
            f"""SELECT g.group_id AS gid, l.street_address_raw, l.title, l.suburb,
                       l.price_zar, l.photo_url, s.tier
                  FROM property_groups g
                  LEFT JOIN listings l ON l.listing_key = g.listing_key
                  LEFT JOIN scores s ON s.listing_key = g.listing_key
                 WHERE g.group_id IN ({q})
                 ORDER BY l.street_address_raw IS NULL, l.last_seen DESC""",
            gids).fetchall()
    except sqlite3.Error:
        return
    for r in rows:
        gid = int(r["gid"])
        cur = out.get(gid)
        if cur is None:
            cur = out[gid] = {
                "label": r["street_address_raw"] or r["title"] or f"Property {gid}",
                "suburb": r["suburb"], "price_zar": r["price_zar"],
                "tier": None, "photo_url": None}
        photo = (r["photo_url"] or "").strip()
        if not cur["photo_url"] and photo and photo != "-":
            cur["photo_url"] = photo
        tier = r["tier"]
        if tier in _TIER_RANK and (cur["tier"] is None
                                   or _TIER_RANK[tier] < _TIER_RANK[cur["tier"]]):
            cur["tier"] = tier


def _zerko_db_path() -> str:
    url = os.environ.get("DATABASE_URL") or ""
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    return os.path.join(config.DATA_DIR, "media-data", "zerko.db")


def media_lookup(ids) -> dict | None:
    """Zerko library id → {name, kind, thumb, caption} for the ids that exist
    (and are not in the trash), or None when the library is unavailable.

    Read-only and fail-soft: opens Zerko's own SQLite catalogue with
    ``mode=ro`` and never imports the Zerko backend. Tests monkeypatch this.
    """
    ids = sorted({int(i) for i in ids})[:MAX_ATTACHMENTS * 4]
    path = _zerko_db_path()
    if not path or not os.path.isfile(path):
        return None
    try:
        conn = sqlite3.connect(f"file:{quote(os.path.abspath(path))}?mode=ro",
                               uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        conn.row_factory = sqlite3.Row
        cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)")}
        if not cols:
            return None
        if not ids:
            return {}
        q = ",".join("?" * len(ids))
        active = " AND (is_active IS NULL OR is_active = 1)" if "is_active" in cols else ""
        rows = conn.execute(
            f"SELECT id, filename, media_type, thumbnail_path FROM videos"
            f" WHERE id IN ({q}){active}", ids).fetchall()
        return {r["id"]: {"name": r["filename"] or f"Item {r['id']}",
                          "kind": r["media_type"] or "video",
                          "thumb": r["thumbnail_path"], "caption": None}
                for r in rows}
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _clean_url(raw) -> tuple[str, str]:
    """(url, domain) for a link attachment, or Bad.

    Strict on purpose, because the card shows ``domain`` as "where this goes":
    no backslash (browsers read ``\\`` as ``/``, so ``http://evil.com\\@good.com``
    would be stored as good.com but open evil.com), no whitespace, controls or
    non-ASCII (the user pastes the percent/punycode-encoded form), no
    user:password@ part, http/https with a real hostname.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise Bad("link: url is required", "bad_attachment")
    url = raw.strip()
    shown = url[:80]
    if len(url) > URL_MAX:
        raise Bad(f"link: url is longer than {URL_MAX} characters", "bad_attachment")
    if any(ord(c) > 126 for c in url):
        raise Bad(f"link: url {shown!r} contains non-ASCII characters; paste the"
                  " encoded form (as the browser's address bar copies it)",
                  "bad_attachment")
    if any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise Bad(f"link: url {shown!r} contains spaces or control characters",
                  "bad_attachment")
    if "\\" in url:
        raise Bad(f"link: url {shown!r} contains a backslash", "bad_attachment")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port                      # noqa: B018 - raises on a bad port
    except ValueError:
        raise Bad(f"link: url {shown!r} does not parse", "bad_attachment")
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc or not host:
        raise Bad(f"link: url {shown!r} must be an http or https address",
                  "bad_attachment")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise Bad(f"link: url {shown!r} must not contain a user name or password",
                  "bad_attachment")
    domain = host.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if not domain:
        raise Bad(f"link: url {shown!r} has no host name", "bad_attachment")
    return url, domain


def validate_attachments(conn, raw, can_media: bool = True) -> list:
    """The posted attachments, checked and enriched into stored snapshots.

    ``can_media`` is the sender's ``media`` privilege: without it any media
    attachment is a 403 before the library is looked at, so the answer says
    nothing about which ids exist."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise Bad("attachments must be a list", "bad_attachment")
    if len(raw) > MAX_ATTACHMENTS:
        raise Bad(f"at most {MAX_ATTACHMENTS} attachments", "bad_attachment")
    items = []
    for a in raw:
        if not isinstance(a, dict):
            raise Bad("each attachment must be an object", "bad_attachment")
        items.append(a)
    gids, media_ids = [], []
    for a in items:
        t = a.get("type")
        if t == "property":
            try:
                gids.append(_int(a.get("gid"), "gid"))
            except Bad:
                raise Bad(f"property gid {str(a.get('gid'))[:20]!r} is not a valid id",
                          "bad_attachment")
        elif t == "media":
            if not can_media:
                raise Bad("Sharing media needs the media privilege.",
                          "media_forbidden", 403)
            try:
                media_ids.append(_int(a.get("id"), "media id"))
            except Bad:
                raise Bad(f"media id {str(a.get('id'))[:20]!r} is not a valid id",
                          "bad_attachment")
        elif t != "link":
            raise Bad(f"unknown attachment type {str(t)[:20]!r}", "bad_attachment")
    props = property_info(conn, gids) if gids else {}
    for g in gids:
        if g not in props:
            raise Bad(f"property gid {g} does not exist", "bad_attachment")
    lib: dict = {}
    if media_ids:
        got = media_lookup(media_ids)
        if got is None:
            raise Bad("media library unavailable", "media_unavailable")
        lib = {int(k): v for k, v in got.items()}
        for m in media_ids:
            if m not in lib:
                raise Bad(f"media id {m} not found in the library", "bad_attachment")
    out = []
    for a in items:
        t = a["type"]
        if t == "property":
            g = _int(a.get("gid"), "gid")
            out.append({"type": "property", "gid": g, **props[g]})
        elif t == "media":
            m = _int(a.get("id"), "media id")
            info = lib[m]
            cap = _one_line_strict(a.get("caption"), CAPTION_MAX, "media caption")
            out.append({"type": "media", "id": m,
                        "name": _one_line(info.get("name"), 200) or f"Item {m}",
                        "kind": str(info.get("kind") or "video")[:20],
                        "thumb": info.get("thumb"),
                        "caption": cap or info.get("caption") or None})
        else:
            url, domain = _clean_url(a.get("url"))
            title = _one_line_strict(a.get("title"), TITLE_MAX, "link title")
            out.append({"type": "link", "url": url, "title": title or None,
                        "domain": domain})
    return out


# -------------------------------------------------------------- messages

def _loads(raw) -> list:
    try:
        v = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else []


def message_obj(r, users: dict, me_id: int) -> dict:
    uid = r["user_id"]
    u = users.get(uid) if uid is not None else None
    if uid is None:
        user, sender = None, r["legacy_sender"] or "Someone"
    elif u is None:
        user, sender = None, "Former member"
    else:
        user, sender = _user_obj(u), _display(u)
    deleted = r["deleted_at"] is not None
    mentions = [] if deleted else _loads(r["mentions"])
    return {
        "id": r["id"], "rev": r["rev"], "channel_id": r["channel_id"],
        "user": user, "sender": sender,
        "body": "" if deleted else r["body"],
        "attachments": [] if deleted else _loads(r["attachments"]),
        "mentions": mentions, "mentions_me": me_id in mentions,
        "created_at": r["created_at"], "edited_at": r["edited_at"],
        "deleted": deleted, "mine": uid is not None and uid == me_id,
        "client_id": r["client_id"],
    }


def _message(conn, mid: int):
    return conn.execute("SELECT * FROM chat_messages WHERE id=?", (mid,)).fetchone()


def _channel(conn, cid: int):
    return conn.execute("SELECT * FROM chat_channels WHERE id=?", (cid,)).fetchone()


def _cursor(conn) -> int:
    return conn.execute("SELECT COALESCE(MAX(rev), 0) FROM chat_messages").fetchone()[0]


def _clean_client_id(raw):
    if raw in (None, ""):
        return None
    if not isinstance(raw, str) or not re.fullmatch(r"[A-Za-z0-9_.:\-]{1,%d}" % CLIENT_ID_MAX, raw):
        raise Bad("client_id must be 1-64 letters, digits or _.:-")
    return raw


def _prior(conn, acct, client_id, channel):
    """The message this (user, client_id) already made, or None. A retry must
    be for the same channel: reusing the id elsewhere is a client bug, 409."""
    if not client_id:
        return None
    prior = conn.execute(
        "SELECT * FROM chat_messages WHERE user_id=? AND client_id=?",
        (acct["id"], client_id)).fetchone()
    if prior is not None and prior["channel_id"] != channel["id"]:
        raise Bad("That client_id was already used in another channel.",
                  "client_id_reused", 409)
    return prior


def post_message(conn, acct, is_admin, channel, payload: dict):
    """Validate and insert. Returns (row, created: bool). Raises Bad."""
    # A retry of a send that already landed answers with the original first —
    # even if the channel was archived in between.
    client_id = _clean_client_id(payload.get("client_id"))
    prior = _prior(conn, acct, client_id, channel)
    if prior is not None:
        return prior, False
    if channel["archived_at"]:
        raise Bad("This channel is archived.", "archived", 409)
    raw_body = payload.get("body")
    if raw_body is not None and not isinstance(raw_body, str):
        raise Bad("body must be text")
    body = clean_body(raw_body)
    if len(body) > BODY_MAX:
        raise Bad(f"The message is longer than {BODY_MAX} characters.", "body_too_long")
    users = _users(conn)
    attachments = validate_attachments(conn, payload.get("attachments"),
                                       can_media="media" in (acct.get("privileges") or []))
    if not body and not attachments:
        raise Bad("Nothing to send.", "empty_message")
    mentions = _explicit_mentions(payload.get("mentions"), users, body, is_admin)
    mentions |= parse_mentions(body, users, acct["id"], is_admin)
    mentions.discard(acct["id"])
    ment = sorted(mentions)
    _begin_write(conn)
    try:
        cur = conn.execute(
            "INSERT INTO chat_messages (channel_id, user_id, body, attachments,"
            " mentions, client_id, rev, created_at) VALUES (?,?,?,?,?,?,"
            " (SELECT COALESCE(MAX(rev), 0) + 1 FROM chat_messages), ?)",
            (channel["id"], acct["id"], body, json.dumps(attachments),
             json.dumps(ment), client_id, _stamp()))
        mid = cur.lastrowid
        conn.executemany(
            "INSERT OR IGNORE INTO chat_mentions (message_id, user_id, channel_id)"
            " VALUES (?,?,?)", [(mid, u, channel["id"]) for u in ment])
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        prior = _prior(conn, acct, client_id, channel)
        if prior:
            return prior, False
        raise
    except BaseException:
        conn.rollback()
        raise
    return _message(conn, mid), True


# ------------------------------------------------------------- read state

def _reads(conn, uid: int) -> tuple[int | None, dict]:
    """(baseline or None, {channel_id: last_read_id})."""
    rows = {r[0]: r[1] for r in conn.execute(
        "SELECT channel_id, last_read_id FROM chat_reads WHERE user_id=?", (uid,))}
    return rows.pop(0, None), rows


def _ensure_baseline(conn, uid: int) -> int:
    """The user's baseline, written the first time they open the chat."""
    base, _ = _reads(conn, uid)
    if base is not None:
        return base
    conn.execute(
        "INSERT OR IGNORE INTO chat_reads (user_id, channel_id, last_read_id)"
        " VALUES (?, 0, (SELECT COALESCE(MAX(id), 0) FROM chat_messages))", (uid,))
    conn.commit()
    return _reads(conn, uid)[0] or 0


def _unread_counts(conn, uid: int, baseline: int, include_archived=False) -> dict:
    """channel id → unread count (others' live messages past the cursor).
    One query: the channel list is small, and each count is an index range."""
    arch = "" if include_archived else "WHERE c.archived_at IS NULL"
    return {r[0]: r[1] for r in conn.execute(
        f"""SELECT c.id,
                   (SELECT COUNT(*) FROM chat_messages m
                     WHERE m.channel_id = c.id
                       AND m.id > COALESCE(r.last_read_id, :base)
                       AND m.deleted_at IS NULL
                       AND (m.user_id IS NULL OR m.user_id <> :me))
              FROM chat_channels c
              LEFT JOIN chat_reads r ON r.user_id = :me AND r.channel_id = c.id
              {arch}""", {"me": uid, "base": baseline})}


def _mention_counts(conn, uid: int, baseline: int) -> dict:
    """channel id → unread mentions of uid, live channels only.

    Driven from the (small) live channel list: per channel one range on
    idx_chat_mentions_user_chan, (user, channel, message_id > last read) —
    bounded by what is unread, not by every mention the user ever had. No join
    to chat_messages is needed: a delete removes its chat_mentions rows."""
    return {r[0]: r[1] for r in conn.execute(
        """SELECT c.id,
                  (SELECT COUNT(*) FROM chat_mentions x
                    WHERE x.user_id = :me AND x.channel_id = c.id
                      AND x.message_id > COALESCE(r.last_read_id, :base))
             FROM chat_channels c
             LEFT JOIN chat_reads r ON r.user_id = :me AND r.channel_id = c.id
            WHERE c.archived_at IS NULL""", {"me": uid, "base": baseline}) if r[1]}


def _channels_stamp(conn) -> str:
    return db.get_state(conn, _STAMP_KEY, "0")


def _bump_stamp(conn) -> None:
    conn.execute(
        "INSERT INTO app_state (key, value, updated_at) VALUES (?, '1', datetime('now'))"
        " ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),"
        " updated_at = excluded.updated_at", (_STAMP_KEY,))


# ------------------------------------------------------------- channels

def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:CHANNEL_NAME_MAX]
    s = s or "channel"
    if re.fullmatch(r"p-\d+", s):         # property channels own p-<gid>
        s += "-topic"
    return s


def _preview(r) -> str:
    body = (r["body"] or "").strip()
    if body:
        line = body.split("\n", 1)[0]
        return line[:PREVIEW_LEN] + ("…" if len(line) > PREVIEW_LEN or "\n" in body else "")
    atts = _loads(r["attachments"])
    if atts:
        kind = {"property": "a property", "media": "media", "link": "a link"}
        return "Shared " + kind.get(atts[0].get("type"), "an attachment")
    return ""


def _channel_list(conn, acct, is_admin, include_archived: bool) -> dict:
    uid = acct["id"]
    baseline = _ensure_baseline(conn, uid)
    _, reads = _reads(conn, uid)
    where = "" if include_archived else "WHERE archived_at IS NULL"
    chans = conn.execute(f"SELECT * FROM chat_channels {where}").fetchall()
    unread = _unread_counts(conn, uid, baseline, include_archived)
    ments = _mention_counts(conn, uid, baseline)
    # Newest live message per channel: an index walk from the end of each
    # channel's (channel_id, id) range, not a scan of the whole table.
    lasts = {r["channel_id"]: r for r in conn.execute(
        f"""SELECT m.* FROM chat_messages m WHERE m.id IN (
               SELECT (SELECT MAX(x.id) FROM chat_messages x
                        WHERE x.channel_id = c.id AND x.deleted_at IS NULL)
                 FROM chat_channels c {where})""")}
    users = _users(conn)
    props = property_info(conn, [c["property_gid"] for c in chans
                                 if c["kind"] == "property" and c["property_gid"] is not None])
    out = []
    for c in chans:
        last = lasts.get(c["id"])
        lobj = None
        if last is not None:
            lobj = {"id": last["id"], "sender": message_obj(last, users, uid)["sender"],
                    "preview": _preview(last), "at": last["created_at"]}
        prop = props.get(c["property_gid"]) if c["kind"] == "property" else None
        out.append({
            "id": c["id"], "slug": c["slug"], "name": c["name"], "kind": c["kind"],
            "property_gid": c["property_gid"],
            "property": ({k: prop[k] for k in ("label", "suburb", "photo_url",
                                               "price_zar", "tier")} if prop else None),
            "archived_at": c["archived_at"],
            "last_read_id": reads.get(c["id"], baseline),
            "unread": unread.get(c["id"], 0), "mentions": ments.get(c["id"], 0),
            "last": lobj,
        })

    def order(ch):
        if ch["kind"] == "general":
            return (0, "", 0)
        if ch["kind"] == "topic":
            return (1, ch["name"].lower(), 0)
        act = ch["last"]["id"] if ch["last"] else 0
        return (2, "", -act)
    out.sort(key=order)
    return {"channels": out,
            "me": {"id": uid, "username": acct["username"],
                   "display_name": acct["display_name"], "is_admin": is_admin},
            "cursor": _cursor(conn)}


def _name_key(name: str) -> str:
    return name.casefold()


def _name_taken(conn, name: str, exclude_id: int | None = None) -> bool:
    """A topic may not share a name (case-insensitively, Unicode-aware) with
    #general or another topic, archived ones included. Property channels are
    named after addresses and may repeat."""
    key = _name_key(name)
    return any(_name_key(r["name"]) == key and r["id"] != exclude_id
               for r in conn.execute(
                   "SELECT id, name FROM chat_channels WHERE kind != 'property'"))


def _free_slug(conn, base: str) -> str:
    """base, or base-2, base-3 … — the first slug no channel has. Names that
    slug to the same thing (non-Latin names all slug to 'channel') coexist."""
    taken = {r[0] for r in conn.execute(
        "SELECT slug FROM chat_channels WHERE slug = ? OR slug LIKE ?",
        (base, base.replace("%", "").replace("_", "") + "-%"))}
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _channel_name(raw, limit: int) -> str:
    if not isinstance(raw, str):
        raise Bad("name must be text")
    name = _one_line_strict(raw, limit, "name").lstrip("#").strip()
    if not name:
        raise Bad("name is required")
    return name


def _channel_public(conn, c) -> dict:
    prop = None
    if c["kind"] == "property" and c["property_gid"] is not None:
        prop = property_info(conn, [c["property_gid"]]).get(c["property_gid"])
    return {"id": c["id"], "slug": c["slug"], "name": c["name"], "kind": c["kind"],
            "property_gid": c["property_gid"],
            "property": ({k: prop[k] for k in ("label", "suburb", "photo_url",
                                               "price_zar", "tier")} if prop else None),
            "archived_at": c["archived_at"]}


# ---------------------------------------------------------------- routes

def _guard(fn):
    """Signed-in actor + Bad → JSON error, for every route below."""
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        acct, is_admin = team._actor()
        if not acct:
            return _unauth()
        # <int:...> accepts any digit string; one past SQLite's 64-bit range
        # would be an OverflowError (500) at bind time. No such row: 404.
        if any(isinstance(v, int) and not 0 <= v <= INT_MAX for v in kw.values()):
            return _err("not_found", "not found", 404)
        try:
            return fn(acct, is_admin, *a, **kw)
        except Bad as e:
            return _err(e.code, e.message, e.status)
    return wrapper


@bp.get("/api/chat/channels")
@_guard
def channels_list(acct, is_admin):
    include = is_admin and request.args.get("archived") in ("1", "true")
    with _Conn() as conn:
        return jsonify(_channel_list(conn, acct, is_admin, include))


@bp.post("/api/chat/channels")
@_guard
def channel_create(acct, is_admin):
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        raise Bad("expected a JSON object")
    now = _stamp()
    with _Conn() as conn:
        if payload.get("property_gid") not in (None, ""):
            gid = _int(payload.get("property_gid"), "property_gid")
            existing = conn.execute(
                "SELECT * FROM chat_channels WHERE kind='property' AND property_gid=?",
                (gid,)).fetchone()
            if existing and existing["archived_at"]:
                # "Discuss" on a property whose channel an admin archived
                # reopens it: the property is being talked about again.
                _begin_write(conn)
                conn.execute("UPDATE chat_channels SET archived_at=NULL, updated_at=?"
                             " WHERE id=?", (now, existing["id"]))
                _bump_stamp(conn)
                conn.commit()
                existing = _channel(conn, existing["id"])
            if existing:
                return jsonify({"channel": _channel_public(conn, existing)}), 200
            info = property_info(conn, [gid]).get(gid)
            if not info:
                raise Bad(f"property gid {gid} does not exist")
            name = _one_line(info["label"], 80) or f"Property {gid}"
            _begin_write(conn)
            try:
                cur = conn.execute(
                    "INSERT INTO chat_channels (slug, name, kind, property_gid,"
                    " created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (f"p-{gid}", name, "property", gid, acct["id"], now, now))
                _bump_stamp(conn)
                conn.commit()
            except sqlite3.IntegrityError:          # a concurrent Discuss won
                conn.rollback()
                existing = conn.execute(
                    "SELECT * FROM chat_channels WHERE kind='property' AND property_gid=?",
                    (gid,)).fetchone()
                return jsonify({"channel": _channel_public(conn, existing)}), 200
            return jsonify({"channel": _channel_public(conn, _channel(conn, cur.lastrowid))}), 201
        if not is_admin:
            return auth.forbidden("admin")
        name = _channel_name(payload.get("name"), CHANNEL_NAME_MAX)
        taken = Bad(f"A channel called {name!r} already exists.", "name_taken", 409)
        # Name check and slug pick under the write lock, so two creates cannot
        # both pass; the UNIQUE lower(name) index is the backstop.
        _begin_write(conn)
        try:
            if _name_taken(conn, name):
                raise taken
            cur = conn.execute(
                "INSERT INTO chat_channels (slug, name, kind, created_by, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?)",
                (_free_slug(conn, _slugify(name)), name, "topic", acct["id"], now, now))
            _bump_stamp(conn)
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            raise taken
        except BaseException:
            conn.rollback()
            raise
        return jsonify({"channel": _channel_public(conn, _channel(conn, cur.lastrowid))}), 201


@bp.patch("/api/chat/channels/<int:cid>")
@_guard
def channel_patch(acct, is_admin, cid: int):
    if not is_admin:
        return auth.forbidden("admin")
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        raise Bad("expected a JSON object")
    with _Conn() as conn:
        c = _channel(conn, cid)
        if not c:
            return _err("not_found", f"channel {cid} not found", 404)
        sets, args = [], []
        name = None
        if "name" in payload:
            name = _channel_name(payload.get("name"),
                                 CHANNEL_NAME_MAX if c["kind"] != "property" else 80)
            sets.append("name=?")
            args.append(name)
        if "archived" in payload:
            arch = payload.get("archived")
            if not isinstance(arch, bool):
                raise Bad("archived must be true or false")
            if arch and c["kind"] == "general":
                raise Bad("#general cannot be archived.")
            sets.append("archived_at=?")
            args.append((c["archived_at"] or _stamp()) if arch else None)
        if not sets:
            raise Bad("nothing to update")
        sets.append("updated_at=?")
        args.append(_stamp())
        taken = Bad(f"A channel called {name!r} already exists.", "name_taken", 409)
        _begin_write(conn)
        try:
            if name is not None and c["kind"] != "property" and _name_taken(conn, name, cid):
                raise taken
            conn.execute(f"UPDATE chat_channels SET {', '.join(sets)} WHERE id=?",
                         (*args, cid))
            _bump_stamp(conn)
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            raise taken
        except BaseException:
            conn.rollback()
            raise
        return jsonify({"channel": _channel_public(conn, _channel(conn, cid))})


@bp.get("/api/chat/channels/<int:cid>/messages")
@_guard
def messages_list(acct, is_admin, cid: int):
    before = _arg_int("before")
    after = _arg_int("after")
    limit = _arg_int("limit", PAGE_DEFAULT, minimum=1, maximum=10 ** 6)
    limit = min(limit, PAGE_MAX)
    with _Conn() as conn:
        if not _channel(conn, cid):
            return _err("not_found", f"channel {cid} not found", 404)
        if after is not None and before is None:
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE channel_id=? AND id>?"
                " ORDER BY id ASC LIMIT ?", (cid, after, limit + 1)).fetchall()
            has_more = len(rows) > limit
            rows = rows[:limit]
        else:
            cond, args = "channel_id=?", [cid]
            if before is not None:
                cond += " AND id<?"
                args.append(before)
            if after is not None:
                cond += " AND id>?"
                args.append(after)
            rows = conn.execute(
                f"SELECT * FROM chat_messages WHERE {cond} ORDER BY id DESC LIMIT ?",
                (*args, limit + 1)).fetchall()
            has_more = len(rows) > limit
            rows = rows[:limit][::-1]
        users = _users(conn)
        return jsonify({"messages": [message_obj(r, users, acct["id"]) for r in rows],
                        "has_more": has_more})


@bp.post("/api/chat/channels/<int:cid>/messages")
@_guard
def message_post(acct, is_admin, cid: int):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise Bad("expected a JSON object")
    with _Conn() as conn:
        c = _channel(conn, cid)
        if not c:
            return _err("not_found", f"channel {cid} not found", 404)
        row, created = post_message(conn, acct, is_admin, c, payload)
        return jsonify({"message": message_obj(row, _users(conn), acct["id"])}), \
            (201 if created else 200)


def _editable(conn, acct, is_admin, row, *, editing: bool):
    """None if the caller may change this row now, else the error response.
    Called on the row as read under the write lock."""
    if row is None:
        return _err("not_found", "message not found", 404)
    own = row["user_id"] is not None and row["user_id"] == acct["id"]
    if not own and not is_admin:
        return _err("forbidden", "You can only change your own messages.", 403)
    if row["deleted_at"]:
        return _err("deleted", "That message was deleted.", 409)
    chan = _channel(conn, row["channel_id"])
    if chan is not None and chan["archived_at"]:
        return _err("archived", "This channel is archived.", 409)
    if editing and own and not is_admin:
        made = _parse_ts(row["created_at"])
        if made is None or _now() - made > EDIT_WINDOW:
            return _err("edit_window", "Messages can only be edited for 15 minutes.", 409)
    return None


def _gone():
    return _err("deleted", "That message was deleted.", 409)


@bp.patch("/api/chat/messages/<int:mid>")
@_guard
def message_edit(acct, is_admin, mid: int):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or "body" not in payload:
        raise Bad("body is required")
    if payload["body"] is not None and not isinstance(payload["body"], str):
        raise Bad("body must be text")
    body = clean_body(payload["body"])
    if len(body) > BODY_MAX:
        raise Bad(f"The message is longer than {BODY_MAX} characters.", "body_too_long")
    with _Conn() as conn:
        users = _users(conn)
        # Every check runs on the row as it is under the write lock: a delete
        # (or archive) that committed a moment ago must win over this edit.
        _begin_write(conn)
        try:
            row = _message(conn, mid)
            denied = _editable(conn, acct, is_admin, row, editing=True)
            if denied:
                conn.rollback()
                return denied
            if not body and not _loads(row["attachments"]):
                raise Bad("Nothing to send.", "empty_message")
            author = users.get(row["user_id"]) if row["user_id"] is not None else None
            # New @mentions in the edited text are added; earlier ones are
            # kept (the mention was already delivered, and may have been read).
            ment = set(_loads(row["mentions"])) | parse_mentions(
                body, users, row["user_id"] if row["user_id"] is not None else -1,
                is_admin_account(author))
            ment.discard(row["user_id"])
            ment = sorted(m for m in ment if isinstance(m, int))
            cur = conn.execute(
                "UPDATE chat_messages SET body=?, mentions=?, edited_at=?,"
                " rev=(SELECT COALESCE(MAX(rev), 0) + 1 FROM chat_messages)"
                " WHERE id=? AND deleted_at IS NULL",
                (body, json.dumps(ment), _stamp(), mid))
            if cur.rowcount == 0:
                conn.rollback()
                return _gone()
            conn.executemany(
                "INSERT OR IGNORE INTO chat_mentions (message_id, user_id, channel_id)"
                " VALUES (?,?,?)", [(mid, u, row["channel_id"]) for u in ment])
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        return jsonify({"message": message_obj(_message(conn, mid), users, acct["id"])})


@bp.delete("/api/chat/messages/<int:mid>")
@_guard
def message_delete(acct, is_admin, mid: int):
    """Soft delete. Deleting an already-deleted message is 409 ``deleted``
    (the same answer an edit gets), whether it was deleted long ago or by a
    request that won the write lock a moment before this one."""
    with _Conn() as conn:
        _begin_write(conn)
        try:
            row = _message(conn, mid)
            denied = _editable(conn, acct, is_admin, row, editing=False)
            if denied:
                conn.rollback()
                return denied
            # Soft: the row (id, author, time) stays so the thread keeps its
            # shape and the delete reaches every client through sync; the
            # content itself is cleared.
            cur = conn.execute(
                "UPDATE chat_messages SET deleted_at=?, body='', attachments='[]',"
                " mentions='[]', rev=(SELECT COALESCE(MAX(rev), 0) + 1 FROM chat_messages)"
                " WHERE id=? AND deleted_at IS NULL", (_stamp(), mid))
            if cur.rowcount == 0:
                conn.rollback()
                return _gone()
            conn.execute("DELETE FROM chat_mentions WHERE message_id=?", (mid,))
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        return jsonify({"message": message_obj(_message(conn, mid), _users(conn), acct["id"])})


@bp.post("/api/chat/channels/<int:cid>/read")
@_guard
def channel_read(acct, is_admin, cid: int):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise Bad("expected a JSON object")
    want = _int(payload.get("last_read_id"), "last_read_id")
    uid = acct["id"]
    with _Conn() as conn:
        if not _channel(conn, cid):
            return _err("not_found", f"channel {cid} not found", 404)
        baseline = _ensure_baseline(conn, uid)
        top = conn.execute("SELECT COALESCE(MAX(id), 0) FROM chat_messages"
                           " WHERE channel_id=?", (cid,)).fetchone()[0]
        want = min(want, top)          # never past the end: no hiding the future
        conn.execute(
            "INSERT INTO chat_reads (user_id, channel_id, last_read_id) VALUES (?,?,?)"
            " ON CONFLICT(user_id, channel_id) DO UPDATE SET"
            " last_read_id = MAX(last_read_id, excluded.last_read_id)",
            (uid, cid, max(want, baseline)))
        conn.commit()
        last = conn.execute("SELECT last_read_id FROM chat_reads WHERE user_id=?"
                            " AND channel_id=?", (uid, cid)).fetchone()[0]
        unread = _unread_counts(conn, uid, baseline, include_archived=True).get(cid, 0)
        ments = sum(_mention_counts(conn, uid, baseline).values())
        return jsonify({"last_read_id": last, "unread": unread, "mentions": ments})


@bp.get("/api/chat/sync")
@_guard
def sync(acct, is_admin):
    since = _arg_int("since")
    uid = acct["id"]
    with _Conn() as conn:
        base, _ = _reads(conn, uid)
        if base is None:
            base = _ensure_baseline(conn, uid)
        # One read snapshot for everything below, so the cursor and the rows
        # it covers agree even while other threads are writing.
        conn.execute("BEGIN")
        try:
            cursor = _cursor(conn)
            messages, more = [], False
            if since is not None:
                rows = conn.execute(
                    "SELECT * FROM chat_messages WHERE rev > ? AND channel_id IN"
                    " (SELECT id FROM chat_channels WHERE archived_at IS NULL)"
                    " ORDER BY rev ASC LIMIT ?", (since, SYNC_MAX + 1)).fetchall()
                more = len(rows) > SYNC_MAX
                rows = rows[:SYNC_MAX]
                if more:
                    cursor = rows[-1]["rev"]
                if rows:
                    users = _users(conn)
                    messages = [message_obj(r, users, uid) for r in rows]
            unread = _unread_counts(conn, uid, base)
            mentions = sum(_mention_counts(conn, uid, base).values())
            stamp = _channels_stamp(conn)
        finally:
            conn.rollback()
    return jsonify({"cursor": cursor, "messages": messages, "more": more,
                    "unread": {str(k): v for k, v in unread.items()},
                    "mentions": mentions, "channels_stamp": stamp})


@bp.get("/api/chat/mentions")
@_guard
def mentions_list(acct, is_admin):
    limit = min(_arg_int("limit", MENTIONS_DEFAULT, minimum=1, maximum=10 ** 6), MENTIONS_MAX)
    with _Conn() as conn:
        rows = conn.execute(
            """SELECT m.*, c.name AS c_name, c.slug AS c_slug, c.kind AS c_kind
                 FROM chat_mentions x
                 JOIN chat_messages m ON m.id = x.message_id AND m.deleted_at IS NULL
                 JOIN chat_channels c ON c.id = x.channel_id
                WHERE x.user_id = ?
                ORDER BY x.message_id DESC LIMIT ?""", (acct["id"], limit)).fetchall()
        users = _users(conn)
        out = []
        for r in rows:
            msg = message_obj(r, users, acct["id"])
            msg["channel"] = {"id": r["channel_id"], "name": r["c_name"],
                              "slug": r["c_slug"], "kind": r["c_kind"]}
            out.append(msg)
    return jsonify({"messages": out})


@bp.get("/api/chat/people")
@_guard
def people(acct, is_admin):
    now = _now()
    with _Conn() as conn:
        users = conn.execute(
            "SELECT id, username, display_name FROM users WHERE disabled=0"
            " ORDER BY lower(COALESCE(display_name, username))").fetchall()
        try:
            beats = {r[0]: r[1] for r in conn.execute(
                "SELECT user_id, MAX(last_seen_at) FROM presence GROUP BY user_id")}
        except sqlite3.Error:
            beats = {}
    out = []
    for u in users:
        seen = _parse_ts(beats.get(u["id"]))
        age = None if seen is None else max(0.0, (now - seen).total_seconds())
        out.append({**_user_obj(u), "online": team.status_for(age) == "online",
                    "is_me": u["id"] == acct["id"]})
    return jsonify({"people": out})


# ------------------------------------------------- the old /api/chat shim
#
# A browser still holding the pre-channels bundle polls /api/chat?after=<id>
# and posts {sender, body}. Both keep working against #general; the typed
# sender is ignored — the message is from whoever is signed in.

def _general(conn):
    return conn.execute("SELECT * FROM chat_channels WHERE slug='general'").fetchone()


def _compat_row(r, users) -> dict:
    return {"id": r["id"], "sender": message_obj(r, users, -1)["sender"],
            "body": r["body"], "at": r["created_at"]}


@bp.get("/api/chat")
@_guard
def compat_get(acct, is_admin):
    try:
        after = _arg_int("after")
    except Bad:
        after = None
    with _Conn() as conn:
        gen = _general(conn)
        if after is None:
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE channel_id=? AND deleted_at IS NULL"
                " ORDER BY id DESC LIMIT ?", (gen["id"], COMPAT_TAIL)).fetchall()[::-1]
        else:
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE channel_id=? AND deleted_at IS NULL"
                " AND id>? ORDER BY id ASC LIMIT ?", (gen["id"], after, SYNC_MAX)).fetchall()
        latest = conn.execute("SELECT COALESCE(MAX(id), 0) FROM chat_messages"
                              " WHERE channel_id=?", (gen["id"],)).fetchone()[0]
        users = _users(conn)
        return jsonify({"messages": [_compat_row(r, users) for r in rows],
                        "latest": latest})


@bp.post("/api/chat")
@_guard
def compat_post(acct, is_admin):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    with _Conn() as conn:
        row, _ = post_message(conn, acct, is_admin, _general(conn),
                              {"body": payload.get("body")})
        return jsonify({"message": _compat_row(row, _users(conn))})
