"""Tests for chat.py — channels, attachments, @mentions, read state, sync.

    .venv/bin/python -m pytest tests/test_chat.py -q

Self-contained: DATA_DIR is always a fresh temp directory (set before webapp
is imported), so nothing here can touch a real prospects.db. A legacy
team_chat table is seeded before the boot migration runs; users are made
straight in the users table and each gets a real session cookie through
auth.create_session, so every request passes the same gate a browser does.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from datetime import timedelta

import pytest

DATA = tempfile.mkdtemp(prefix="chat-test-")
os.environ["DATA_DIR"] = DATA
for k in ("DB_PATH", "DATABASE_URL", "CACHE_DIR"):
    os.environ.pop(k, None)
os.environ["MEDIA_ROOT"] = tempfile.mkdtemp(prefix="chat-media-root-")
os.environ["DASHBOARD_USER"] = "owner"
os.environ["DASHBOARD_PASSWORD"] = "check-pass"
os.environ["AUTO_CRAWL"] = "0"
os.environ["PROSPECTS_NO_WARM"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

assert os.path.abspath(config.DB_PATH).startswith(os.path.abspath(DATA)), config.DB_PATH

import db  # noqa: E402

# --- legacy chat + a couple of properties, before the boot migration -------
LEGACY = [(1, "Daniel", "first ever", "2026-09-20T08:00:00Z"),
          (2, "Sam", "second", "2026-09-20T08:01:00Z"),
          (5, "Alex", "gap in the ids", "2026-09-20T08:02:00Z")]
with db.connect() as _c:
    _c.executemany("INSERT INTO team_chat (id, sender, body, created_at) VALUES (?,?,?,?)",
                   LEGACY)
    for key, gid, addr, photo, tier in (("seed:a", 101, "12 Kloof Rd", "-", "warm"),
                                        ("seed:b", 101, None, "https://img.test/b.jpg", "hot"),
                                        ("seed:c", 102, "3 Beta Rd", "-", None)):
        db.upsert_listing(_c, {
            "listing_key": key, "source": "seed", "source_id": key[-1],
            "listing_type": "sale", "url": f"https://seed.test/{key}",
            "suburb_slug": "clifton", "suburb": "Clifton", "title": f"Home {key}",
            "price_zar": 9_500_000, "photo_url": photo, "street_address_raw": addr,
        })
        _c.execute("INSERT INTO property_groups (group_id, listing_key) VALUES (?,?)",
                   (gid, key))
        if tier:
            _c.execute("INSERT INTO scores (listing_key, tier) VALUES (?,?)", (key, tier))

import auth    # noqa: E402
import chat    # noqa: E402
import webapp  # noqa: E402  (boot: auth/team/chat ensure_schema, migration)

app = webapp.app

_now = auth._now()
with db.connect() as _c:
    for name, disp, role, disabled in (("boss", "Big Boss", "admin", 0),
                                       ("sam", "Sam Smith", "member", 0),
                                       ("alex", "Alex", "member", 0),
                                       ("gone", "Gone Person", "member", 1)):
        _c.execute("INSERT INTO users (username, display_name, role, privileges,"
                   " created_at, disabled) VALUES (?,?,?,?,?,?)",
                   (name, disp, role, '["leads"]', _now, disabled))
    _c.commit()
    IDS = {r["username"]: r["id"] for r in _c.execute("SELECT id, username FROM users")}


def client_for(username):
    c = app.test_client()
    c.set_cookie(auth.COOKIE_NAME, auth.create_session(username, f"test/{username}"))
    return c


owner, boss, sam, alex = (client_for(u) for u in ("owner", "boss", "sam", "alex"))


def general_id():
    with db.connect() as c:
        return c.execute("SELECT id FROM chat_channels WHERE slug='general'").fetchone()[0]


GEN = general_id()


def post(client, cid, body="", **kw):
    return client.post(f"/api/chat/channels/{cid}/messages", json={"body": body, **kw})


def new_topic(name):
    r = boss.post("/api/chat/channels", json={"name": name})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["channel"]["id"]


def unread_of(client, cid):
    chans = client.get("/api/chat/channels").get_json()["channels"]
    return next(c for c in chans if c["id"] == cid)


# ------------------------------------------------------------ migration

def test_migration_moves_legacy_rows():
    with db.connect() as c:
        rows = c.execute("SELECT * FROM chat_messages WHERE legacy_sender IS NOT NULL"
                         " ORDER BY id").fetchall()
    assert [(r["id"], r["legacy_sender"], r["body"], r["created_at"]) for r in rows] == LEGACY
    assert all(r["rev"] == r["id"] and r["channel_id"] == GEN and r["user_id"] is None
               for r in rows)
    msgs = sam.get(f"/api/chat/channels/{GEN}/messages").get_json()["messages"]
    legacy = [m for m in msgs if m["user"] is None]
    assert [m["sender"] for m in legacy] == ["Daniel", "Sam", "Alex"]


def test_migration_is_idempotent_and_leaves_team_chat():
    chat._schema_done = False
    with db.connect() as c:
        before = c.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
        chat.ensure_schema(c)
        chat._schema_done = False
        chat.ensure_schema(c)
        after = c.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
        legacy = c.execute("SELECT COUNT(*) FROM team_chat").fetchone()[0]
        gens = c.execute("SELECT COUNT(*) FROM chat_channels WHERE kind='general'").fetchone()[0]
    assert before == after
    assert legacy == len(LEGACY)
    assert gens == 1
    # A new message lands after the legacy ids and revs.
    m = post(alex, GEN, "after migration").get_json()["message"]
    assert m["id"] > 5 and m["rev"] > 5


# ------------------------------------------------------------- channels

def test_anonymous_is_refused():
    anon = app.test_client()
    assert anon.get("/api/chat/sync").status_code == 401
    assert anon.get("/api/chat/channels").status_code == 401


def test_channel_create_permissions():
    r = sam.post("/api/chat/channels", json={"name": "deals"})
    assert r.status_code == 403
    r = boss.post("/api/chat/channels", json={"name": "Deals"})
    assert r.status_code == 201
    ch = r.get_json()["channel"]
    assert ch["kind"] == "topic" and ch["slug"] == "deals"
    assert owner.post("/api/chat/channels", json={"name": "deals"}).status_code == 409
    assert boss.post("/api/chat/channels", json={"name": "General"}).status_code == 409
    assert boss.post("/api/chat/channels", json={"name": "   "}).status_code == 400
    assert boss.post("/api/chat/channels", json={"name": "x" * 41}).status_code == 400


def test_property_channel_idempotent():
    r = sam.post("/api/chat/channels", json={"property_gid": 101})
    assert r.status_code == 201, r.get_json()
    ch = r.get_json()["channel"]
    assert ch["kind"] == "property" and ch["property_gid"] == 101
    assert ch["property"]["photo_url"] == "https://img.test/b.jpg"   # '-' skipped
    assert ch["property"]["tier"] == "hot"
    assert ch["property"]["label"] == "12 Kloof Rd"
    r2 = alex.post("/api/chat/channels", json={"property_gid": "101"})
    assert r2.status_code == 200 and r2.get_json()["channel"]["id"] == ch["id"]
    r3 = sam.post("/api/chat/channels", json={"property_gid": 999})
    assert r3.status_code == 400 and "999" in r3.get_json()["message"]
    assert sam.post("/api/chat/channels", json={"property_gid": "1; DROP"}).status_code == 400
    chans = sam.get("/api/chat/channels").get_json()
    kinds = [c["kind"] for c in chans["channels"]]
    first_prop = kinds.index("property")
    assert kinds[0] == "general" and all(k == "property" for k in kinds[first_prop:])
    assert chans["me"]["id"] == IDS["sam"] and chans["me"]["is_admin"] is False


def test_channel_patch_and_archive():
    cid = new_topic("to-archive")
    assert sam.patch(f"/api/chat/channels/{cid}", json={"archived": True}).status_code == 403
    assert boss.patch(f"/api/chat/channels/{GEN}", json={"archived": True}).status_code == 400
    before = sam.get("/api/chat/sync").get_json()["channels_stamp"]
    r = boss.patch(f"/api/chat/channels/{cid}", json={"archived": True, "name": "old stuff"})
    assert r.status_code == 200 and r.get_json()["channel"]["archived_at"]
    assert sam.get("/api/chat/sync").get_json()["channels_stamp"] != before
    r = post(sam, cid, "hello?")
    assert r.status_code == 409 and r.get_json()["error"] == "archived"
    ids = [c["id"] for c in sam.get("/api/chat/channels").get_json()["channels"]]
    assert cid not in ids
    ids = [c["id"] for c in boss.get("/api/chat/channels?archived=1").get_json()["channels"]]
    assert cid in ids
    assert boss.patch(f"/api/chat/channels/{cid}", json={"archived": False}).status_code == 200
    assert post(sam, cid, "back").status_code == 201


# ------------------------------------------------------------ validation

def _msg(r):
    return (r.get_json() or {}).get("message", "")


def test_bad_property_gid():
    r = post(sam, GEN, "look", attachments=[{"type": "property", "gid": 4242}])
    assert r.status_code == 400 and "4242" in _msg(r)
    r = post(sam, GEN, "look", attachments=[{"type": "property", "gid": 102}])
    assert r.status_code == 201
    att = r.get_json()["message"]["attachments"][0]
    assert att == {"type": "property", "gid": 102, "label": "3 Beta Rd", "suburb": "Clifton",
                   "price_zar": 9_500_000, "tier": None, "photo_url": None}


def test_media_attachments(monkeypatch):
    # (boss is an admin: every privilege, media included.)
    # No Zerko catalogue in the scratch DATA_DIR: the real lookup says so.
    r = post(boss, GEN, "pic", attachments=[{"type": "media", "id": 7}])
    assert r.status_code == 400 and "media library unavailable" in _msg(r)
    monkeypatch.setattr(chat, "media_lookup", lambda ids: {
        7: {"name": "kitchen.jpg", "kind": "photo", "thumb": "/thumbnails/7.jpg",
            "caption": None}})
    r = post(boss, GEN, "pic", attachments=[{"type": "media", "id": 8}])
    assert r.status_code == 400 and "8" in _msg(r)
    r = post(boss, GEN, "", attachments=[{"type": "media", "id": 7, "caption": "the kitchen"}])
    assert r.status_code == 201
    att = r.get_json()["message"]["attachments"][0]
    assert att == {"type": "media", "id": 7, "name": "kitchen.jpg", "kind": "photo",
                   "thumb": "/thumbnails/7.jpg", "caption": "the kitchen"}


@pytest.mark.parametrize("url", ["ftp://example.com/x", "javascript:alert(1)",
                                 "JavaScript:alert(1)", "http://", "https:///path",
                                 "data:text/html,<b>x</b>", "http://exa mple.com",
                                 "https://" + "a" * 2050 + ".com", "example.com"])
def test_bad_links(url):
    r = post(sam, GEN, "link", attachments=[{"type": "link", "url": url}])
    assert r.status_code == 400, url


def test_good_link_and_title_cap():
    r = post(sam, GEN, "", attachments=[{"type": "link", "url": "https://Example.com/a?b=1",
                                         "title": "A page"}])
    assert r.status_code == 201
    att = r.get_json()["message"]["attachments"][0]
    assert att == {"type": "link", "url": "https://Example.com/a?b=1", "title": "A page",
                   "domain": "example.com"}
    r = post(sam, GEN, "x", attachments=[{"type": "link", "url": "https://e.com",
                                          "title": "t" * 201}])
    assert r.status_code == 400


def test_attachment_limits_and_types():
    seven = [{"type": "link", "url": f"https://e.com/{i}"} for i in range(7)]
    assert post(sam, GEN, "x", attachments=seven).status_code == 400
    assert post(sam, GEN, "x", attachments=seven[:6]).status_code == 201
    r = post(sam, GEN, "x", attachments=[{"type": "file", "path": "/etc/passwd"}])
    assert r.status_code == 400 and "file" in _msg(r)
    assert post(sam, GEN, "x", attachments="nope").status_code == 400


def test_mention_validation():
    r = post(sam, GEN, "hi", mentions=[99999])
    assert r.status_code == 400 and "99999" in _msg(r)
    r = post(sam, GEN, "hi", mentions=[IDS["gone"]])
    assert r.status_code == 400 and str(IDS["gone"]) in _msg(r)
    r = post(sam, GEN, "hi", mentions=["abc"])
    assert r.status_code == 400
    r = post(sam, GEN, "hi @alex", mentions=[IDS["alex"], IDS["sam"]])
    assert r.status_code == 201 and r.get_json()["message"]["mentions"] == [IDS["alex"]]


def test_body_sanitising_and_limits():
    r = post(sam, GEN, "  a\x07b\r\nc\x00d\te\x7f  ")
    assert r.status_code == 201 and r.get_json()["message"]["body"] == "ab\ncd\te"
    assert post(sam, GEN, "x" * 2001).status_code == 400
    assert post(sam, GEN, "x" * 2000).status_code == 201
    r = post(sam, GEN, "   \x01  ")
    assert r.status_code == 400 and r.get_json()["error"] == "empty_message"
    assert post(sam, GEN, None).status_code == 400
    assert post(sam, GEN, {"x": 1}).status_code == 400
    assert post(sam, 987654, "nowhere").status_code == 404


def test_script_is_stored_as_text():
    body = '<script>alert("x")</script> <img src=x onerror=alert(1)> &amp;'
    r = post(sam, GEN, body)
    m = r.get_json()["message"]
    assert r.status_code == 201 and m["body"] == body
    assert r.mimetype == "application/json"
    got = sam.get(f"/api/chat/channels/{GEN}/messages?after={m['id'] - 1}").get_json()
    assert got["messages"][0]["body"] == body


# --------------------------------------------------------------- mentions

def test_mention_parsing_from_body():
    def ments(client, body):
        r = post(client, GEN, body)
        assert r.status_code == 201, r.get_json()
        return set(r.get_json()["message"]["mentions"])

    assert ments(sam, "@alex can you call?") == {IDS["alex"]}
    assert ments(alex, "thanks @Sam Smith!") == {IDS["sam"]}
    assert ments(alex, "@SAM, ok") == {IDS["sam"]}
    assert ments(sam, "note to @sam self") == set()
    assert ments(sam, "@alexander is not alex") == set()
    assert ments(sam, "mail me at x@alex.com") == set()
    assert ments(sam, "@gone are you there") == set()            # disabled
    assert ments(sam, "@everyone lunch") == set()                 # member: plain text
    active = {IDS[u] for u in ("owner", "boss", "sam", "alex")}
    assert ments(boss, "@everyone lunch") == active - {IDS["boss"]}
    assert ments(owner, "@here standup") == active - {IDS["owner"]}
    m = post(sam, GEN, "@alex hi").get_json()["message"]
    got = alex.get(f"/api/chat/channels/{GEN}/messages?after={m['id'] - 1}").get_json()
    assert got["messages"][0]["mentions_me"] is True


def test_parse_mentions_unit():
    users = {1: {"id": 1, "username": "al", "display_name": "Al Green", "disabled": 0},
             2: {"id": 2, "username": "algreen", "display_name": None, "disabled": 0}}
    assert chat.parse_mentions("@al green hi", users, 99, False) == {1}
    assert chat.parse_mentions("@algreen hi", users, 99, False) == {2}
    assert chat.parse_mentions("@al", users, 99, False) == {1}
    assert chat.parse_mentions("@alg", users, 99, False) == set()
    assert chat.parse_mentions("@everyone", users, 1, True) == {2}


def test_mentions_endpoint():
    m = post(boss, GEN, "@alex see this").get_json()["message"]
    got = alex.get("/api/chat/mentions?limit=5").get_json()["messages"]
    assert got[0]["id"] == m["id"] and got[0]["channel"]["slug"] == "general"
    assert alex.get("/api/chat/mentions?limit=abc").status_code == 400


# -------------------------------------------------------- edit / delete

def test_edit_and_delete_permissions(monkeypatch):
    m = post(sam, GEN, "draft").get_json()["message"]
    r = sam.patch(f"/api/chat/messages/{m['id']}", json={"body": "final @alex"})
    assert r.status_code == 200
    e = r.get_json()["message"]
    assert e["body"] == "final @alex" and e["edited_at"] and e["rev"] > m["rev"]
    assert IDS["alex"] in e["mentions"]
    assert alex.patch(f"/api/chat/messages/{m['id']}", json={"body": "x"}).status_code == 403
    assert sam.patch(f"/api/chat/messages/{m['id']}", json={"body": "x" * 2001}).status_code == 400

    later = chat._now() + timedelta(minutes=16)
    monkeypatch.setattr(chat, "_now", lambda: later)
    r = sam.patch(f"/api/chat/messages/{m['id']}", json={"body": "too late"})
    assert r.status_code == 409 and r.get_json()["error"] == "edit_window"
    r = boss.patch(f"/api/chat/messages/{m['id']}", json={"body": "admin fix"})
    assert r.status_code == 200 and r.get_json()["message"]["body"] == "admin fix"
    monkeypatch.undo()

    assert alex.delete(f"/api/chat/messages/{m['id']}").status_code == 403
    r = sam.delete(f"/api/chat/messages/{m['id']}")
    d = r.get_json()["message"]
    assert r.status_code == 200 and d["deleted"] and d["body"] == "" and d["attachments"] == []
    assert sam.patch(f"/api/chat/messages/{m['id']}", json={"body": "x"}).status_code == 409
    assert sam.delete("/api/chat/messages/99999999").status_code == 404
    # Legacy rows belong to nobody: only an admin may remove them.
    assert sam.delete("/api/chat/messages/2").status_code == 403
    assert boss.delete("/api/chat/messages/2").status_code == 200


# ---------------------------------------------------------- read state

def test_read_cursor_and_unread():
    cid = new_topic("reads")
    ids = [post(alex, cid, f"m{i}").get_json()["message"]["id"] for i in range(3)]
    post(sam, cid, "my own does not count")
    assert unread_of(sam, cid)["unread"] == 3
    r = sam.post(f"/api/chat/channels/{cid}/read", json={"last_read_id": ids[1]})
    assert r.status_code == 200 and r.get_json()["last_read_id"] == ids[1]
    assert r.get_json()["unread"] == 1
    r = sam.post(f"/api/chat/channels/{cid}/read", json={"last_read_id": ids[0]})
    assert r.get_json()["last_read_id"] == ids[1]              # never goes back
    r = sam.post(f"/api/chat/channels/{cid}/read", json={"last_read_id": 10 ** 12})
    assert r.get_json()["last_read_id"] < 10 ** 12             # clamped to the channel
    assert r.get_json()["unread"] == 0
    assert sam.post(f"/api/chat/channels/{cid}/read",
                    json={"last_read_id": "x"}).status_code == 400
    # A deleted message stops counting; a mention counts until read.
    m1 = post(alex, cid, "@sam look").get_json()["message"]
    m2 = post(alex, cid, "oops").get_json()["message"]
    ch = unread_of(sam, cid)
    assert ch["unread"] == 2 and ch["mentions"] == 1
    sync = sam.get("/api/chat/sync").get_json()
    assert sync["unread"][str(cid)] == 2 and sync["mentions"] >= 1
    alex.delete(f"/api/chat/messages/{m2['id']}")
    assert unread_of(sam, cid)["unread"] == 1
    r = sam.post(f"/api/chat/channels/{cid}/read", json={"last_read_id": m1["id"]})
    assert r.get_json()["unread"] == 0
    assert unread_of(sam, cid)["mentions"] == 0


def test_baseline_for_new_user():
    post(alex, GEN, "history before newbie")
    with db.connect() as c:
        c.execute("INSERT INTO users (username, display_name, role, privileges, created_at)"
                  " VALUES ('newbie', 'New Bie', 'member', '[]', ?)", (auth._now(),))
        c.commit()
    nb = client_for("newbie")
    assert unread_of(nb, GEN)["unread"] == 0
    post(alex, GEN, "welcome")
    assert unread_of(nb, GEN)["unread"] == 1
    cid = new_topic("after-newbie")
    post(alex, cid, "one")
    post(alex, cid, "two")
    assert nb.get("/api/chat/sync").get_json()["unread"][str(cid)] == 2


# ----------------------------------------------------------------- sync

def test_sync_cursor_semantics():
    first = sam.get("/api/chat/sync").get_json()
    assert first["messages"] == [] and isinstance(first["cursor"], int)
    assert sam.get("/api/chat/sync?since=-1").status_code == 400
    assert sam.get("/api/chat/sync?since=abc").status_code == 400
    cur = first["cursor"]
    m = post(alex, GEN, "sync me").get_json()["message"]
    s = sam.get(f"/api/chat/sync?since={cur}").get_json()
    assert [x["id"] for x in s["messages"]] == [m["id"]] and s["cursor"] == m["rev"]
    cur = s["cursor"]
    assert sam.get(f"/api/chat/sync?since={cur}").get_json()["messages"] == []
    alex.patch(f"/api/chat/messages/{m['id']}", json={"body": "edited"})
    s = sam.get(f"/api/chat/sync?since={cur}").get_json()
    assert [(x["id"], x["body"]) for x in s["messages"]] == [(m["id"], "edited")]
    assert s["messages"][0]["edited_at"]
    cur = s["cursor"]
    alex.delete(f"/api/chat/messages/{m['id']}")
    s = sam.get(f"/api/chat/sync?since={cur}").get_json()
    assert [(x["id"], x["deleted"], x["body"]) for x in s["messages"]] == [(m["id"], True, "")]


def test_sync_more_when_over_200():
    cid = new_topic("flood")
    cur = sam.get("/api/chat/sync").get_json()["cursor"]
    posted = [post(alex, cid, f"f{i}").get_json()["message"]["id"] for i in range(205)]
    s = sam.get(f"/api/chat/sync?since={cur}").get_json()
    assert len(s["messages"]) == 200 and s["more"] is True
    s2 = sam.get(f"/api/chat/sync?since={s['cursor']}").get_json()
    assert s2["more"] is False
    got = [x["id"] for x in s["messages"] + s2["messages"]]
    assert got == posted
    page = sam.get(f"/api/chat/channels/{cid}/messages?limit=500").get_json()
    assert len(page["messages"]) == 200 and page["has_more"] is True
    older = sam.get(f"/api/chat/channels/{cid}/messages?before={page['messages'][0]['id']}"
                    ).get_json()
    assert [x["id"] for x in older["messages"]] == posted[:5] and older["has_more"] is False
    tail = sam.get(f"/api/chat/channels/{cid}/messages").get_json()
    assert [x["id"] for x in tail["messages"]] == posted[-50:]


def test_sync_skips_archived_channels():
    cid = new_topic("hidden-sync")
    cur = sam.get("/api/chat/sync").get_json()["cursor"]
    post(alex, cid, "secretish")
    boss.patch(f"/api/chat/channels/{cid}", json={"archived": True})
    s = sam.get(f"/api/chat/sync?since={cur}").get_json()
    assert all(x["channel_id"] != cid for x in s["messages"])
    assert str(cid) not in s["unread"]


def test_concurrent_posts_and_sync():
    cid = new_topic("busy")
    start_cursor = sam.get("/api/chat/sync").get_json()["cursor"]
    writers_done = threading.Event()
    posted: list[int] = []
    posted_lock = threading.Lock()
    errors: list = []
    seen: list[tuple[int, int]] = []

    def writer(n):
        c = client_for(["sam", "alex", "boss", "owner"][n % 4])
        for i in range(25):
            r = post(c, cid, f"t{n}-{i}")
            if r.status_code != 201:
                errors.append(r.status_code)
                continue
            with posted_lock:
                posted.append(r.get_json()["message"]["id"])

    def reader():
        c = client_for("alex")
        cur = start_cursor
        while True:
            done = writers_done.is_set()
            s = c.get(f"/api/chat/sync?since={cur}").get_json()
            seen.extend((m["rev"], m["id"]) for m in s["messages"])
            cur = s["cursor"]
            if done and not s["more"]:
                break
            time.sleep(0.005)

    rt = threading.Thread(target=reader)
    rt.start()
    ws = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in ws:
        t.start()
    for t in ws:
        t.join()
    writers_done.set()
    rt.join(timeout=60)
    assert not errors
    assert len(posted) == 200
    revs = [r for r, _ in seen]
    assert all(a < b for a, b in zip(revs, revs[1:])), "revs must strictly increase"
    ids = [i for _, i in seen]
    assert sorted(ids) == sorted(posted) and len(set(ids)) == len(ids)


# ---------------------------------------------------------- idempotency

def test_client_id_retry():
    r1 = post(sam, GEN, "once", client_id="cid-123")
    r2 = post(sam, GEN, "once", client_id="cid-123")
    assert r1.status_code == 201 and r2.status_code == 200
    assert r1.get_json()["message"]["id"] == r2.get_json()["message"]["id"]
    assert r2.get_json()["message"]["client_id"] == "cid-123"
    r3 = post(alex, GEN, "once", client_id="cid-123")
    assert r3.status_code == 201 and r3.get_json()["message"]["id"] != r1.get_json()["message"]["id"]
    assert post(sam, GEN, "x", client_id="bad id!").status_code == 400
    assert post(sam, GEN, "x", client_id="x" * 65).status_code == 400


# --------------------------------------------------------------- compat

def test_compat_shim():
    r = sam.post("/api/chat", json={"sender": "Impostor", "body": "old client here"})
    assert r.status_code == 200
    m = r.get_json()["message"]
    assert m["sender"] == "Sam Smith" and m["body"] == "old client here"
    assert set(m) == {"id", "sender", "body", "at"}
    g = sam.get("/api/chat").get_json()
    assert g["latest"] >= m["id"] and g["messages"][-1]["id"] == m["id"]
    assert set(g["messages"][0]) == {"id", "sender", "body", "at"}
    g2 = sam.get(f"/api/chat?after={m['id'] - 1}").get_json()
    assert [x["id"] for x in g2["messages"]] == [m["id"]]
    assert sam.post("/api/chat", json={"body": "  "}).status_code == 400
    page = sam.get(f"/api/chat/channels/{GEN}/messages").get_json()["messages"]
    assert page[-1]["id"] == m["id"] and page[-1]["user"]["username"] == "sam"


# ---------------------------------------------------------------- people

def test_people():
    ppl = sam.get("/api/chat/people").get_json()["people"]
    names = {p["username"] for p in ppl}
    assert {"owner", "boss", "sam", "alex"} <= names and "gone" not in names
    me = next(p for p in ppl if p["username"] == "sam")
    assert me["is_me"] and me["initials"] == "SS" and me["display_name"] == "Sam Smith"


def test_discuss_reopens_archived_property_channel():
    ch = sam.post("/api/chat/channels", json={"property_gid": 101}).get_json()["channel"]
    assert boss.patch(f"/api/chat/channels/{ch['id']}", json={"archived": True}).status_code == 200
    r = alex.post("/api/chat/channels", json={"property_gid": 101})
    assert r.status_code == 200
    again = r.get_json()["channel"]
    assert again["id"] == ch["id"] and not again["archived_at"]
    assert post(alex, ch["id"], "back on it").status_code == 201


# ============================================================ review fixes

# ---- 1. link spoofing -----------------------------------------------------

@pytest.mark.parametrize("url", [
    "http://evil.com\\@good.com/",          # browsers read \ as /
    "http://evil.com\\.good.com/",
    "https://user@good.com/",
    "https://user:pw@good.com/",
    "https://:pw@good.com/",
    "https://exämple.com/",                 # non-ASCII: paste the encoded form
    "https://example.com/café",
    "https://example.com/‮exe.txt",
    "https://example.com/a\tb",
    "https://example.com/a\nb",
    "https://good.com:99999/",              # port out of range
    "https://good.com:abc/",
])
def test_link_spoofing_refused(url):
    r = post(sam, GEN, "link", attachments=[{"type": "link", "url": url}])
    assert r.status_code == 400, url
    assert r.get_json()["error"] == "bad_attachment"


def test_link_non_ascii_message_and_domain():
    r = post(sam, GEN, "x", attachments=[{"type": "link", "url": "https://exämple.com"}])
    assert "encoded" in _msg(r)
    r = post(sam, GEN, "", attachments=[{"type": "link",
                                         "url": "https://WWW.Good.com:8443/p?q=1#f"}])
    assert r.status_code == 201
    att = r.get_json()["message"]["attachments"][0]
    assert att["domain"] == "good.com" and att["url"] == "https://WWW.Good.com:8443/p?q=1#f"
    r = post(sam, GEN, "", attachments=[{"type": "link", "url": "https://xn--exmple-cua.com/"}])
    assert r.status_code == 201
    assert r.get_json()["message"]["attachments"][0]["domain"] == "xn--exmple-cua.com"


# ---- 2. media needs the media privilege -----------------------------------

def test_media_needs_privilege(monkeypatch):
    calls = []

    def lookup(ids):
        calls.append(ids)
        return {7: {"name": "k.jpg", "kind": "photo", "thumb": "/t/7.jpg", "caption": None}}
    monkeypatch.setattr(chat, "media_lookup", lookup)
    exists = post(sam, GEN, "pic", attachments=[{"type": "media", "id": 7}])
    missing = post(sam, GEN, "pic", attachments=[{"type": "media", "id": 8}])
    for r in (exists, missing):
        assert r.status_code == 403 and r.get_json()["error"] == "media_forbidden"
    assert exists.get_json() == missing.get_json()   # nothing learnt about ids
    assert calls == []                                # refused before any lookup
    with db.connect() as c:
        c.execute("UPDATE users SET privileges='[\"leads\",\"media\"]' WHERE username='alex'")
        c.commit()
    try:
        r = post(client_for("alex"), GEN, "pic", attachments=[{"type": "media", "id": 7}])
        assert r.status_code == 201, r.get_json()
    finally:
        with db.connect() as c:
            c.execute("UPDATE users SET privileges='[\"leads\"]' WHERE username='alex'")
            c.commit()


# ---- 3. edit / delete race ------------------------------------------------

def _delete_before_lock(monkeypatch, mid):
    """Make a concurrent delete commit between the handler's first look and
    its write lock: the first _begin_write soft-deletes the row first."""
    real = chat._begin_write
    state = {"done": False}

    def racing(conn):
        if not state["done"]:
            state["done"] = True
            with db.connect() as other:
                other.execute("UPDATE chat_messages SET deleted_at='2026-01-01T00:00:00Z',"
                              " body='', rev=(SELECT MAX(rev)+1 FROM chat_messages)"
                              " WHERE id=?", (mid,))
                other.commit()
        real(conn)
    monkeypatch.setattr(chat, "_begin_write", racing)


def test_edit_loses_to_concurrent_delete(monkeypatch):
    m = post(sam, GEN, "soon gone").get_json()["message"]
    _delete_before_lock(monkeypatch, m["id"])
    r = sam.patch(f"/api/chat/messages/{m['id']}", json={"body": "resurrect @alex"})
    assert r.status_code == 409 and r.get_json()["error"] == "deleted"
    monkeypatch.undo()
    with db.connect() as c:
        row = c.execute("SELECT * FROM chat_messages WHERE id=?", (m["id"],)).fetchone()
        n = c.execute("SELECT COUNT(*) FROM chat_mentions WHERE message_id=?",
                      (m["id"],)).fetchone()[0]
    assert row["body"] == "" and row["deleted_at"] and n == 0


def test_delete_twice_is_409(monkeypatch):
    m = post(sam, GEN, "delete me").get_json()["message"]
    _delete_before_lock(monkeypatch, m["id"])
    r = sam.delete(f"/api/chat/messages/{m['id']}")
    assert r.status_code == 409 and r.get_json()["error"] == "deleted"
    monkeypatch.undo()
    assert sam.delete(f"/api/chat/messages/{m['id']}").status_code == 409


# ---- 4. legacy migration: marker + late rows ------------------------------

def test_legacy_rows_written_after_migration_arrive_once():
    with db.connect() as c:
        marker = int(db.get_state(c, chat._LEGACY_KEY))
        assert marker == max(r[0] for r in LEGACY)
    cur = sam.get("/api/chat/sync").get_json()["cursor"]
    post(alex, GEN, "a new-style message first")
    with db.connect() as c:
        before_max = c.execute("SELECT MAX(rev) FROM chat_messages").fetchone()[0]
        # An old container, mid-deploy, still writes to team_chat.
        c.execute("INSERT INTO team_chat (sender, body, created_at)"
                  " VALUES ('OldClient', 'from the old build', '2026-09-25T10:00:00Z')")
        c.commit()
        legacy_id = c.execute("SELECT MAX(id) FROM team_chat").fetchone()[0]
    for _ in range(2):                                    # twice: copied once
        chat._schema_done = False
        with db.connect() as c:
            chat.ensure_schema(c)
    with db.connect() as c:
        rows = c.execute("SELECT * FROM chat_messages WHERE body='from the old build'"
                         ).fetchall()
        assert int(db.get_state(c, chat._LEGACY_KEY)) == legacy_id
    assert len(rows) == 1
    row = rows[0]
    assert row["channel_id"] == GEN and row["legacy_sender"] == "OldClient"
    assert row["rev"] > before_max and row["user_id"] is None
    s = sam.get(f"/api/chat/sync?since={cur}").get_json()
    got = [x for x in s["messages"] if x["body"] == "from the old build"]
    assert len(got) == 1 and got[0]["sender"] == "OldClient" and got[0]["user"] is None


def test_first_migration_into_non_empty_table(tmp_path):
    """No marker yet but chat_messages already has rows (an earlier build
    copied with INSERT OR IGNORE): copy only what is missing, fresh ids."""
    import sqlite3
    conn = sqlite3.connect(tmp_path / "m.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);"
        "CREATE TABLE team_chat (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT,"
        " body TEXT, created_at TEXT);")
    conn.executemany("INSERT INTO team_chat VALUES (?,?,?,?)",
                     [(1, "A", "one", "t1"), (2, "B", "two", "t2"), (3, "C", "three", "t3")])
    conn.executescript(chat._SCHEMA)
    conn.execute("INSERT INTO chat_channels (slug,name,kind,created_at,updated_at)"
                 " VALUES ('general','general','general','t','t')")
    # Old build: copied 1 and 2, then a new message took id 3 before
    # team_chat row 3 was written (so OR IGNORE would have lost it).
    conn.execute("INSERT INTO chat_messages (id,channel_id,legacy_sender,body,rev,created_at)"
                 " VALUES (1,1,'A','one',1,'t1'),(2,1,'B','two',2,'t2')")
    conn.execute("INSERT INTO chat_messages (id,channel_id,user_id,body,rev,created_at)"
                 " VALUES (3,1,9,'new',3,'t9')")
    conn.commit()
    chat._migrate_legacy(conn)
    chat._migrate_legacy(conn)
    rows = conn.execute("SELECT id, legacy_sender, body, rev FROM chat_messages"
                        " ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [(1, "A", "one", 1), (2, "B", "two", 2),
                                        (3, None, "new", 3), (4, "C", "three", 4)]
    assert db.get_state(conn, chat._LEGACY_KEY) == "3"
    conn.close()


# ---- 5. explicit mentions from members ------------------------------------

def test_member_explicit_mentions_need_the_token():
    r = post(sam, GEN, "quiet message", mentions=[IDS["alex"], IDS["boss"]])
    assert r.status_code == 201 and r.get_json()["message"]["mentions"] == []
    r = post(sam, GEN, "ping @Big Boss and @alex", mentions=[IDS["alex"], IDS["boss"]])
    assert sorted(r.get_json()["message"]["mentions"]) == sorted([IDS["alex"], IDS["boss"]])
    r = post(sam, GEN, "@alexander", mentions=[IDS["alex"]])            # not a whole token
    assert r.get_json()["message"]["mentions"] == []
    r = post(boss, GEN, "admin quiet ping", mentions=[IDS["alex"]])     # admins: as sent
    assert r.get_json()["message"]["mentions"] == [IDS["alex"]]
    r = post(boss, GEN, "x", mentions=[IDS["alex"]] * 21)
    assert r.status_code == 400 and r.get_json()["error"] == "bad_mention"


# ---- 6. huge ids ----------------------------------------------------------

def test_huge_ids_are_not_500():
    huge = "9" * 25
    big = str(2 ** 63)
    for path in (f"/api/chat/channels/{huge}/messages", f"/api/chat/channels/{big}/messages"):
        assert sam.get(path).status_code == 404
        assert post(sam, huge, "x").status_code == 404
    assert sam.patch(f"/api/chat/messages/{huge}", json={"body": "x"}).status_code == 404
    assert sam.delete(f"/api/chat/messages/{big}").status_code == 404
    assert sam.delete(f"/api/chat/messages/{2 ** 63 - 1}").status_code == 404
    assert boss.patch(f"/api/chat/channels/{huge}", json={"name": "x"}).status_code == 404
    assert sam.post(f"/api/chat/channels/{huge}/read", json={"last_read_id": 1}).status_code == 404
    for q in (f"before={huge}", f"after={big}", f"before={big}"):
        assert sam.get(f"/api/chat/channels/{GEN}/messages?{q}").status_code == 400
    assert sam.get(f"/api/chat/channels/{GEN}/messages?after={2 ** 63 - 1}").status_code == 200
    assert sam.get(f"/api/chat/sync?since={big}").status_code == 400
    assert sam.post(f"/api/chat/channels/{GEN}/read",
                    json={"last_read_id": 2 ** 64}).status_code == 400
    assert sam.post(f"/api/chat/channels/{GEN}/read",
                    json={"last_read_id": int(huge)}).status_code == 400
    assert post(sam, GEN, "x", mentions=[2 ** 64]).status_code == 400


# ---- 7. invisible / bidi characters ---------------------------------------

def test_invisible_characters_stripped():
    family = "\U0001F468‍\U0001F469‍\U0001F467"
    body = ("a‮b⁦c⁩‎d‏e؜f​g⁠h﻿i"
            "\u0085j\u009fk l m " + family)
    r = post(sam, GEN, body)
    assert r.status_code == 201
    assert r.get_json()["message"]["body"] == "abcdefghijk\nl\nm " + family
    assert post(sam, GEN, "‍ ​‮").get_json()["error"] == "empty_message"
    r = post(sam, GEN, "", attachments=[{"type": "link", "url": "https://e.com",
                                         "title": "safe‮‍txt.exe x"}])
    assert r.get_json()["message"]["attachments"][0]["title"] == "safetxt.exe x"
    r = boss.post("/api/chat/channels", json={"name": "de‮als‍ two"})
    assert r.status_code == 201 and r.get_json()["channel"]["name"] == "deals two"


def test_caption_stripped(monkeypatch):
    monkeypatch.setattr(chat, "media_lookup", lambda ids: {
        7: {"name": "k‮.jpg", "kind": "photo", "thumb": "/t/7.jpg", "caption": None}})
    r = post(boss, GEN, "", attachments=[{"type": "media", "id": 7,
                                          "caption": "the‍ ‮kitchen"}])
    att = r.get_json()["message"]["attachments"][0]
    assert att["caption"] == "the kitchen" and att["name"] == "k.jpg"


# ---- 8. one admin rule ----------------------------------------------------

def test_admin_rule_is_the_admin_privilege():
    row = lambda role, privs: {"role": role, "privileges": privs}   # noqa: E731
    assert chat.is_admin_account(row("owner", "[]"))
    assert chat.is_admin_account(row("admin", "[]"))
    assert chat.is_admin_account(row("member", '["admin"]'))       # as team._actor sees it
    assert not chat.is_admin_account(row("member", '["leads","media"]'))
    assert not chat.is_admin_account(None)


def test_user_patch_strips_admin_from_members():
    with db.connect() as c:
        c.execute("INSERT INTO users (username, display_name, role, privileges, created_at)"
                  " VALUES ('tick', 'Tick Box', 'member', '[]', ?)", (auth._now(),))
        c.commit()
        uid = c.execute("SELECT id FROM users WHERE username='tick'").fetchone()[0]
    r = owner.patch(f"/api/users/{uid}", json={"privileges": ["admin", "leads"]})
    assert r.status_code == 200, r.get_json()
    assert "admin" not in r.get_json()["granted"] and "leads" in r.get_json()["granted"]
    r = owner.patch(f"/api/users/{uid}", json={"role": "admin"})
    assert r.status_code == 200 and "admin" in r.get_json()["privileges"]
    with db.connect() as c:                  # legacy data: an admin tick on the row
        c.execute("UPDATE users SET privileges='[\"admin\",\"crawl\"]' WHERE id=?", (uid,))
        c.commit()
    r = owner.patch(f"/api/users/{uid}", json={"role": "member"})
    assert r.status_code == 200
    assert r.get_json()["granted"] == ["crawl"] and "admin" not in r.get_json()["privileges"]


# ---- 9. documented: see test_discuss_reopens_archived_property_channel ----

# ---- 10. edits / deletes in archived channels -----------------------------

def test_edit_delete_in_archived_channel():
    cid = new_topic("frozen")
    m = post(sam, cid, "before the freeze").get_json()["message"]
    boss.patch(f"/api/chat/channels/{cid}", json={"archived": True})
    for c in (sam, boss):
        r = c.patch(f"/api/chat/messages/{m['id']}", json={"body": "changed"})
        assert r.status_code == 409 and r.get_json()["error"] == "archived"
        r = c.delete(f"/api/chat/messages/{m['id']}")
        assert r.status_code == 409 and r.get_json()["error"] == "archived"
    boss.patch(f"/api/chat/channels/{cid}", json={"archived": False})
    assert sam.patch(f"/api/chat/messages/{m['id']}", json={"body": "ok"}).status_code == 200


# ---- 11. channel names ----------------------------------------------------

def test_channel_name_types_and_slugs(monkeypatch):
    for bad in (123, ["x"], {"a": 1}, True):
        assert boss.post("/api/chat/channels", json={"name": bad}).status_code == 400
    cid = new_topic("renamable")
    assert boss.patch(f"/api/chat/channels/{cid}", json={"name": 5}).status_code == 400
    a = boss.post("/api/chat/channels", json={"name": "Сделки"})
    b = boss.post("/api/chat/channels", json={"name": "Продажи"})
    c = boss.post("/api/chat/channels", json={"name": "販売"})
    assert (a.status_code, b.status_code, c.status_code) == (201, 201, 201)
    slugs = [x.get_json()["channel"]["slug"] for x in (a, b, c)]
    assert slugs[0] == "channel" and slugs[1] == "channel-2" and slugs[2] == "channel-3"
    r = boss.post("/api/chat/channels", json={"name": "СДЕЛКИ"})       # Unicode case-fold
    assert r.status_code == 409 and r.get_json()["error"] == "name_taken"
    r = boss.patch(f"/api/chat/channels/{cid}", json={"name": "сделки"})
    assert r.status_code == 409
    assert boss.patch(f"/api/chat/channels/{cid}", json={"name": "RENAMABLE"}).status_code == 200
    # The UNIQUE lower(name) index catches what slips past the check (a race).
    monkeypatch.setattr(chat, "_name_taken", lambda *a, **k: False)
    r = boss.post("/api/chat/channels", json={"name": "renamable"})
    assert r.status_code == 409 and r.get_json()["error"] == "name_taken"
    r = boss.patch(f"/api/chat/channels/{a.get_json()['channel']['id']}",
                   json={"name": "Renamable"})
    assert r.status_code == 409 and r.get_json()["error"] == "name_taken"
    # Property channels may share a name (two listings, one address).
    with db.connect() as conn:
        idx = conn.execute("SELECT sql FROM sqlite_master WHERE name='idx_chat_channels_name'"
                           ).fetchone()[0]
    assert "kind != 'property'" in idx


# ---- 12. client_id retry --------------------------------------------------

def test_client_id_retry_rules():
    cid = new_topic("cid-home")
    r1 = post(sam, cid, "once", client_id="cid-archived")
    assert r1.status_code == 201
    boss.patch(f"/api/chat/channels/{cid}", json={"archived": True})
    r2 = post(sam, cid, "once", client_id="cid-archived")       # retry still answers
    assert r2.status_code == 200 and r2.get_json()["message"]["id"] == r1.get_json()["message"]["id"]
    r3 = post(sam, GEN, "once", client_id="cid-archived")       # same id, other channel
    assert r3.status_code == 409 and r3.get_json()["error"] == "client_id_reused"
    assert post(sam, cid, "new", client_id="cid-fresh").status_code == 409   # archived


# ---- perf -----------------------------------------------------------------

def _plan(sql, params):
    with db.connect() as c:
        return " | ".join(r["detail"] for r in c.execute("EXPLAIN QUERY PLAN " + sql, params))


def test_mention_count_uses_range_index():
    plan = _plan("""SELECT c.id,
                  (SELECT COUNT(*) FROM chat_mentions x
                    WHERE x.user_id = :me AND x.channel_id = c.id
                      AND x.message_id > COALESCE(r.last_read_id, :base))
             FROM chat_channels c
             LEFT JOIN chat_reads r ON r.user_id = :me AND r.channel_id = c.id
            WHERE c.archived_at IS NULL""", {"me": 1, "base": 0})
    assert "idx_chat_mentions_user_chan (user_id=? AND channel_id=? AND message_id>?)" in plan, plan
    plan = _plan("DELETE FROM chat_mentions WHERE message_id=?", (1,))
    assert "idx_chat_mentions_message" in plan, plan


def test_mention_counts_still_right():
    cid = new_topic("ments")
    ids = [post(alex, cid, f"@sam n{i}").get_json()["message"]["id"] for i in range(3)]
    assert unread_of(sam, cid)["mentions"] == 3
    alex.delete(f"/api/chat/messages/{ids[2]}")
    assert unread_of(sam, cid)["mentions"] == 2
    r = sam.post(f"/api/chat/channels/{cid}/read", json={"last_read_id": ids[0]})
    assert unread_of(sam, cid)["mentions"] == 1
    total = sam.get("/api/chat/sync").get_json()["mentions"]
    assert total == r.get_json()["mentions"] == sum(
        c["mentions"] for c in sam.get("/api/chat/channels").get_json()["channels"])


def test_property_info_chunks():
    with db.connect() as c:
        got = chat.property_info(c, list(range(1000, 2300)) + [101, 102])
    assert set(got) == {101, 102} and got[101]["tier"] == "hot"


def test_baseline_is_one_committed_insert():
    with db.connect() as c:
        c.execute("INSERT INTO users (username, display_name, role, privileges, created_at)"
                  " VALUES ('basey', 'Base Y', 'member', '[]', ?)", (auth._now(),))
        c.commit()
    b = client_for("basey")
    assert b.get("/api/chat/sync").status_code == 200
    with db.connect() as c:
        uid = c.execute("SELECT id FROM users WHERE username='basey'").fetchone()[0]
        assert c.execute("SELECT COUNT(*) FROM chat_reads WHERE user_id=?",
                         (uid,)).fetchone()[0] == 1
        assert not c.in_transaction
