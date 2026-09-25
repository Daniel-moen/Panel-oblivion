"""End-to-end Playwright harness for the team chat (docs/CHAT.md).

Run from the worktree root (the server serves ui/build, so build first):

    cd ui && npm run build && cd .. && .venv/bin/python tests/chat_e2e.py

Flags: --only phone|ipad   run one viewport
       --headed            show the browsers
       --keep              leave the server running at the end and print its URL

What it does: copies ./prospects.db into a scratch DATA_DIR (the real data is
never touched), makes three accounts straight in the users table (tessa and
marco, members; boss, an admin), mints cookie sessions for them with
auth.create_session, starts `webapp.py` on a free loopback port, and drives two
browser contexts (A = tessa, B = marco) through the chat scenario on a phone
(390x844, touch, dpr 3) and an iPad (1024x768, touch). Every console error and
uncaught page error on either page fails the run. Screenshots land in
~/.mission-control/mia/briefs/0046-shots/. Exit code 0 only when every step
passed with zero console errors.

The server started here is stopped by its own PID (terminate, wait, kill) —
never by pattern.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")
SHOTS = os.path.expanduser("~/.mission-control/mia/briefs/0046-shots")
PASSWORD = "e2e-pass"
SECRET = "e2e-secret-" + os.urandom(6).hex()

OPEN_POLL_WAIT = 6500      # the open sheet polls every 4 s
CLOSED_POLL_WAIT = 35000   # the closed launcher polls every 30 s
T = 10000                  # default UI wait

# ----------------------------------------------------------------- reporting

results: list[tuple[str, bool, str]] = []


def log(msg):
    print(msg, flush=True)


class Step:
    """`with Step("phone", "A opens chat"):` — records PASS/FAIL, never raises
    (so one broken step does not hide the rest), and screenshots both pages on
    a failure."""

    pages: list = []

    def __init__(self, vp, name, required=True):
        self.label = f"[{vp}] {name}"
        self.vp = vp
        self.ok = False

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is None:
            self.ok = True
            results.append((self.label, True, ""))
            log(f"PASS {self.label}")
            return False
        msg = f"{et.__name__}: {str(ev).strip().splitlines()[0] if str(ev).strip() else ''}"
        if not isinstance(ev, AssertionError) and "Timeout" not in et.__name__:
            msg += "\n" + "".join(traceback.format_tb(tb)[-2:])
        slug = re.sub(r"[^a-z0-9]+", "-", self.label.lower()).strip("-")
        shots = []
        for who, page in Step.pages:
            try:
                p = os.path.join(SHOTS, f"FAIL-{slug}-{who}.png")
                page.screenshot(path=p)
                shots.append(p)
            except Exception:       # noqa: BLE001
                pass
        results.append((self.label, False, msg + (f"\n  shots: {', '.join(shots)}" if shots else "")))
        log(f"FAIL {self.label}\n  {msg}" + (f"\n  shots: {', '.join(shots)}" if shots else ""))
        return True                # swallow: keep going


# ------------------------------------------------------------------ plumbing


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def base_env(data_dir, media_root):
    env = dict(os.environ)
    for k in ("PORT", "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "DB_PATH", "CACHE_DIR"):
        env.pop(k, None)
    env.update(DATA_DIR=data_dir, MEDIA_ROOT=media_root, DASHBOARD_USER="owner",
               DASHBOARD_PASSWORD=PASSWORD, DASHBOARD_SECRET=SECRET, AUTO_CRAWL="0",
               PYTHONUNBUFFERED="1")
    return env


SETUP = r"""
import json, os, sys
sys.path.insert(0, os.getcwd())
import auth, db
now = auth._now()
with db.connect() as conn:
    auth.ensure_schema(conn)
    for u, name, role, privs in (("tessa", "Tessa Brand", "member", '["leads","media","crawl"]'),
                                 ("marco", "Marco Rossi", "member", '["leads","media","crawl"]'),
                                 ("boss", "Boss Admin", "admin", '["leads","media","crawl","admin"]')):
        conn.execute("INSERT OR IGNORE INTO users (username, display_name, role, privileges,"
                     " created_at) VALUES (?,?,?,?,?)", (u, name, role, privs, now))
    conn.commit()
print(json.dumps({u: auth.create_session(u, "e2e/" + u) for u in ("tessa", "marco", "boss")}))
"""


class Server:
    def __init__(self, env, port, logpath):
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self.logf = open(logpath, "w")
        self.logpath = logpath
        # Not `python webapp.py`: that needs $PORT, and $PORT flips the app
        # into hosted mode (binds 0.0.0.0). Import it and bind loopback.
        code = ("import webapp; webapp.app.run(host='127.0.0.1', port=%d,"
                " debug=False, threaded=True)" % port)
        self.proc = subprocess.Popen([PY, "-c", code], cwd=ROOT, env=env,
                                     stdout=self.logf, stderr=subprocess.STDOUT)
        self.pid = self.proc.pid
        atexit.register(self.stop)

    def stop(self):
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)       # this PID only
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self.proc = None
        self.logf.close()

    def tail(self, n=40):
        try:
            with open(self.logpath) as f:
                return "".join(f.readlines()[-n:])
        except OSError:
            return ""


def api(base, token, method, path, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Cookie", f"oblivion_session={token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw[:300]


# ---------------------------------------------------------------- UI helpers

def tid(page, name):
    return page.get_by_test_id(name)


def sheet(page):
    return tid(page, "chat-sheet")


def launcher(page):
    return tid(page, "chat-launcher").locator("visible=true").first


def open_chat(page):
    if sheet(page).is_visible():
        return
    launcher(page).click()
    sheet(page).wait_for(state="visible", timeout=T)


def close_chat(page):
    if not sheet(page).is_visible():
        return
    tid(page, "chat-close").locator("visible=true").first.click()
    sheet(page).wait_for(state="hidden", timeout=T)


def channel_row(page, slug):
    return sheet(page).locator(f'[data-testid="chat-channel"][data-slug="{slug}"]')


def show_channel_list(page):
    """On a narrow sheet the channel list may be its own view behind a back
    button; make it visible if it is not."""
    rows = sheet(page).get_by_test_id("chat-channel")
    if rows.locator("visible=true").count():
        return
    for sel in ('[data-testid="chat-channels-toggle"]', '[data-testid="chat-back"]',
                'button[aria-label*="hannel" i]', 'button[aria-label*="back" i]'):
        b = sheet(page).locator(sel).locator("visible=true")
        if b.count():
            b.first.click()
            rows.locator("visible=true").first.wait_for(timeout=T)
            return
    rows.locator("visible=true").first.wait_for(timeout=T)


def select_channel(page, slug):
    show_channel_list(page)
    row = channel_row(page, slug)
    row.click()
    # the composer / thread of that channel is what matters
    tid(page, "chat-input").locator("visible=true").first.wait_for(timeout=T)


def is_current(row):
    return row.evaluate("""el => el.getAttribute('aria-current') === 'true'
        || el.getAttribute('aria-current') === 'page'
        || el.getAttribute('aria-selected') === 'true'
        || el.dataset.active === 'true' || el.classList.contains('active')
        || el.classList.contains('on')""")


def composer(page):
    return tid(page, "chat-input").locator("visible=true").first


def send(page, text):
    box = composer(page)
    box.fill(text)
    tid(page, "chat-send").locator("visible=true").first.click()


def msg(page, text):
    return sheet(page).get_by_test_id("chat-msg").filter(has_text=text)


def shot(page, name):
    page.screenshot(path=os.path.join(SHOTS, name))


# ------------------------------------------------------------------ scenario

def assert_property_channel(page, server, token, gid):
    """The open sheet is on the property channel for `gid`: the channel exists
    server-side (kind property) and its row, when the list shows, is current."""
    from playwright.sync_api import expect
    st, body = api(server.url, token, "GET", "/api/chat/channels")
    assert st == 200, (st, body)
    pch = [c for c in body["channels"] if c.get("kind") == "property"
           and str(c.get("property_gid")) == str(gid)]
    assert pch, "no property channel for gid %s in /api/chat/channels" % gid
    prow = sheet(page).locator(f'[data-testid="chat-channel"][data-id="{pch[0]["id"]}"]')
    expect(prow).to_have_count(1)
    slug = prow.first.get_attribute("data-slug") or ""
    assert slug.startswith("p-") or pch[0]["kind"] == "property", slug
    if prow.first.is_visible():
        assert is_current(prow.first), "property channel row is not the current one"


def run_viewport(pw, vp, server, tokens, prop, topic, headed):
    from playwright.sync_api import expect

    expect.set_options(timeout=T)
    if vp == "phone":
        ctx_opts = dict(viewport={"width": 390, "height": 844}, is_mobile=True,
                        has_touch=True, device_scale_factor=3)
    else:
        ctx_opts = dict(viewport={"width": 1024, "height": 768}, has_touch=True,
                        device_scale_factor=2)
    browser = pw.chromium.launch(headless=not headed)
    errors: list[str] = []
    pages = {}
    for who, user in (("A", "tessa"), ("B", "marco")):
        ctx = browser.new_context(**ctx_opts)
        ctx.add_cookies([{"name": "oblivion_session", "value": tokens[user],
                          "url": server.url}])
        page = ctx.new_page()
        page.set_default_timeout(T)
        page.on("console", lambda m, w=who: m.type == "error" and errors.append(
            f"{w} console.error: {m.text} @ {m.location.get('url', '')}:{m.location.get('lineNumber', '')}"))
        page.on("pageerror", lambda e, w=who: errors.append(f"{w} pageerror: {e}"))
        page.on("dialog", lambda d: d.accept())
        pages[who] = page
    A, B = pages["A"], pages["B"]
    Step.pages = [("A", A), ("B", B)]
    tag = f"{vp}-{int(time.time()) % 100000}"
    state = {}
    drawer = B.locator('aside[role="dialog"][aria-label="Property detail"]')
    gid = prop["gid"]

    with Step(vp, "pages load, launcher visible (A on /, B on /prospects)"):
        A.goto(server.url + "/")
        B.goto(server.url + "/prospects")
        expect(launcher(A)).to_be_visible()
        expect(launcher(B)).to_be_visible()

    with Step(vp, "A opens chat: sheet visible, #general selected"):
        open_chat(A)
        expect(sheet(A)).to_be_visible()
        expect(composer(A)).to_be_visible()
        gen = channel_row(A, "general")
        expect(gen).to_have_count(1)
        # the sheet opens on #general: either its row is marked current, or
        # the sheet header names it
        if not is_current(gen):
            expect(sheet(A)).to_contain_text("general")
        shot(A, f"{vp}-A-general.png")

    with Step(vp, "B opens then closes chat (sets its baseline)"):
        open_chat(B)
        expect(composer(B)).to_be_visible()
        close_chat(B)
        expect(tid(B, "chat-badge").locator("visible=true")).to_have_count(0)

    hello = f"hello from tessa {tag}"
    with Step(vp, "A sends a message; it renders as mine"):
        send(A, hello)
        m = msg(A, hello)
        expect(m).to_have_count(1)
        expect(m).to_have_attribute("data-mine", "true")
        expect(composer(A)).to_have_value("")

    with Step(vp, "B (closed) gets the launcher badge within one closed poll (<=35 s)"):
        badge = tid(B, "chat-badge").locator("visible=true")
        expect(badge).to_have_count(1, timeout=CLOSED_POLL_WAIT)
        kind = badge.first.get_attribute("data-kind")
        assert kind == "plain", f"badge data-kind={kind!r}, expected 'plain'"
        shot(B, f"{vp}-B-badge.png")

    with Step(vp, "B opens: A's message is there, not mine; badge clears"):
        open_chat(B)
        m = msg(B, hello)
        expect(m).to_have_count(1)
        expect(m).to_have_attribute("data-mine", "false")
        close_chat(B)
        expect(tid(B, "chat-badge").locator("visible=true")).to_have_count(0)
        open_chat(B)

    live = f"live while open {tag}"
    with Step(vp, "B with sheet open receives A's next message within ~6 s"):
        send(A, live)
        expect(msg(B, live)).to_have_count(1, timeout=OPEN_POLL_WAIT)
        shot(B, f"{vp}-B-general.png")

    # ---- channels
    with Step(vp, "channel switch: A moves general -> topic -> general"):
        select_channel(A, topic["slug"])
        row = channel_row(A, topic["slug"])
        if not is_current(row):
            expect(sheet(A)).to_contain_text(topic["name"])
        expect(msg(A, hello)).to_have_count(0)
        shot(A, f"{vp}-A-channels.png")

    in_topic = f"over in the topic {tag}"
    with Step(vp, "B (on #general) sees an unread badge on the topic row"):
        send(A, in_topic)
        expect(msg(A, in_topic)).to_have_count(1)
        show_channel_list(B)
        unread = channel_row(B, topic["slug"]).get_by_test_id("chat-channel-unread")
        expect(unread).to_be_visible(timeout=OPEN_POLL_WAIT)
        shot(B, f"{vp}-B-channel-unread.png")

    with Step(vp, "B opens the topic: message there, row unread clears"):
        select_channel(B, topic["slug"])
        expect(msg(B, in_topic)).to_have_count(1)
        show_channel_list(B)
        expect(channel_row(B, topic["slug"]).get_by_test_id("chat-channel-unread")).to_have_count(0)
        select_channel(B, "general")
        select_channel(A, "general")
        expect(msg(A, hello)).to_have_count(1)

    # ---- @ mention
    with Step(vp, "B closes its sheet"):
        close_chat(B)

    with Step(vp, "@ picker: '@mar' offers marco and inserts him"):
        box = composer(A)
        box.click()
        box.fill("")
        box.type("ping @mar", delay=40)
        people = tid(A, "chat-people")
        expect(people).to_be_visible()
        person = people.locator('[data-testid="chat-person"][data-username="marco"]')
        expect(person).to_have_count(1)
        shot(A, f"{vp}-composer-picker.png")
        if vp == "phone":
            person.tap()
        else:
            sel = person.get_attribute("aria-selected")
            if sel != "true":
                box.press("ArrowDown")
                if person.get_attribute("aria-selected") != "true":
                    # ArrowDown may have moved past a pre-highlighted first row
                    box.press("ArrowUp")
            box.press("Enter")
        expect(people).to_be_hidden()
        val = box.input_value()
        assert re.search(r"@(marco|Marco Rossi)\b", val), f"composer after pick: {val!r}"
        assert "@mar " not in val and not val.endswith("@mar"), f"partial left behind: {val!r}"

    mention_txt = f"can you take this {tag}"
    with Step(vp, "A sends the mention; A's own message has chat-mention data-me=false"):
        box = composer(A)
        box.press("End")
        box.type(mention_txt)
        tid(A, "chat-send").locator("visible=true").first.click()
        m = msg(A, mention_txt)
        expect(m).to_have_count(1)
        expect(m.get_by_test_id("chat-mention").first).to_have_attribute("data-me", "false")

    with Step(vp, "B (closed) launcher badge has data-kind=mention (<=35 s)"):
        badge = tid(B, "chat-badge").locator("visible=true")
        expect(badge).to_have_count(1, timeout=CLOSED_POLL_WAIT)
        expect(badge.first).to_have_attribute("data-kind", "mention", timeout=T)
        shot(B, f"{vp}-B-mention-badge.png")

    with Step(vp, "B opens: the mention is highlighted with data-me=true"):
        open_chat(B)
        m = msg(B, mention_txt)
        expect(m).to_have_count(1)
        men = m.get_by_test_id("chat-mention")
        expect(men.first).to_have_attribute("data-me", "true")
        m.scroll_into_view_if_needed()
        shot(B, f"{vp}-B-mention.png")

    # ---- attachments
    att_txt = f"see this one {tag}"
    with Step(vp, "A attaches a property via PropertyPick"):
        tid(A, "chat-attach").locator("visible=true").first.click()
        tid(A, "chat-attach-opt-property").locator("visible=true").first.click()
        search = sheet(A).locator('input[type="search"]').locator("visible=true").first
        search.fill(prop["query"])
        opt = sheet(A).get_by_role("option").filter(has_text=prop["label"][:20])
        expect(opt.first).to_be_visible()
        opt.first.click()
        expect(tid(A, "chat-draft-chip")).to_have_count(1)

    with Step(vp, "A attaches a link"):
        tid(A, "chat-attach").locator("visible=true").first.click()
        tid(A, "chat-attach-opt-link").locator("visible=true").first.click()
        tid(A, "chat-link-url").fill("https://example.com/x")
        tid(A, "chat-link-title").fill("Example X")
        tid(A, "chat-link-add").click()
        expect(tid(A, "chat-draft-chip")).to_have_count(2)
        shot(A, f"{vp}-A-drafts.png")

    with Step(vp, "A sends; both see chat-att-property and chat-att-link"):
        send(A, att_txt)
        for who, page, wait in (("A", A, T), ("B", B, OPEN_POLL_WAIT)):
            m = msg(page, att_txt)
            expect(m).to_have_count(1, timeout=wait)
            expect(m.get_by_test_id("chat-att-property")).to_have_count(1)
            expect(m.get_by_test_id("chat-att-link")).to_have_count(1)
        expect(tid(A, "chat-draft-chip")).to_have_count(0)
        msg(B, att_txt).scroll_into_view_if_needed()
        shot(A, f"{vp}-A-attachments.png")
        shot(B, f"{vp}-B-attachments.png")

    with Step(vp, "link attachment opens in a new tab safely"):
        link = msg(B, att_txt).get_by_test_id("chat-att-link")
        a = link if link.evaluate("el => el.tagName") == "A" else link.locator("a").first
        assert a.get_attribute("href") == "https://example.com/x", a.get_attribute("href")
        assert a.get_attribute("target") == "_blank", a.get_attribute("target")
        rel = a.get_attribute("rel") or ""
        assert "noopener" in rel, f"rel={rel!r}"
        expect(link).to_contain_text("Example X")

    with Step(vp, "B taps the property: drawer opens or /leads/properties/<gid>"):
        card = msg(B, att_txt).get_by_test_id("chat-att-property")
        expect(card).to_contain_text(prop["label"][:12])
        if vp == "phone":
            card.tap()
        else:
            card.click()
        prop_url = re.compile(rf"/leads/properties/{gid}(\b|/|\?|$)")
        deadline = time.time() + T / 1000
        outcome = None
        while time.time() < deadline and not outcome:
            if drawer.is_visible():
                outcome = "drawer"
            elif prop_url.search(B.url):
                outcome = "page"
            else:
                B.wait_for_timeout(150)
        assert outcome, f"neither drawer nor property page; url={B.url}"
        if outcome == "page":
            B.wait_for_load_state("networkidle")
            expect(tid(B, "discuss-property").locator("visible=true")).to_have_count(1)
        shot(B, f"{vp}-B-property-{outcome}.png")
        log(f"     property tap -> {outcome}")
        state["prop_outcome"] = outcome

    if state.get("prop_outcome") == "drawer":
        with Step(vp, "Discuss in the drawer opens the property channel with a draft chip"):
            btn = drawer.get_by_test_id("discuss-property").locator("visible=true")
            expect(btn).to_have_count(1)
            btn.first.click()
            expect(sheet(B)).to_be_visible()
            expect(tid(B, "chat-draft-chip").locator("visible=true")).to_have_count(1)
            assert_property_channel(B, server, tokens["marco"], gid)
            shot(B, f"{vp}-B-discuss-drawer.png")

    with Step(vp, "B back on /prospects with the chat on #general"):
        if drawer.is_visible():
            B.keyboard.press("Escape")
        if sheet(B).is_visible() and drawer.is_visible():
            close_chat(B)
            B.keyboard.press("Escape")
        expect(drawer).to_be_hidden()
        if "/prospects" not in B.url:
            B.go_back()
            B.wait_for_url(re.compile(r"/prospects"))
        open_chat(B)
        select_channel(B, "general")
        expect(msg(B, live)).to_have_count(1)

    # ---- edit / delete
    edited = f"edited text {tag}"
    with Step(vp, "A edits its message; B sees new text + (edited)"):
        m = msg(A, live)
        m.scroll_into_view_if_needed()
        acts = m.get_by_test_id("chat-msg-actions")
        if not acts.is_visible():
            m.get_by_test_id("chat-msg-body").click()
        acts.click()
        tid(A, "chat-msg-edit").locator("visible=true").first.click()
        inp = tid(A, "chat-edit-input")
        expect(inp).to_be_visible()
        inp.fill(edited)
        tid(A, "chat-edit-save").click()
        expect(msg(A, edited)).to_have_count(1)
        b = msg(B, edited)
        expect(b).to_have_count(1, timeout=OPEN_POLL_WAIT)
        expect(b).to_contain_text("(edited)")
        expect(msg(B, live)).to_have_count(0)
        b.scroll_into_view_if_needed()
        shot(B, f"{vp}-B-edited.png")

    with Step(vp, "A deletes it; B sees it gone / 'Message deleted'"):
        m = msg(A, edited)
        mid = m.first.get_attribute("data-id")
        acts = m.get_by_test_id("chat-msg-actions")
        if not acts.is_visible():
            m.get_by_test_id("chat-msg-body").click()
        acts.click()
        tid(A, "chat-msg-delete").locator("visible=true").first.click()
        # a confirm step inside the sheet, if there is one (window.confirm is
        # auto-accepted by the dialog handler)
        conf = sheet(A).get_by_role("button", name=re.compile(r"^delete$", re.I)).locator("visible=true")
        try:
            conf.first.wait_for(timeout=1200)
            conf.first.click()
        except Exception:       # noqa: BLE001
            pass
        expect(msg(A, edited)).to_have_count(0)
        expect(msg(B, edited)).to_have_count(0, timeout=OPEN_POLL_WAIT)
        gone = sheet(B).locator(f'[data-testid="chat-msg"][data-id="{mid}"]')
        if gone.count():
            expect(gone.get_by_test_id("chat-msg-body")).to_have_text("Message deleted")
        shot(B, f"{vp}-B-deleted.png")

    # ---- Discuss on the property page
    with Step(vp, "Discuss on /leads/properties/<gid> opens a property channel with a draft chip"):
        close_chat(A)
        A.goto(f"{server.url}/leads/properties/{gid}")
        btn = tid(A, "discuss-property").locator("visible=true").first
        expect(btn).to_be_visible(timeout=15000)
        btn.click()
        expect(sheet(A)).to_be_visible()
        expect(tid(A, "chat-draft-chip").locator("visible=true")).to_have_count(1)
        assert_property_channel(A, server, tokens["tessa"], gid)
        shot(A, f"{vp}-A-discuss.png")

    with Step(vp, f"zero console errors on both pages ({len(errors)})"):
        assert not errors, "\n    " + "\n    ".join(errors[:40])

    browser.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", choices=("phone", "ipad"))
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(os.path.join(ROOT, "ui", "build", "index.html")):
        sys.exit("ui/build is missing — run `cd ui && npm run build` first.")
    os.makedirs(SHOTS, exist_ok=True)

    data_dir = tempfile.mkdtemp(prefix="chat-e2e-")
    media_root = tempfile.mkdtemp(prefix="chat-e2e-media-")
    shutil.copy2(os.path.join(ROOT, "prospects.db"), os.path.join(data_dir, "prospects.db"))
    env = base_env(data_dir, media_root)
    log(f"DATA_DIR {data_dir}")

    out = subprocess.run([PY, "-c", SETUP], cwd=ROOT, env=env, capture_output=True,
                         text=True, timeout=120)
    if out.returncode:
        sys.exit("account setup failed:\n" + out.stderr[-3000:])
    tokens = json.loads(out.stdout.strip().splitlines()[-1])

    port = free_port()
    server = Server(env, port, os.path.join(data_dir, "server.log"))
    log(f"server pid {server.pid} on {server.url}")
    try:
        deadline = time.time() + 120
        while True:
            if server.proc.poll() is not None:
                sys.exit("server exited during boot:\n" + server.tail())
            try:
                st, _ = api(server.url, tokens["tessa"], "GET", "/api/me", timeout=3)
                if st == 200:
                    break
            except OSError:
                pass
            if time.time() > deadline:
                sys.exit("server not ready in 120 s:\n" + server.tail())
            time.sleep(0.5)

        # ---- fixtures over the API
        st, chans = api(server.url, tokens["tessa"], "GET", "/api/chat/channels")
        if st != 200:
            sys.exit(f"/api/chat/channels answered {st}: {chans}\n{server.tail()}")
        prop = pick_property(server, tokens)
        log(f"property gid {prop['gid']}: {prop['label']} (search {prop['query']!r})")
        # /leads/properties/<gid> is the tracked-lead page (an untracked gid
        # renders "not found"), so track it for the Discuss step.
        st, body = api(server.url, tokens["tessa"], "POST", "/api/tracked", {"group_id": prop["gid"]})
        if st not in (200, 201):
            sys.exit(f"could not track gid {prop['gid']}: {st} {body}")

        vps = [args.only] if args.only else ["phone", "ipad"]
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            for vp in vps:
                name = f"Deals {vp} {int(time.time()) % 100000}"
                st, body = api(server.url, tokens["boss"], "POST", "/api/chat/channels", {"name": name})
                ok = st == 201 and body and "channel" in body or (st == 201 and body and "slug" in body)
                with Step(vp, "admin creates a topic channel (POST /api/chat/channels)"):
                    assert ok, (st, body)
                    st2, _ = api(server.url, tokens["tessa"], "POST", "/api/chat/channels",
                                 {"name": name + " member"})
                    assert st2 == 403, f"member topic create answered {st2}, expected 403"
                ch = body.get("channel", body) if isinstance(body, dict) else {}
                topic = {"id": ch.get("id"), "slug": ch.get("slug"), "name": ch.get("name", name)}
                run_viewport(pw, vp, server, tokens, prop, topic, args.headed)

        if args.keep:
            log(f"\n--keep: server still running at {server.url} (pid {server.pid})")
            for u in ("tessa", "marco", "boss"):
                log(f"  cookie oblivion_session for {u}: {tokens[u]}")
            atexit.unregister(server.stop)
    finally:
        if not args.keep:
            server.stop()

    failed = [r for r in results if not r[1]]
    log("\n==== summary ====")
    for label, ok, msg in results:
        log(f"{'PASS' if ok else 'FAIL'} {label}")
    log(f"\n{len(results) - len(failed)}/{len(results)} passed; screenshots in {SHOTS}")
    if server.proc is None:
        if failed:
            log(f"server log: {server.logpath} (scratch DATA_DIR kept for inspection)")
        else:
            # a copy of prospects.db is ~150 MB: do not leave one per run
            shutil.rmtree(data_dir, ignore_errors=True)
            shutil.rmtree(media_root, ignore_errors=True)
    sys.exit(1 if failed else 0)


def pick_property(server, tokens):
    """A for-sale group with a street address, that is in the prospect list
    (so the drawer can open) and that the PropertyPick search finds."""
    st, rows = api(server.url, tokens["tessa"], "GET", "/api/prospects", timeout=120)
    if isinstance(rows, dict):
        rows = rows.get("prospects") or rows.get("rows") or []
    cands = []
    for r in rows or []:
        gid = r.get("group_id")
        addr = (r.get("street_address_raw") or r.get("street_address") or "").strip()
        if gid is None or not re.search(r"\d+\s+\w{3,}", addr):
            continue
        cands.append((str(gid), addr))
    for gid, addr in cands[:40]:
        st, res = api(server.url, tokens["tessa"], "GET",
                      "/api/team/properties?q=" + urllib.request.quote(addr))
        hits = [x for x in (res or {}).get("results", []) if str(x["group_id"]) == gid]
        if st == 200 and hits and len(res["results"]) <= 3:
            return {"gid": gid, "query": addr, "label": hits[0]["label"]}
    sys.exit(f"no usable property found (prospects: {len(rows or [])}, with address: {len(cands)})")


if __name__ == "__main__":
    main()
