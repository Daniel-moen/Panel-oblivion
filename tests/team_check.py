"""Checks for team.py: the task permission matrix, presence thresholds, and
the schema migration.

Plain script, no pytest needed (the repo has no test runner):

    DATA_DIR=$(mktemp -d) .venv/bin/python tests/team_check.py

It refuses to run without DATA_DIR pointing somewhere disposable, because
importing webapp opens DATA_DIR/prospects.db. Nothing here crawls or calls
out. Three accounts are made straight in the users table — a member, an
admin and the owner — and each gets a real session cookie via
auth.create_session, so every request goes through the same gate a browser
does.
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

data = os.environ.get("DATA_DIR")
if not data or os.path.abspath(data) == os.path.abspath(os.path.dirname(os.path.dirname(__file__))):
    sys.exit("Set DATA_DIR to a scratch directory (e.g. DATA_DIR=$(mktemp -d)).")
os.environ.setdefault("MEDIA_ROOT", tempfile.mkdtemp(prefix="media-root-"))
os.environ["DASHBOARD_USER"] = "owner"
os.environ["DASHBOARD_PASSWORD"] = "check-pass"
os.environ["AUTO_CRAWL"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth    # noqa: E402
import db      # noqa: E402
import team    # noqa: E402
import webapp  # noqa: E402

failures = []


def check(name, cond, extra: object = ""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({extra})" if extra and not cond else ""))
    if not cond:
        failures.append(name)


# --- the migration ------------------------------------------------------------
# An "older" user_tasks with only the first columns must gain the rest, and
# running ensure_schema twice must be a no-op.
with db.connect() as conn:
    conn.execute("DROP TABLE IF EXISTS user_tasks")
    conn.execute("CREATE TABLE user_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                 " user_id INTEGER NOT NULL, title TEXT NOT NULL,"
                 " status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL,"
                 " updated_at TEXT NOT NULL)")
    conn.execute("INSERT INTO user_tasks (user_id, title, created_at, updated_at)"
                 " VALUES (1, 'legacy row', 'x', 'x')")
    conn.commit()
    team.ensure_schema(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(user_tasks)")}
    check("migration adds the missing task columns",
          {"notes", "due_date", "property_group_id", "priority", "done_at", "created_by"} <= cols,
          sorted(cols))
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(presence)")}
    check("migration creates the presence table",
          {"session_id", "user_id", "page", "user_agent", "last_seen_at"} <= pcols)
    legacy = conn.execute("SELECT priority FROM user_tasks WHERE title='legacy row'").fetchone()
    check("legacy row survives with the default priority", legacy and legacy[0] == 2)
    team.ensure_schema(conn)
    check("ensure_schema is idempotent",
          cols == {r[1] for r in conn.execute("PRAGMA table_info(user_tasks)")})
    conn.execute("DELETE FROM user_tasks")
    conn.commit()

# --- accounts ------------------------------------------------------------------
now = auth._now()
with db.connect() as conn:
    auth.ensure_schema(conn)
    for name, role, privs in (("sam", "member", '["leads"]'),
                              ("alex", "member", '["leads"]'),
                              ("boss", "admin", '[]')):
        conn.execute("INSERT OR IGNORE INTO users (username, display_name, role, privileges,"
                     " created_at) VALUES (?,?,?,?,?)", (name, name.title(), role, privs, now))
    conn.commit()
    ids = {r["username"]: r["id"] for r in conn.execute("SELECT id, username FROM users")}

client = webapp.app.test_client()
BASIC = {"Authorization": "Basic " + base64.b64encode(b"owner:check-pass").decode()}


def cookie_client(username):
    c = webapp.app.test_client()
    tok = auth.create_session(username, f"check/{username}")
    c.set_cookie(auth.COOKIE_NAME, tok)
    return c


sam, alex, boss = cookie_client("sam"), cookie_client("alex"), cookie_client("boss")

# --- who may do what -------------------------------------------------------------
r = webapp.app.test_client().get("/api/team/tasks")
check("anonymous list is 401", r.status_code == 401, r.status_code)

r = sam.post("/api/team/tasks", json={"title": "Phone the Blair Rd owner", "due_date": "2026-01-01"})
check("member creates a task for themselves", r.status_code == 201, r.get_data(as_text=True)[:200])
t_sam = r.get_json()
check("created_by is recorded", t_sam["created_by"] == ids["sam"] and t_sam["user_id"] == ids["sam"])
check("a past due date reads as overdue", t_sam["overdue"] is True)

r = sam.post("/api/team/tasks", json={"title": "for alex", "user_id": ids["alex"]})
check("member cannot assign to another user", r.status_code == 403, r.status_code)

r = sam.get(f"/api/team/tasks?user={ids['alex']}")
check("member cannot list another user's tasks", r.status_code == 403, r.status_code)

r = sam.get("/api/team/tasks/board")
check("member cannot open the admin board", r.status_code == 403, r.status_code)

r = alex.get("/api/team/tasks")
check("another member sees none of sam's tasks",
      r.status_code == 200 and r.get_json()["tasks"] == [], r.get_json())

tid = t_sam["id"]
for verb, path, kw in (("PATCH", f"/api/team/tasks/{tid}", {"json": {"title": "hijack"}}),
                       ("POST", f"/api/team/tasks/{tid}/start", {}),
                       ("POST", f"/api/team/tasks/{tid}/complete", {}),
                       ("DELETE", f"/api/team/tasks/{tid}", {})):
    r = alex.open(path, method=verb, **kw)
    check(f"member {verb} on another's task is 404 (not probeable)", r.status_code == 404, r.status_code)

r = sam.post(f"/api/team/tasks/{tid}/start")
check("owner of the task can start it", r.status_code == 200 and r.get_json()["status"] == "in_progress")
r = sam.patch(f"/api/team/tasks/{tid}", json={"title": "Phone the owner", "priority": 1, "due_date": ""})
check("owner of the task can edit it",
      r.status_code == 200 and r.get_json()["priority"] == 1 and r.get_json()["due_date"] is None)
r = sam.patch(f"/api/team/tasks/{tid}", json={"user_id": ids["alex"]})
check("member cannot reassign their own task", r.status_code == 403, r.status_code)
r = sam.patch(f"/api/team/tasks/{tid}", json={"due_date": "not-a-date"})
check("bad due date is 400", r.status_code == 400, r.status_code)
r = sam.post("/api/team/tasks", json={"title": "   "})
check("empty title is 400", r.status_code == 400, r.status_code)

# admin
r = boss.get(f"/api/team/tasks?user={ids['sam']}")
check("admin lists a member's tasks",
      r.status_code == 200 and [t["id"] for t in r.get_json()["tasks"]] == [tid], r.get_json())
r = boss.post("/api/team/tasks", json={"title": "Send the Clifton film", "user_id": ids["alex"]})
check("admin assigns a task to a member", r.status_code == 201 and r.get_json()["user_id"] == ids["alex"])
t_alex = r.get_json()
check("assignment records the admin as creator", t_alex["created_by"] == ids["boss"]
      and t_alex["created_by_name"] == "Boss")
r = alex.get("/api/team/tasks")
check("the member sees what was assigned", [t["id"] for t in r.get_json()["tasks"]] == [t_alex["id"]])
r = boss.patch(f"/api/team/tasks/{t_alex['id']}", json={"user_id": ids["sam"], "notes": "moved"})
check("admin reassigns a task", r.status_code == 200 and r.get_json()["user_id"] == ids["sam"])
r = boss.get("/api/team/tasks/board")
board = r.get_json()
counts = {u["username"]: u["counts"] for u in board["users"]}
check("admin board counts per user", counts["sam"]["open"] == 2 and counts["sam"]["in_progress"] == 1
      and counts["alex"]["open"] == 0, counts)
r = boss.post(f"/api/team/tasks/{tid}/complete")
check("admin completes a member's task", r.status_code == 200 and r.get_json()["done_at"])
r = boss.post(f"/api/team/tasks/{tid}/reopen")
check("admin reopens it", r.status_code == 200 and r.get_json()["status"] == "open"
      and r.get_json()["done_at"] is None)
r = boss.delete(f"/api/team/tasks/{t_alex['id']}")
check("admin deletes any task", r.status_code == 200)

# owner (basic auth, no session)
r = client.get(f"/api/team/tasks?user={ids['alex']}", headers=BASIC)
check("owner lists any user's tasks", r.status_code == 200 and r.get_json()["is_admin"] is True)
r = client.post("/api/team/tasks", headers=BASIC,
                json={"title": "Chase the bond originator", "user_id": ids["alex"], "status": "in_progress"})
check("owner assigns an in-progress task", r.status_code == 201 and r.get_json()["status"] == "in_progress")
t_owner = r.get_json()
r = client.post("/api/team/tasks", headers=BASIC, json={"title": "Owner's own"})
check("owner creates for themself", r.status_code == 201 and r.get_json()["user_id"] == ids["owner"])
r = client.delete(f"/api/team/tasks/{t_sam['id']}", headers=BASIC)
check("owner deletes a member's task", r.status_code == 200)
r = sam.delete(f"/api/team/tasks/{t_owner['id']}")
check("member cannot delete an admin-owned task", r.status_code == 404, r.status_code)

# a disabled 'me' target and a bogus id
r = boss.get("/api/team/tasks?user=999999")
check("admin asking for an unknown user is 404", r.status_code == 404, r.status_code)
r = boss.get("/api/team/tasks?user=abc")
check("non-numeric user is 400", r.status_code == 400, r.status_code)

# --- presence ------------------------------------------------------------------
check("status: fresh beat is online", team.status_for(0) == "online")
check("status: 120s is still online", team.status_for(team.ONLINE_S) == "online")
check("status: 121s is away", team.status_for(team.ONLINE_S + 1) == "away")
check("status: 600s is still away", team.status_for(team.AWAY_S) == "away")
check("status: 601s is offline", team.status_for(team.AWAY_S + 1) == "offline")
check("status: never seen is offline", team.status_for(None) == "offline")

r = webapp.app.test_client().post("/api/presence", json={"page": "/"})
check("anonymous heartbeat is 401", r.status_code == 401, r.status_code)
r = sam.post("/api/presence", json={"page": "/leads/properties/12"})
check("member heartbeat lands", r.status_code == 200 and r.get_json()["interval"] == team.HEARTBEAT_S)
r = alex.post("/api/presence", json={"page": "javascript:alert(1)"})
check("a bad page is normalised", r.status_code == 200)
r = boss.post("/api/presence", json={"page": "/online"})

r = sam.get("/api/online")
o = r.get_json()
check("member gets the roster", r.status_code == 200 and {u["username"] for u in o["users"]}
      >= {"owner", "sam", "alex", "boss"})
by = {u["username"]: u for u in o["users"]}
check("a fresh heartbeat shows online", by["sam"]["status"] == "online" and by["boss"]["status"] == "online")
check("page title is derived", by["sam"]["page_title"] == "Leads · properties", by["sam"]["page_title"])
check("a bad page falls back to home", by["alex"]["page"] == "/", by["alex"]["page"])
check("busy-with lists the in-progress task",
      [b["title"] for b in by["alex"]["busy"]] == ["Chase the bond originator"], by["alex"]["busy"])
check("member never sees sessions", all("sessions" not in u for u in o["users"]))
check("owner without a beat is offline", by["owner"]["status"] == "offline", by["owner"])
check("online count", o["online"] == 3, o["online"])

# Age the beats and re-read: 5 minutes → away, 20 minutes → offline.
with db.connect() as conn:
    away = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    gone = (datetime.now(timezone.utc) - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("UPDATE presence SET last_seen_at=? WHERE user_id=?", (away, ids["sam"]))
    conn.execute("UPDATE presence SET last_seen_at=? WHERE user_id=?", (gone, ids["alex"]))
    conn.commit()
o = sam.get("/api/online").get_json()
by = {u["username"]: u for u in o["users"]}
check("5 min old beat is away", by["sam"]["status"] == "away", by["sam"]["status"])
check("20 min old beat is offline with a last-seen",
      by["alex"]["status"] == "offline" and by["alex"]["seconds_ago"] > 1100, by["alex"])
check("an offline user's page is not shown", by["alex"]["page"] is None)
ORDER = {"online": 0, "away": 1, "offline": 2}
ranks = [ORDER[u["status"]] for u in o["users"]]
check("sorted online → away → offline", ranks == sorted(ranks), ranks)

# admin sees sessions, and can revoke a member's
o = boss.get("/api/online").get_json()
by = {u["username"]: u for u in o["users"]}
check("admin sees each user's sessions", isinstance(by["sam"].get("sessions"), list)
      and len(by["sam"]["sessions"]) == 1, by["sam"].get("sessions"))
sess = by["sam"]["sessions"][0]
check("session carries device + current page", sess["page"] == "/leads/properties/12" and sess["label"])
check("admin's own session is flagged current", any(s["current"] for s in by["boss"]["sessions"]))

r = sam.post(f"/api/team/sessions/{sess['id']}/revoke")
check("member cannot revoke sessions", r.status_code == 403, r.status_code)
r = boss.post(f"/api/team/sessions/{sess['id']}/revoke")
check("admin revokes a member's session", r.status_code == 200, r.get_data(as_text=True)[:200])
r = sam.get("/api/team/tasks")
check("the revoked browser is signed out", r.status_code == 401, r.status_code)
o = boss.get("/api/online").get_json()
by = {u["username"]: u for u in o["users"]}
check("revoked session drops off the list", by["sam"]["sessions"] == [] and by["sam"]["status"] == "offline",
      by["sam"])

auth.create_session("owner", "check/owner")
with db.connect() as conn:
    owner_sess = conn.execute("SELECT id FROM sessions WHERE user='owner' ORDER BY rowid DESC"
                              " LIMIT 1").fetchone()["id"]
r = boss.post(f"/api/team/sessions/{owner_sess}/revoke")
check("admin cannot revoke the owner's session", r.status_code == 403, r.status_code)
boss_sess = [s for s in by["boss"]["sessions"]][0]["id"]
r = client.post(f"/api/team/sessions/{boss_sess}/revoke", headers=BASIC)
check("owner revokes an admin's session", r.status_code == 200, r.status_code)

print()
print(f"{len(failures)} failure(s)" if failures else "all checks passed")
sys.exit(1 if failures else 0)
