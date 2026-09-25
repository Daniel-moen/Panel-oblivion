"""Per-person tasks and presence: who is doing what, and who is here.

Two small things the dashboard did not have, sharing one module because they
meet in the middle — the /online page shows each person's *in-progress* task
as what they are busy with.

Tasks (``user_tasks``)
----------------------
A to-do list per ACCOUNT, not per property: "phone the Blair Rd owner",
"send the Clifton film", "chase the bond originator". It is deliberately not
panel.py's ``tasks`` table — that one is a follow-up hung off a tracked
property and has no owner — though a user task may *link* to a property
group so the row can open the lead. The privilege rules are the whole design:

  * everyone sees and edits their OWN list, and nobody else's;
  * an admin (the owner, or anyone holding ``admin``) sees every list, may
    assign a task to anyone, and may edit or delete any task;
  * the server enforces it on every route — the UI's user switcher is drawn
    for admins as a courtesy, and a member who forges ``?user=`` gets 403.

``created_by`` records who wrote the task, so an assignee can see "from
Daniel" on something that landed in their list.

Presence (``presence``)
-----------------------
The SPA posts a heartbeat (``POST /api/presence``) every 45 seconds while the
tab is visible, and on every route change, carrying the path it is on. One
row per SESSION (the cookie's session id, so a person on a phone and a Mac
is two rows); the /online page collapses to one line per person using the
freshest row. Online = a beat in the last 2 minutes, away = 10, else offline
with a "last seen" — thresholds in ``status_for`` so they can be tested.

Persisted rather than in-memory on purpose: Railway restarts the process on
every deploy and "everyone vanished" would be the wrong thing to show.
"""

from __future__ import annotations

import re
import threading
from datetime import date, datetime, timezone

from flask import Blueprint, jsonify, request

import auth
import db

bp = Blueprint("team", __name__)

STATUSES = ("open", "in_progress", "done")
PRIORITIES = (1, 2, 3)              # 1 high · 2 normal · 3 low

#: Presence thresholds, in seconds since the last heartbeat.
ONLINE_S = 120
AWAY_S = 600
#: How often the client beats. Advertised to it in /api/online so the two
#: sides cannot drift apart if the threshold is ever tuned.
HEARTBEAT_S = 45

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_tasks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL,            -- the assignee (users.id)
    created_by        INTEGER,                     -- who wrote / assigned it
    title             TEXT NOT NULL,
    notes             TEXT,
    status            TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open', 'in_progress', 'done')),
    due_date          TEXT,                        -- 'YYYY-MM-DD' or NULL
    property_group_id TEXT,                        -- a prospect group, or NULL
    priority          INTEGER NOT NULL DEFAULT 2,  -- 1 high · 2 normal · 3 low
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    done_at           TEXT
);
CREATE INDEX IF NOT EXISTS idx_user_tasks_user ON user_tasks(user_id, status);

-- One row per signed-in browser that has sent a heartbeat. `session_id` is
-- the sessions.id for a cookie sign-in; basic-auth callers (curl, the owner
-- in a script) have no session and key on 'basic:<user id>' instead.
CREATE TABLE IF NOT EXISTS presence (
    session_id    TEXT PRIMARY KEY,
    user_id       INTEGER NOT NULL,
    page          TEXT,
    user_agent    TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_presence_user ON presence(user_id, last_seen_at);
"""

#: Columns added after the table first shipped go here so an older database
#: is brought up to date on boot — the same idempotent pattern db._migrate
#: uses. Nothing yet; the list exists so the next column has a home.
_TASK_COLUMNS: tuple[tuple[str, str], ...] = (
    ("notes", "TEXT"),
    ("due_date", "TEXT"),
    ("property_group_id", "TEXT"),
    ("priority", "INTEGER NOT NULL DEFAULT 2"),
    ("done_at", "TEXT"),
    ("created_by", "INTEGER"),
)

_schema_lock = threading.Lock()
_schema_done = False


def ensure_schema(conn) -> None:
    """Create both tables; add any column an older install is missing.

    Idempotent — safe to run on every boot and in every test.
    """
    global _schema_done
    with _schema_lock:
        conn.executescript(_SCHEMA)
        have = {r[1] for r in conn.execute("PRAGMA table_info(user_tasks)")}
        for col, ddl in _TASK_COLUMNS:
            if col not in have:
                conn.execute(f"ALTER TABLE user_tasks ADD COLUMN {col} {ddl}")
        conn.commit()
        _schema_done = True


def _conn():
    conn = db.connect()
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts):
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ------------------------------------------------------------- who is asking

def _actor():
    """(account dict, is_admin). The gate already refused anonymous calls."""
    acct = auth.account()
    return acct, bool(acct and "admin" in acct["privileges"])


def _unauth():
    return jsonify({"error": "auth_required"}), 401


# ------------------------------------------------------------------ tasks

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clean_date(raw):
    """'YYYY-MM-DD' or None; anything else is a 400 (the caller raises)."""
    if raw in (None, ""):
        return None
    s = str(raw).strip()[:10]
    if not _DATE_RE.match(s):
        raise ValueError("due_date must be YYYY-MM-DD")
    datetime.strptime(s, "%Y-%m-%d")           # a real calendar date
    return s


def _clean_task_fields(body: dict, *, creating: bool) -> dict:
    """The writable columns, validated. Raises ValueError with a message."""
    out: dict = {}
    if "title" in body or creating:
        title = str(body.get("title") or "").strip()[:200]
        if not title:
            raise ValueError("title is required")
        out["title"] = title
    if "notes" in body:
        out["notes"] = (str(body.get("notes") or "").strip()[:2000]) or None
    if "due_date" in body:
        out["due_date"] = _clean_date(body.get("due_date"))
    if "property_group_id" in body:
        gid = body.get("property_group_id")
        out["property_group_id"] = (str(gid).strip()[:32] or None) if gid not in (None, "") else None
    if "priority" in body:
        try:
            pr = int(body.get("priority") or 2)
        except (TypeError, ValueError):
            raise ValueError("priority must be 1, 2 or 3")
        if pr not in PRIORITIES:
            raise ValueError("priority must be 1, 2 or 3")
        out["priority"] = pr
    if "status" in body:
        st = str(body.get("status") or "")
        if st not in STATUSES:
            raise ValueError("status must be open, in_progress or done")
        out["status"] = st
    return out


def _property_labels(conn, gids: list) -> dict:
    """group id → a human label for the linked property, best effort."""
    gids = [str(g) for g in gids if g not in (None, "")]
    if not gids:
        return {}
    out: dict = {}
    q = ",".join("?" * len(gids))
    try:
        rows = conn.execute(
            f"""SELECT CAST(g.group_id AS TEXT) AS gid, l.street_address_raw,
                       l.title, l.suburb, l.price_zar
                  FROM property_groups g JOIN listings l ON l.listing_key = g.listing_key
                 WHERE CAST(g.group_id AS TEXT) IN ({q})
                 ORDER BY l.street_address_raw IS NULL, l.last_seen DESC""", gids).fetchall()
    except Exception:                # noqa: BLE001 - a bare DB without listings
        return {}
    for r in rows:
        if r["gid"] in out:
            continue
        out[r["gid"]] = {
            "label": r["street_address_raw"] or r["title"] or f"Property {r['gid']}",
            "suburb": r["suburb"],
            "price_zar": r["price_zar"],
        }
    return out


def _task_public(row, labels: dict, names: dict, today: str) -> dict:
    d = dict(row)
    gid = d.get("property_group_id")
    prop = labels.get(str(gid)) if gid else None
    d["property"] = ({"group_id": gid, **prop} if prop
                     else ({"group_id": gid, "label": f"Property {gid}"} if gid else None))
    d["overdue"] = bool(d["due_date"] and d["status"] != "done" and d["due_date"] < today)
    d["created_by_name"] = names.get(d.get("created_by"))
    d["user_name"] = names.get(d.get("user_id"))
    return d


def _names(conn) -> dict:
    return {r["id"]: (r["display_name"] or r["username"]) for r in
            conn.execute("SELECT id, username, display_name FROM users")}


def _target_user(conn, acct, is_admin, raw):
    """The user id a list/create call is about, or (None, response)."""
    if raw in (None, "", "me"):
        return acct["id"], None
    try:
        uid = int(raw)
    except (TypeError, ValueError):
        return None, (jsonify({"error": "bad_user"}), 400)
    if uid == acct["id"]:
        return uid, None
    if not is_admin:
        return None, auth.forbidden("admin")
    row = conn.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return None, (jsonify({"error": "not_found"}), 404)
    return uid, None


def _user_public(conn, uid: int) -> dict | None:
    r = conn.execute("SELECT id, username, display_name, role, disabled"
                     " FROM users WHERE id=?", (uid,)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "username": r["username"],
            "display_name": r["display_name"] or r["username"],
            "role": r["role"], "disabled": bool(r["disabled"])}


def _load(conn, task_id: int):
    return conn.execute("SELECT * FROM user_tasks WHERE id=?", (task_id,)).fetchone()


def _may_touch(acct, is_admin, row) -> bool:
    """Your own task, or any task if you are an admin."""
    return bool(row) and (is_admin or row["user_id"] == acct["id"])


def _respond_task(conn, row):
    today = date.today().isoformat()
    return jsonify(_task_public(row, _property_labels(conn, [row["property_group_id"]]),
                                _names(conn), today))


def _list_payload(conn, uid: int, include_done: bool = True) -> dict:
    today = date.today().isoformat()
    rows = conn.execute(
        """SELECT * FROM user_tasks WHERE user_id=?
            ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'open' THEN 1 ELSE 2 END,
                     CASE WHEN status='done' THEN done_at END DESC,
                     due_date IS NULL, due_date, priority, created_at""", (uid,)).fetchall()
    names = _names(conn)
    labels = _property_labels(conn, [r["property_group_id"] for r in rows])
    tasks = [_task_public(r, labels, names, today) for r in rows]
    done = [t for t in tasks if t["status"] == "done"]
    live = [t for t in tasks if t["status"] != "done"]
    counts = {
        "open": len(live),
        "in_progress": sum(1 for t in live if t["status"] == "in_progress"),
        "overdue": sum(1 for t in live if t["overdue"]),
        "done": len(done),
    }
    return {"user": _user_public(conn, uid), "counts": counts,
            "tasks": live + (done[:50] if include_done else [])}


@bp.get("/api/team/tasks")
def tasks_list():
    """My tasks — or, for an admin, ?user=<id>'s."""
    acct, is_admin = _actor()
    if not acct:
        return _unauth()
    with _conn() as conn:
        ensure_schema(conn)
        uid, err = _target_user(conn, acct, is_admin, request.args.get("user"))
        if err:
            return err
        out = _list_payload(conn, uid)
    out["is_admin"] = is_admin
    out["me"] = acct["id"]
    return jsonify(out)


@bp.get("/api/team/tasks/board")
@auth.require_priv("admin")
def tasks_board():
    """Every account with its live counts — the admin's user switcher."""
    with _conn() as conn:
        ensure_schema(conn)
        users = conn.execute(
            "SELECT id, username, display_name, role, disabled FROM users"
            " ORDER BY role='owner' DESC, role='admin' DESC, username").fetchall()
        today = date.today().isoformat()
        counts: dict = {}
        for r in conn.execute(
                "SELECT user_id, status, due_date FROM user_tasks WHERE status<>'done'"):
            c = counts.setdefault(r["user_id"], {"open": 0, "in_progress": 0, "overdue": 0})
            c["open"] += 1
            if r["status"] == "in_progress":
                c["in_progress"] += 1
            if r["due_date"] and r["due_date"] < today:
                c["overdue"] += 1
    return jsonify({"users": [{
        "id": u["id"], "username": u["username"],
        "display_name": u["display_name"] or u["username"], "role": u["role"],
        "disabled": bool(u["disabled"]),
        "counts": counts.get(u["id"], {"open": 0, "in_progress": 0, "overdue": 0}),
    } for u in users]})


@bp.post("/api/team/tasks")
def task_create():
    acct, is_admin = _actor()
    if not acct:
        return _unauth()
    body = request.get_json(silent=True) or {}
    try:
        fields = _clean_task_fields(body, creating=True)
    except ValueError as e:
        return jsonify({"error": "bad_request", "message": str(e)}), 400
    with _conn() as conn:
        ensure_schema(conn)
        uid, err = _target_user(conn, acct, is_admin, body.get("user_id"))
        if err:
            return err
        now = _now()
        status = fields.get("status", "open")
        cur = conn.execute(
            "INSERT INTO user_tasks (user_id, created_by, title, notes, status,"
            " due_date, property_group_id, priority, created_at, updated_at, done_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (uid, acct["id"], fields["title"], fields.get("notes"), status,
             fields.get("due_date"), fields.get("property_group_id"),
             fields.get("priority", 2), now, now, now if status == "done" else None))
        conn.commit()
        row = _load(conn, cur.lastrowid)
        return _respond_task(conn, row), 201


def _set_status(conn, row, status: str):
    now = _now()
    done_at = now if status == "done" else None
    conn.execute("UPDATE user_tasks SET status=?, done_at=?, updated_at=? WHERE id=?",
                 (status, done_at, now, row["id"]))
    conn.commit()
    return _load(conn, row["id"])


@bp.patch("/api/team/tasks/<int:task_id>")
def task_patch(task_id: int):
    acct, is_admin = _actor()
    if not acct:
        return _unauth()
    body = request.get_json(silent=True) or {}
    try:
        fields = _clean_task_fields(body, creating=False)
    except ValueError as e:
        return jsonify({"error": "bad_request", "message": str(e)}), 400
    with _conn() as conn:
        ensure_schema(conn)
        row = _load(conn, task_id)
        if not _may_touch(acct, is_admin, row):
            # 404, not 403: a member must not be able to probe which ids exist.
            return jsonify({"error": "not_found"}), 404
        if "user_id" in body:              # reassignment: admins only
            uid, err = _target_user(conn, acct, is_admin, body.get("user_id"))
            if err:
                return err
            fields["user_id"] = uid
        if not fields:
            return jsonify({"error": "nothing_to_update"}), 400
        now = _now()
        if "status" in fields:
            fields["done_at"] = now if fields["status"] == "done" else None
        fields["updated_at"] = now
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE user_tasks SET {sets} WHERE id=?",
                     (*fields.values(), task_id))
        conn.commit()
        return _respond_task(conn, _load(conn, task_id))


def _transition(task_id: int, status: str):
    acct, is_admin = _actor()
    if not acct:
        return _unauth()
    with _conn() as conn:
        ensure_schema(conn)
        row = _load(conn, task_id)
        if not _may_touch(acct, is_admin, row):
            return jsonify({"error": "not_found"}), 404
        return _respond_task(conn, _set_status(conn, row, status))


@bp.post("/api/team/tasks/<int:task_id>/start")
def task_start(task_id: int):
    """'I'm on it' — the one status the /online page reads as busy-with."""
    return _transition(task_id, "in_progress")


@bp.post("/api/team/tasks/<int:task_id>/complete")
def task_complete(task_id: int):
    return _transition(task_id, "done")


@bp.post("/api/team/tasks/<int:task_id>/reopen")
def task_reopen(task_id: int):
    return _transition(task_id, "open")


@bp.delete("/api/team/tasks/<int:task_id>")
def task_delete(task_id: int):
    acct, is_admin = _actor()
    if not acct:
        return _unauth()
    with _conn() as conn:
        ensure_schema(conn)
        row = _load(conn, task_id)
        if not _may_touch(acct, is_admin, row):
            return jsonify({"error": "not_found"}), 404
        conn.execute("DELETE FROM user_tasks WHERE id=?", (task_id,))
        conn.commit()
    return jsonify({"ok": True, "id": task_id})


@bp.get("/api/team/properties")
def property_search():
    """A few prospect groups matching ?q=, for the task's property link.

    Tracked leads first, then anything in the for-sale book by address,
    title or suburb. Eight rows: this is a picker, not a report.
    """
    if not auth.account():
        return _unauth()
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"results": []})
    like = f"%{q}%"
    with _conn() as conn:
        try:
            rows = conn.execute(
                """SELECT CAST(g.group_id AS TEXT) AS gid, l.street_address_raw,
                          l.title, l.suburb, l.price_zar, t.group_id AS tracked,
                          MAX(l.last_seen) AS seen
                     FROM property_groups g
                     JOIN listings l ON l.listing_key = g.listing_key
                     LEFT JOIN tracked_property t
                            ON t.group_id = CAST(g.group_id AS TEXT) AND t.archived_at IS NULL
                    WHERE l.listing_type = 'sale'
                      AND (l.street_address_raw LIKE ? OR l.title LIKE ? OR l.suburb LIKE ?)
                    GROUP BY g.group_id
                    ORDER BY t.group_id IS NULL, seen DESC
                    LIMIT 8""", (like, like, like)).fetchall()
        except Exception:            # noqa: BLE001 - no listings table yet
            rows = []
    return jsonify({"results": [{
        "group_id": r["gid"],
        "label": r["street_address_raw"] or r["title"] or f"Property {r['gid']}",
        "suburb": r["suburb"], "price_zar": r["price_zar"],
        "tracked": bool(r["tracked"]),
    } for r in rows]})


# --------------------------------------------------------------- presence

def status_for(seconds_since: float | None) -> str:
    """online / away / offline from the age of the last heartbeat."""
    if seconds_since is None:
        return "offline"
    if seconds_since <= ONLINE_S:
        return "online"
    if seconds_since <= AWAY_S:
        return "away"
    return "offline"


_PAGE_RE = re.compile(r"^/[A-Za-z0-9_\-./?=&%]{0,200}$")


def _presence_key(acct) -> str:
    sid = auth.session_id(request)
    if sid:
        return sid
    return f"{acct['via']}:{acct['id']}"


@bp.post("/api/presence")
def presence_beat():
    """The heartbeat. Cheap on purpose: one upsert, no reads."""
    acct = auth.account()
    if not acct:
        return _unauth()
    body = request.get_json(silent=True) or {}
    page = str(body.get("page") or "/")[:200]
    if not _PAGE_RE.match(page):
        page = "/"
    now = _now()
    with _conn() as conn:
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO presence (session_id, user_id, page, user_agent,"
            " first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(session_id) DO UPDATE SET"
            "  user_id=excluded.user_id, page=excluded.page,"
            "  user_agent=excluded.user_agent, last_seen_at=excluded.last_seen_at",
            (_presence_key(acct), acct["id"], page,
             (request.headers.get("User-Agent") or "")[:400], now, now))
        conn.commit()
    return jsonify({"ok": True, "at": now, "interval": HEARTBEAT_S})


def _initials(name: str) -> str:
    parts = [p for p in re.split(r"[\s._\-]+", name or "") if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _page_title(path: str | None) -> str:
    """'/leads/properties/12' → 'Leads · properties', for the busy line."""
    if not path or path == "/":
        return "Home"
    bits = [b for b in path.split("?")[0].split("/") if b]
    names = {"prospects": "Prospects", "agent": "Agent Z", "leads": "Leads",
             "map": "Map", "media": "Media", "account": "Account",
             "online": "Online", "cma": "CMA"}
    head = names.get(bits[0], bits[0].capitalize())
    if len(bits) > 1 and not bits[1].isdigit():
        return f"{head} · {bits[1].replace('-', ' ')}"
    return head


@bp.get("/api/online")
def online():
    """Everyone, with a presence status and what they are busy with.

    Members get the roster, the status and the busy-with line; admins also
    get each person's signed-in sessions (device, since, last beat, page)
    with the ids needed to revoke one.
    """
    acct, is_admin = _actor()
    if not acct:
        return _unauth()
    now_dt = datetime.now(timezone.utc)
    now = _now()
    here = auth.session_id(request)
    with _conn() as conn:
        ensure_schema(conn)
        users = conn.execute(
            "SELECT id, username, display_name, role, disabled, last_seen_at"
            " FROM users ORDER BY role='owner' DESC, role='admin' DESC, username").fetchall()
        beats = conn.execute(
            "SELECT * FROM presence ORDER BY last_seen_at DESC").fetchall()
        busy_rows = conn.execute(
            "SELECT * FROM user_tasks WHERE status='in_progress'"
            " ORDER BY updated_at DESC").fetchall()
        open_counts = {r["user_id"]: r["n"] for r in conn.execute(
            "SELECT user_id, COUNT(*) AS n FROM user_tasks WHERE status<>'done'"
            " GROUP BY user_id")}
        labels = _property_labels(conn, [r["property_group_id"] for r in busy_rows])
        sessions = {}
        if is_admin:
            for s in conn.execute(
                    "SELECT id, user_id, user, created_at, last_seen_at, user_agent"
                    " FROM sessions WHERE revoked=0 AND expires_at > ?"
                    " ORDER BY last_seen_at DESC", (now,)):
                sessions.setdefault(s["user_id"], []).append(s)

    by_user: dict = {}
    for b in beats:
        by_user.setdefault(b["user_id"], []).append(b)
    busy_by: dict = {}
    for t in busy_rows:
        gid = t["property_group_id"]
        prop = labels.get(str(gid)) if gid else None
        busy_by.setdefault(t["user_id"], []).append({
            "id": t["id"], "title": t["title"],
            "property": ({"group_id": gid, **prop} if prop else None),
            "since": t["updated_at"],
        })

    def age(ts):
        d = _parse(ts)
        return None if d is None else max(0.0, (now_dt - d).total_seconds())

    out = []
    for u in users:
        mine = by_user.get(u["id"], [])
        latest = mine[0] if mine else None
        last_ts = latest["last_seen_at"] if latest else u["last_seen_at"]
        seconds = age(last_ts)
        # A user row's last_seen_at is written by any authenticated request
        # (auth._session), so it is a fair "last seen" before the first beat
        # ever lands — but it never counts as ONLINE: that needs a heartbeat.
        status = status_for(age(latest["last_seen_at"])) if latest else "offline"
        if u["disabled"]:
            status = "offline"
        row = {
            "id": u["id"], "username": u["username"],
            "display_name": u["display_name"] or u["username"],
            "initials": _initials(u["display_name"] or u["username"]),
            "role": u["role"], "disabled": bool(u["disabled"]),
            "status": status,
            "last_seen_at": last_ts, "seconds_ago": seconds,
            "page": latest["page"] if latest and status != "offline" else None,
            "page_title": _page_title(latest["page"]) if latest and status != "offline" else None,
            "device": auth.device_name(latest["user_agent"] or "") if latest else None,
            "busy": busy_by.get(u["id"], []),
            "open_tasks": open_counts.get(u["id"], 0),
            "is_me": u["id"] == acct["id"],
        }
        if is_admin:
            beat_by_sid = {b["session_id"]: b for b in mine}
            row["sessions"] = [{
                "id": s["id"], "label": auth.device_name(s["user_agent"] or ""),
                "created_at": s["created_at"],
                "last_seen_at": (beat_by_sid[s["id"]]["last_seen_at"]
                                 if s["id"] in beat_by_sid else s["last_seen_at"]),
                "page": beat_by_sid[s["id"]]["page"] if s["id"] in beat_by_sid else None,
                "status": status_for(age(beat_by_sid[s["id"]]["last_seen_at"]))
                          if s["id"] in beat_by_sid else "offline",
                "current": s["id"] == here,
            } for s in sessions.get(u["id"], [])]
        out.append(row)

    order = {"online": 0, "away": 1, "offline": 2}
    out.sort(key=lambda r: (order[r["status"]], r["disabled"],
                            r["seconds_ago"] if r["seconds_ago"] is not None else 1e12))
    return jsonify({
        "now": now, "me": acct["id"], "is_admin": is_admin,
        "thresholds": {"online": ONLINE_S, "away": AWAY_S, "heartbeat": HEARTBEAT_S},
        "users": out,
        "online": sum(1 for r in out if r["status"] == "online"),
    })


@bp.post("/api/team/sessions/<sid>/revoke")
@auth.require_priv("admin")
def session_revoke_any(sid: str):
    """Sign somebody else's browser out. The owner is untouchable from here
    (they use their own account page); another admin only by the owner."""
    acct = auth.account()
    with _conn() as conn:
        ensure_schema(conn)
        s = conn.execute(
            "SELECT s.id, u.id AS uid, u.role FROM sessions s"
            " LEFT JOIN users u ON u.id = s.user_id OR u.username = s.user"
            " WHERE s.id=? AND s.revoked=0", (sid,)).fetchone()
        if not s:
            return jsonify({"error": "not_found"}), 404
        if s["uid"] != acct["id"]:
            if s["role"] == "owner":
                return jsonify({"error": "forbidden", "message":
                                "The owner's sessions cannot be revoked from here."}), 403
            if s["role"] == "admin" and not acct["is_owner"]:
                return jsonify({"error": "forbidden", "message":
                                "Only the owner can sign out another admin."}), 403
        conn.execute("DELETE FROM presence WHERE session_id=?", (sid,))
        conn.commit()
    auth.revoke_session(sid)
    return jsonify({"ok": True, "self": sid == auth.session_id(request)})
