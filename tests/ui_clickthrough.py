"""UI click-through: every route, three device shapes, every console error.

Plain script, no pytest. It boots the app itself, on a scratch DATA_DIR
holding a COPY of prospects.db, on a free loopback port, signs in through
the /login form, and drives headless Chromium (Playwright):

    .venv/bin/python tests/ui_clickthrough.py                    # checks only
    .venv/bin/python tests/ui_clickthrough.py --shots /tmp/shots --label before

Viewports: phone 390x844 (mobile, touch), iPad 1024x768 and 1180x820 (touch),
desktop 1440x900. Routes: / /prospects /leads /map /media /online /account.

On Home (`/`) it checks the photo-first scene's contract:
  - greeting h1[data-home-greeting] and sentence [data-home-line] get text,
    and neither box moves between first paint and 2 s after data lands (≤1px)
  - idle: no `.mg-pane` element and no visible `header.strip` (unless a crawl
    is running)
  - the native <select data-home-view> through needs/mandates/crawl/pipeline:
    the line has text every time and changes, the CTA [data-home-cta] has a label
  - Search round button → /prospects with [data-page-search] focused; back
  - Quick log round button → [data-quicklog-sheet] visible; Escape closes it
  - reveal chevron button[data-home-reveal] → [data-home-overview] in view with
    a visible .mg-stat-tile; scroll back to top → scrollY 0, scene back
Every other route: header.strip's Search and Quick log buttons do the same,
there is no left rail (no `aside.rail`, no fixed ~300px full-height element
at left:0) and the .mg-page column is horizontally centred.

The dock (task 0048: no rail; one floating pill at every width), per viewport:
  - nav[data-testid=dock] inside the viewport at opacity 1, on one row (tabs
    and the raised primary share a top within 2px, no overflow, ≤ vw-16 wide)
  - labels hidden < 900px, shown ≥ 900px (seven labelled tabs need ~800px); [dock-cma] present iff ≥ 1024px
  - Prospects → Leads: the highlight glides (intermediate positions seen) and
    settles within 3px of the Leads tab's centre; Leads gets aria-current
  - the raised primary opens the crawl sheet (data-action=crawl) or the Quick
    log (quicklog); Escape closes it
  - [account-btn] opens /account from /, /prospects and /leads
  - Home: the dock goes .quiet after the idle delay (every width)
  - reduced motion (a fresh context): a dock-tab route change, sampled every
    frame for ~600 ms, animates no transform anywhere (opacity only)

The chat launcher (sweep): on every route — the fixed ones plus each /leads
and /media sub-page found under ui/src/routes ([param] pages get a real id
from the API, or are skipped with a note) — exactly one [chat-launcher] a
person can see (box in the viewport, not hidden, no ancestor at opacity 0,
topmost at its centre by elementFromPoint); any [chat-badge] sits inside it;
clicking it opens the chat (check_chat). Home is checked again once the dock
has gone quiet. --no-dock / --no-chat-sweep skip these blocks.

Console errors and page errors are collected across the whole run. Ignored:
`net::ERR_ABORTED` (fetches cut short by navigation) and 404s for resources on
non-localhost hosts (map tiles, listing photos). Exit status is non-zero on any
failed check or any remaining console/page error.

The database is copied from --db (default: prospects.db next to this repo
checkout); the live ~/prospecting-auto/prospects.db is refused. The server is
stopped by its own PID (never a pattern kill); the scratch dir is removed.

ui_perf.py imports boot() / sign_in() from here.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_DB = os.path.realpath(os.path.expanduser("~/prospecting-auto/prospects.db"))
USER, PASS = "owner", "ui-check-pass"

VIEWPORTS = {
    "phone": dict(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True),
    "ipad": dict(viewport={"width": 1024, "height": 768}, has_touch=True),
    "ipad-l": dict(viewport={"width": 1180, "height": 820}, has_touch=True),
    "desktop": dict(viewport={"width": 1440, "height": 900}),
}
ROUTES = ["/", "/prospects", "/leads", "/map", "/media", "/online", "/account"]
VIEWS = ["needs", "mandates", "crawl", "pipeline"]
T = 6000  # ms, default wait for a contract selector
# zerko/ is vendored untracked; a worktree without it answers /api/media/* 503.
NO_MEDIA = not os.path.isdir(os.path.join(REPO, "zerko"))


# ---------------------------------------------------------------- the server

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def boot(db_src: str | None = None, quiet: bool = True):
    """Start webapp.py on a scratch DATA_DIR with a copy of the database.

    Yields the base URL. The PID is written to DATA_DIR/server.pid and the
    server is stopped with that PID only."""
    src = os.path.realpath(db_src or os.path.join(REPO, "prospects.db"))
    if src == LIVE_DB:
        sys.exit(f"refusing to use the live database {LIVE_DB}; pass a copy with --db")
    if not os.path.exists(src):
        sys.exit(f"no database at {src}; pass --db PATH (a copy, never the live one)")
    data = tempfile.mkdtemp(prefix="ui-check-")
    media = tempfile.mkdtemp(prefix="ui-check-media-")
    t0 = time.monotonic()
    shutil.copy2(src, os.path.join(data, "prospects.db"))
    for ext in ("-wal", "-shm"):
        if os.path.exists(src + ext):
            shutil.copy2(src + ext, os.path.join(data, "prospects.db" + ext))
    port = _free_port()
    env = {k: v for k, v in os.environ.items()
           if k not in ("CRAWL_SOURCES_PLUGIN", "PROSPECTS_NO_WARM", "DB_PATH", "PORT")}
    env.update(DATA_DIR=data, MEDIA_ROOT=media, PORT=str(port), AUTO_CRAWL="0",
               DASHBOARD_USER=USER, DASHBOARD_PASSWORD=PASS, PYTHONUNBUFFERED="1")
    log_path = os.path.join(data, "server.log")
    log = open(log_path, "w")
    proc = subprocess.Popen([sys.executable, os.path.join(REPO, "webapp.py")], cwd=REPO,
                            env=env, stdout=log, stderr=subprocess.STDOUT)
    with open(os.path.join(data, "server.pid"), "w") as f:
        f.write(str(proc.pid))
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 90
        while True:
            if proc.poll() is not None:
                log.flush()
                sys.exit(f"server exited early ({proc.returncode}); log:\n"
                         + open(log_path).read()[-3000:])
            try:
                urllib.request.urlopen(base + "/login", timeout=2).read()
                break
            except (urllib.error.URLError, OSError):
                if time.monotonic() > deadline:
                    sys.exit("server did not answer /login within 90 s")
                time.sleep(0.3)
        if not quiet:
            print(f"server up on {base} (pid {proc.pid}, DATA_DIR {data}) "
                  f"in {time.monotonic() - t0:.1f}s")
        yield base
    finally:
        with open(os.path.join(data, "server.pid")) as f:
            pid = int(f.read().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            proc.wait(timeout=10)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            os.kill(pid, signal.SIGKILL)
            proc.wait(timeout=5)
        log.close()
        if os.environ.get("UI_CHECK_KEEP"):
            print(f"kept scratch DATA_DIR {data}")
        else:
            shutil.rmtree(data, ignore_errors=True)
        shutil.rmtree(media, ignore_errors=True)


def sign_in(page, base: str) -> None:
    """The owner's password form (sets the session cookie for the context)."""
    page.goto(base + "/login", wait_until="domcontentloaded")
    page.fill("#pw", PASS)
    with page.expect_navigation(wait_until="domcontentloaded"):
        page.click("form[action='/login'] button[type=submit]")
    if "/login" in urlparse(page.url).path:
        sys.exit("sign-in failed (still on /login)")


def crawl_running(page, base: str) -> bool:
    try:
        return bool(page.context.request.get(base + "/api/status").json().get("running"))
    except Exception:                                   # noqa: BLE001
        return False


# ---------------------------------------------------------------- checks

failures: list[str] = []
errors: list[str] = []


def check(name: str, cond, extra: object = "") -> bool:
    print(("  ok   " if cond else "  FAIL ") + name + (f"  ({extra})" if extra and not cond else ""))
    if not cond:
        failures.append(name)
    return bool(cond)


def step(name: str, fn) -> None:
    """Run one interaction; a timeout or error fails it and the run carries on."""
    try:
        fn()
    except Exception as e:                              # noqa: BLE001
        msg = str(e).splitlines()[0][:200]
        check(name, False, f"{type(e).__name__}: {msg}")


def attach_console(page, where) -> None:
    def on_console(m):
        if m.type != "error":
            return
        text = m.text
        if "net::ERR_ABORTED" in text:
            return
        url = (m.location or {}).get("url") or ""
        host = urlparse(url).hostname or ""
        if "404" in text and host and host not in ("127.0.0.1", "localhost"):
            return
        if NO_MEDIA and "503" in text and "/api/media/" in url:
            return
        errors.append(f"{where()} {page.url}: {text}" + (f"  [{url}]" if url else ""))

    page.on("console", on_console)
    page.on("pageerror", lambda e: errors.append(f"{where()} {page.url}: PAGEERROR {e}"))


def route_name(path: str) -> str:
    return "home" if path == "/" else path.strip("/").replace("/", "-")


# Records the rects of the greeting and the line on the first frame they are
# both in the DOM (a MutationObserver from document start, then one rAF so
# layout has run). Home's "first paint" as far as the boxes are concerned.
FIRST_PAINT = """
(() => {
  const grab = () => {
    const h = document.querySelector('h1[data-home-greeting]');
    const l = document.querySelector('[data-home-line]');
    if (!h || !l || window.__homeFirst) return;
    window.__homeFirst = 'pending';
    requestAnimationFrame(() => {
      const r = (e) => { const b = e.getBoundingClientRect(); return {x: b.x, y: b.y + scrollY, w: b.width, h: b.height}; };
      window.__homeFirst = { h1: r(h), line: r(l), t: performance.now(),
                             h1Text: h.textContent.trim(), lineText: l.textContent.trim() };
    });
  };
  new MutationObserver(grab).observe(document, { childList: true, subtree: true });
})();
"""

RECTS = """() => {
  const r = (e) => { const b = e.getBoundingClientRect(); return {x: b.x, y: b.y + scrollY, w: b.width, h: b.height}; };
  return { h1: r(document.querySelector('h1[data-home-greeting]')),
           line: r(document.querySelector('[data-home-line]')) };
}"""


def focused_search(page) -> bool:
    return page.evaluate("() => !!document.activeElement && document.activeElement.matches('[data-page-search]')")


def wait_focused_search(page, timeout=T) -> None:
    page.wait_for_function(
        "() => !!document.activeElement && document.activeElement.matches('[data-page-search]')",
        timeout=timeout)


def check_quicklog(page, btn_sel: str, tag: str) -> None:
    sheet = "[data-quicklog-sheet]"

    def run():
        page.click(btn_sel, timeout=T)
        page.wait_for_selector(sheet, state="visible", timeout=T)
        check(f"{tag}: Quick log opens [data-quicklog-sheet]", True)
        page.keyboard.press("Escape")
        page.wait_for_selector(sheet, state="hidden", timeout=T)
        check(f"{tag}: Escape closes the Quick log sheet", True)

    step(f"{tag}: Quick log opens and Escape closes it", run)


def check_chat(page, btn_sel: str, tag: str, shot=None, frost=True) -> None:
    """Task 0047: the header's round chat button is the one chat entry point
    (no floating launcher). It opens the sheet over a page that still has its
    Frost pane, and closing it logs no console errors."""
    sheet = '[data-testid="chat-sheet"]'

    def run():
        before = len(errors)
        n = page.locator('[data-testid="chat-launcher"]').locator("visible=true").count()
        check(f"{tag}: exactly one visible chat button (no floating launcher)", n == 1, f"{n} visible")
        check(f"{tag}: no .launcher element in the DOM", page.locator("button.launcher").count() == 0)
        page.click(btn_sel, timeout=T)
        page.wait_for_selector(sheet, state="visible", timeout=T)
        check(f"{tag}: the header chat button opens [chat-sheet]", True)
        if frost:                           # /map has no pane by design
            bg = page.evaluate(
                "() => { const f = document.querySelector('.mg-frostclip .mg-frost');"
                " return f ? getComputedStyle(f).backgroundImage : null; }")
            check(f"{tag}: the Frost pane is present under the open sheet",
                  bool(bg) and bg != "none", bg)
        if shot:
            shot("-chat")
        page.wait_for_timeout(800)          # first sync lands while open
        page.click('[data-testid="chat-close"]', timeout=T)
        page.wait_for_selector(sheet, state="hidden", timeout=T)
        page.wait_for_timeout(500)
        check(f"{tag}: closing the sheet leaves no console errors", len(errors) == before,
              errors[before:])

    step(f"{tag}: chat opens from the header", run)


def check_home(page, base: str, vp: str, shot) -> None:
    tag = f"{vp} /"
    page.goto(base + "/", wait_until="domcontentloaded")

    # greeting + line get text; the boxes do not move once data lands
    def texts():
        page.wait_for_function(
            "() => { const h = document.querySelector('h1[data-home-greeting]'),"
            " l = document.querySelector('[data-home-line]');"
            " return h && l && h.textContent.trim() && l.textContent.trim(); }", timeout=10000)
        check(f"{tag}: greeting and line have text", True)
        first = page.evaluate("() => window.__homeFirst")
        page.wait_for_timeout(2000)
        after = page.evaluate(RECTS)
        if not isinstance(first, dict):
            check(f"{tag}: first-paint rects recorded", False, first)
            return
        moved = []
        # Tops and the greeting's height only: both boxes are centred and
        # shrink-wrapped, so their x/width follow the text by design.
        for el, keys in (("h1", ("y", "h")), ("line", ("y",))):
            for k in keys:
                d = abs(first[el][k] - after[el][k])
                if d > 1:
                    moved.append(f"{el}.{k} {first[el][k]:.1f}->{after[el][k]:.1f}")
        check(f"{tag}: greeting/line boxes steady from first paint to +2 s (≤1px)", not moved,
              "; ".join(moved))
        print(f"       first paint: h1 {first.get('h1Text')!r} / line {first.get('lineText')!r}")
        print(f"       after 2 s:   line {page.locator('[data-home-line]').first.inner_text().strip()!r}")

    step(f"{tag}: greeting and line get text", texts)
    shot(vp, "/")

    # the idle scene: no content pane, no strip (unless a crawl runs)
    running = crawl_running(page, base)
    check(f"{tag}: idle scene has no .mg-pane", page.locator(".mg-pane").count() == 0,
          f"{page.locator('.mg-pane').count()} found")
    if running:
        print("       (a crawl is running: header.strip allowed)")
    else:
        strip_vis = page.locator("header.strip").first.is_visible() if page.locator("header.strip").count() else False
        check(f"{tag}: idle scene shows no header.strip", not strip_vis)

    # the view dropdown
    def views():
        sel = page.locator("select[data-home-view]")
        sel.wait_for(state="attached", timeout=T)
        seen = {}
        for v in VIEWS:
            prev = page.locator("[data-home-line]").first.inner_text().strip()
            sel.select_option(v)
            # a change is expected unless the view happens to say the same thing
            with contextlib.suppress(Exception):
                page.wait_for_function(
                    "(p) => { const l = document.querySelector('[data-home-line]');"
                    " return l && l.textContent.trim() && l.textContent.trim() !== p; }",
                    arg=prev, timeout=2500)
            line = page.locator("[data-home-line]").first.inner_text().strip()
            cta = page.locator("[data-home-cta]").first
            label = cta.inner_text().strip() if cta.count() else ""
            label = label or (cta.get_attribute("aria-label") or "" if cta.count() else "")
            seen[v] = line
            check(f"{tag}: view {v!r} has a line", bool(line))
            check(f"{tag}: view {v!r} CTA has a label", bool(label))
            print(f"       {v:<9} {line!r} → [{label}]")
        check(f"{tag}: the line changes across the four views", len(set(seen.values())) > 1, seen)
        sel.select_option("needs")

    step(f"{tag}: view dropdown", views)

    # Search → /prospects with the search field focused
    def search():
        page.click('[data-home-scene] button[aria-label="Search"]', timeout=T)
        page.wait_for_url("**/prospects**", timeout=T)
        wait_focused_search(page)
        check(f"{tag}: Search lands on /prospects with [data-page-search] focused", True)
        page.go_back(wait_until="domcontentloaded")
        page.wait_for_selector("[data-home-scene]", timeout=T)
        check(f"{tag}: back returns to the scene", urlparse(page.url).path == "/")

    step(f"{tag}: Search round button", search)

    check_quicklog(page, '[data-home-scene] button[aria-label="Quick log"]', tag)
    check_chat(page, '[data-home-scene] [data-testid="chat-launcher"]', tag,
               lambda suffix: shot(vp, "/", suffix=suffix))

    # reveal → the overview pane, then back to the top
    def reveal():
        page.click("button[data-home-reveal]", timeout=T)
        page.wait_for_function(
            "() => { const o = document.querySelector('[data-home-overview]'); if (!o) return false;"
            " const b = o.getBoundingClientRect(); return b.top < innerHeight * 0.5 && b.top > -innerHeight && b.bottom > 0; }",
            timeout=4000)
        page.wait_for_timeout(700)  # let the smooth scroll settle
        info = page.evaluate(
            "() => { const o = document.querySelector('[data-home-overview]').getBoundingClientRect();"
            " const t = document.querySelector('[data-home-overview] .mg-stat-tile, .mg-stat-tile');"
            " const tb = t && t.getBoundingClientRect();"
            " return { scrollY, top: o.top, tile: !!t,"
            "   tileInView: !!tb && tb.width > 0 && tb.height > 0 && tb.top < innerHeight && tb.bottom > 0 }; }")
        check(f"{tag}: reveal brings [data-home-overview] into view", info["top"] < page.viewport_size["height"] * 0.5
              and info["scrollY"] > 0, info)
        check(f"{tag}: a .mg-stat-tile is visible in the overview", info["tileInView"], info)
        shot(vp, "/", suffix="-overview")
        page.evaluate("() => window.scrollTo({ top: 0, behavior: 'instant' })")
        page.wait_for_function("() => scrollY === 0", timeout=3000)
        page.wait_for_timeout(300)
        back = page.evaluate(
            "() => { const h = document.querySelector('h1[data-home-greeting]'); const b = h && h.getBoundingClientRect();"
            " return { scrollY, greetingInView: !!b && b.top >= 0 && b.bottom <= innerHeight }; }")
        check(f"{tag}: back at the top, scrollY 0 and the scene in view",
              back["scrollY"] == 0 and back["greetingInView"], back)

    step(f"{tag}: reveal chevron and back", reveal)


def check_route(page, base: str, vp: str, path: str, shot) -> None:
    tag = f"{vp} {path}"
    page.goto(base + path, wait_until="domcontentloaded")
    step(f"{tag}: header.strip present",
         lambda: page.wait_for_selector("header.strip", state="visible", timeout=T))
    page.wait_for_timeout(1500)
    shot(vp, path)
    check_no_rail(page, tag)

    def search():
        page.click('header.strip button[aria-label="Search"]', timeout=T)
        try:
            wait_focused_search(page)
        except Exception:                               # noqa: BLE001
            focus = page.evaluate("() => { const a = document.activeElement;"
                                  " return a ? a.outerHTML.slice(0, 120) : null; }")
            check(f"{tag}: header Search focuses [data-page-search]", False,
                  f"landed on {urlparse(page.url).path}, focused {focus}")
            return
        landed = urlparse(page.url).path
        check(f"{tag}: header Search focuses [data-page-search]"
              + ("" if landed == path else f" (moved to {landed})"), True)
        if landed != path:
            # Media has its own library search; everywhere else it is the
            # prospect filter box.
            want = "/media/search" if path.startswith("/media") else "/prospects"
            check(f"{tag}: a page without its own search sends Search to {want}",
                  landed.startswith(want), landed)
            page.goto(base + path, wait_until="domcontentloaded")
            page.wait_for_selector("header.strip", state="visible", timeout=T)
        else:
            page.keyboard.press("Escape")

    step(f"{tag}: header Search", search)
    check_quicklog(page, 'header.strip button[aria-label="Quick log"]', tag)
    check_chat(page, 'header.strip [data-testid="chat-launcher"]', tag,
               (lambda suffix: shot(vp, path, suffix=suffix)) if path == "/prospects" else None,
               frost=path != "/map")


# ---------------------------------------------------------------- the dock (task 0048)

DOCK = 'nav[data-testid="dock"]'
TAB = 'a[data-dock-item]'
HL = '[data-testid="dock-highlight"]'
PRIMARY = '[data-testid="dock-primary"]'
CMA = '[data-testid="dock-cma"]'
ACCOUNT = '[data-testid="account-btn"]'
CRAWL_SHEET = '[role="dialog"][aria-label="New crawl"]'
DOCK_TABS = ["/", "/prospects", "/agent", "/leads", "/map", "/media", "/online"]

# Old rail leftovers + the page column's horizontal centring, in one pass.
RAIL_PROBE = """() => {
  const vw = document.documentElement.clientWidth, vh = innerHeight;
  const fixedLeft = [];
  for (const e of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(e);
    if (cs.position !== 'fixed' || cs.display === 'none' || cs.visibility === 'hidden') continue;
    const b = e.getBoundingClientRect();
    if (Math.abs(b.left) <= 1 && b.width >= 260 && b.width <= 340 && b.height >= vh * 0.9)
      fixedLeft.push((e.tagName + '.' + [...e.classList].join('.')).slice(0, 80));
  }
  const m = document.querySelector('main.mg-page');
  let centre = null;
  if (m) {
    const b = m.getBoundingClientRect(), cs = getComputedStyle(m);
    const left = b.left + parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth);
    const right = vw - (b.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth));
    centre = { left: Math.round(left * 10) / 10, right: Math.round(right * 10) / 10 };
  }
  return { rails: document.querySelectorAll('aside.rail').length, fixedLeft, centre };
}"""

DOCK_PROBE = """([dock, tab, primary, cma]) => {
  const n = document.querySelector(dock);
  if (!n) return null;
  const r = (e) => { const b = e.getBoundingClientRect();
    return { x: b.x, y: b.y, w: b.width, h: b.height, top: b.top, cx: b.x + b.width / 2 }; };
  const vis = (e) => { if (!e) return false; const b = e.getBoundingClientRect(), cs = getComputedStyle(e);
    return b.width > 0 && b.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const tabs = [...n.querySelectorAll(tab)].map((a) => ({
    href: a.getAttribute('data-dock-item'), text: a.innerText.trim(), rect: r(a),
    current: a.getAttribute('aria-current') }));
  const p = document.querySelector(primary);
  const c = document.querySelector(cma);
  return { nav: r(n), opacity: getComputedStyle(n).opacity, cls: n.className,
           scrollW: n.scrollWidth, clientW: n.clientWidth,
           vw: document.documentElement.clientWidth, vh: innerHeight,
           tabs, primary: p ? { rect: r(p), action: p.getAttribute('data-action'), vis: vis(p) } : null,
           cma: vis(c), more: vis(document.querySelector('[data-testid="dock-more"]')) };
}"""

# Resolves once the highlight's box has not moved for 6 frames (or 3 s).
# Also records every centre-x it passed through since `window.__hlTrack` was
# armed, so a glide (intermediate positions) can be told from a jump.
HL_ARM = """(sel) => {
  const xs = []; window.__hlTrack = xs; let stop = false; window.__hlStop = () => { stop = true; };
  const f = () => { const h = document.querySelector(sel);
    if (h) { const b = h.getBoundingClientRect(); xs.push(b.x + b.width / 2); }
    if (!stop) requestAnimationFrame(f); };
  requestAnimationFrame(f);
}"""
HL_SETTLE = """(sel) => new Promise((res) => {
  let last = null, still = 0; const t0 = performance.now();
  const f = () => {
    const h = document.querySelector(sel);
    const b = h && h.getBoundingClientRect();
    const k = b ? [b.x, b.y, b.width, b.height].map((v) => v.toFixed(1)).join() : 'none';
    if (k === last) still++; else { still = 0; last = k; }
    if (still >= 6 || performance.now() - t0 > 3000) {
      if (window.__hlStop) window.__hlStop();
      res(b ? { cx: b.x + b.width / 2, cy: b.y + b.height / 2, w: b.width, track: window.__hlTrack || [] } : null);
    } else requestAnimationFrame(f);
  };
  requestAnimationFrame(f);
})"""

# Reduced motion: click the dock tab, then sample every element's computed
# transform on every frame for `ms`, plus once more at the end. An element is
# flagged only if its transform took an INTERMEDIATE value — one that is
# neither the first nor the last it showed. That lets through static layout
# transforms (translate(-50%) centring, present before or arriving with the
# new page) and instant jumps (the highlight moving without a glide), and
# catches anything that travels or scales. Leaflet panes are ignored.
REDUCED_SAMPLE = """([sel, ms]) => new Promise((res) => {
  const ID = new Set(['none', 'matrix(1, 0, 0, 1, 0, 0)']);
  /* Two transforms are "the same" within 1px of translation and 0.01 of
     scale/rotation, so a sub-pixel relayout after an instant jump (a tab
     widening as its label goes bold) is not mistaken for a glide. */
  const nums = (t) => (t === 'id' ? [1, 0, 0, 1, 0, 0] : (t.slice(t.indexOf('(')).match(/-?[\\d.]+(?:e-?\\d+)?/g) || []).map(Number));
  const TX = { 6: [4, 5], 16: [12, 13, 14] };
  const same = (a, b) => {
    if (a === b) return true;
    const x = nums(a), y = nums(b);
    if (x.length !== y.length) {                    // 2d vs 3d: compare as 2d
      const d2 = (m) => m.length === 16 ? [m[0], m[1], m[4], m[5], m[12], m[13]] : m;
      return same2(d2(x), d2(y), TX[6]);
    }
    return same2(x, y, TX[x.length] || []);
  };
  const same2 = (x, y, tx) => x.every((v, i) => Math.abs(v - y[i]) <= (tx.includes(i) ? 1 : 0.01));
  const seen = new Map();                           // el -> [values in order]
  const name = (e) => (e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') +
    [...e.classList].slice(0, 3).map((c) => '.' + c).join('') +
    (e.getAttribute('data-testid') ? `[${e.getAttribute('data-testid')}]` : '')).slice(0, 90);
  const snap = () => {
    for (const e of document.querySelectorAll('body *')) {
      if (e.closest('.leaflet-container, [class*="leaflet-"]')) continue;
      const t = getComputedStyle(e).transform;
      let v = seen.get(e);
      if (!v) {
        if (ID.has(t)) { seen.set(e, ['id']); continue; }
        v = []; seen.set(e, v);
      }
      const val = ID.has(t) ? 'id' : t;
      if (!v.length || !same(v[v.length - 1], val)) v.push(val);
    }
  };
  snap();                                           // baseline
  const a = document.querySelector(sel);
  if (!a) return res({ error: 'no tab ' + sel });
  a.click();
  const t0 = performance.now(); let frames = 0;
  const f = () => { snap(); frames++;
    if (performance.now() - t0 < ms) requestAnimationFrame(f);
    else setTimeout(() => { snap();
      const bad = [];
      for (const [e, v] of seen) if (v.length > 2) bad.push({ el: name(e), values: v.slice(0, 4) });
      res({ frames, bad: bad.slice(0, 8), nbad: bad.length, path: location.pathname });
    }, 50);
  };
  requestAnimationFrame(f);
})"""


def check_no_rail(page, tag: str) -> None:
    info = page.evaluate(RAIL_PROBE)
    check(f"{tag}: no aside.rail", info["rails"] == 0, f"{info['rails']} found")
    check(f"{tag}: no fixed ~300px full-height element at left:0", not info["fixedLeft"], info["fixedLeft"])
    c = info["centre"]
    if c is not None:
        check(f"{tag}: the .mg-page column is centred (left gap ≈ right gap, ≤4px)",
              abs(c["left"] - c["right"]) <= 4, c)


def wait_dock(page, timeout=T) -> None:
    """The dock is in, at full opacity, not quiet, and has stopped moving."""
    page.wait_for_function(
        """(sel) => { const n = document.querySelector(sel); if (!n) return false;
             if (n.classList.contains('quiet') || getComputedStyle(n).opacity !== '1') return false;
             const k = JSON.stringify(n.getBoundingClientRect());
             const same = window.__dockLast === k; window.__dockLast = k; return same; }""",
        arg=DOCK, polling="raf", timeout=timeout)


def check_dock(page, base: str, vp: str, shot) -> None:
    tag = f"{vp} dock"
    w = page.viewport_size["width"]

    def layout():
        page.goto(base + "/prospects", wait_until="domcontentloaded")
        wait_dock(page)
        d = page.evaluate(DOCK_PROBE, [DOCK, TAB, PRIMARY, CMA])
        nav = d["nav"]
        check(f"{tag}: visible inside the viewport at opacity 1",
              d["opacity"] == "1" and nav["x"] >= 0 and nav["y"] >= 0
              and nav["x"] + nav["w"] <= d["vw"] + 0.5 and nav["y"] + nav["h"] <= d["vh"] + 0.5, d["nav"])
        centred = abs(nav["x"] - (d["vw"] - nav["x"] - nav["w"]))
        check(f"{tag}: centred horizontally (≤4px)", centred <= 4, f"off by {centred:.1f}")
        hrefs = [t["href"] for t in d["tabs"]]
        want = [h for h in DOCK_TABS if h != "/online"]
        missing = [h for h in want if h not in hrefs]
        check(f"{tag}: tabs Home/Prospects/Agent Z/Leads/Map/Media present", not missing,
              f"missing {missing}, have {hrefs}")
        check(f"{tag}: Online is a tab or folds into [dock-more]", "/online" in hrefs or d["more"], hrefs)
        check(f"{tag}: has the raised primary", bool(d["primary"] and d["primary"]["vis"]), d["primary"])
        tops = [t["rect"]["top"] for t in d["tabs"]] + ([d["primary"]["rect"]["top"]] if d["primary"] else [])
        spread = max(tops) - min(tops) if tops else 0
        check(f"{tag}: one row (tabs + primary tops within 2px)", spread <= 2, f"spread {spread:.1f}px")
        check(f"{tag}: no overflow (scrollWidth ≤ clientWidth)", d["scrollW"] <= d["clientW"],
              f"{d['scrollW']} > {d['clientW']}")
        check(f"{tag}: width ≤ viewport − 16", nav["w"] <= d["vw"] - 16, f"{nav['w']:.0f} vs {d['vw']}")
        labelled = [t["href"] for t in d["tabs"] if t["text"]]
        if w < 900:
            check(f"{tag}: labels hidden below 900px", not labelled, f"labelled: {labelled}")
        else:
            check(f"{tag}: labels shown from 900px", len(labelled) == len(d["tabs"]),
                  f"labelled {labelled} of {hrefs}")
        check(f"{tag}: CMA pill {'present' if w >= 1024 else 'absent'} at {w}px",
              d["cma"] == (w >= 1024), f"cma visible={d['cma']}")
        cur = [t["href"] for t in d["tabs"] if t["current"] == "page"]
        check(f"{tag}: /prospects tab is aria-current", cur == ["/prospects"], cur)
        shot(vp, "/prospects", suffix="-dock")

    step(f"{tag}: layout", layout)

    def glide():
        page.goto(base + "/prospects", wait_until="domcontentloaded")
        wait_dock(page)
        page.evaluate(HL_SETTLE, HL)
        before = page.evaluate(HL_SETTLE, HL)
        check(f"{tag}: [dock-highlight] exists", before is not None)
        if before is None:
            return
        page.evaluate(HL_ARM, HL)
        page.click(f'{DOCK} a[data-dock-item="/leads"]', timeout=T)
        page.wait_for_url("**/leads**", timeout=T)
        page.wait_for_function(
            "(s) => document.querySelector(s)?.getAttribute('aria-current') === 'page'",
            arg=f'{DOCK} a[data-dock-item="/leads"]', timeout=T)
        after = page.evaluate(HL_SETTLE, HL)
        tab = page.locator(f'{DOCK} a[data-dock-item="/leads"]').bounding_box()
        tcx, tcy = tab["x"] + tab["width"] / 2, tab["y"] + tab["height"] / 2
        dx, dy = abs(after["cx"] - tcx), abs(after["cy"] - tcy)
        check(f"{tag}: highlight settles on Leads (centre within 3px)", dx <= 3 and dy <= 3,
              f"dx {dx:.1f} dy {dy:.1f}")
        check(f"{tag}: Leads has aria-current=page", True)
        lo, hi = sorted((before["cx"], after["cx"]))
        mids = {round(x) for x in after["track"] if lo + 1 < x < hi - 1}
        check(f"{tag}: the highlight glides (intermediate positions seen)", len(mids) >= 2,
              f"{len(mids)} intermediate x from {before['cx']:.0f} to {after['cx']:.0f}")
        shot(vp, "/leads", suffix="-glide")

    step(f"{tag}: tab glide Prospects → Leads", glide)

    def primary():
        page.goto(base + "/prospects", wait_until="domcontentloaded")
        wait_dock(page)
        btn = page.locator(PRIMARY).first
        action = btn.get_attribute("data-action")
        if action == "crawl":
            if crawl_running(page, base):
                print("       (a crawl is running: the primary shows progress, sheet not checked)")
                return
            btn.click(timeout=T)
            page.wait_for_selector(CRAWL_SHEET, state="visible", timeout=T)
            check(f"{tag}: primary (crawl) opens the crawl sheet", True)
            # the dock floats above the modal, but is out of reach behind it
            check(f"{tag}: the dock is inert while the crawl sheet is open",
                  page.evaluate(f"() => !!document.querySelector('{DOCK}')?.inert"))
            page.keyboard.press("Escape")
            page.wait_for_selector(CRAWL_SHEET, state="hidden", timeout=T)
            check(f"{tag}: Escape closes the crawl sheet", True)
            check(f"{tag}: the dock is live again once the sheet closes",
                  page.evaluate(f"() => !document.querySelector('{DOCK}')?.inert"))
            check(f"{tag}: focus returns to the primary after the sheet closes",
                  page.evaluate(f"() => !!document.activeElement?.closest('{PRIMARY}')"))
        elif action == "quicklog":
            check_quicklog(page, PRIMARY, f"{tag} primary")
        else:
            check(f"{tag}: primary data-action is crawl or quicklog on /prospects", False, action)

    step(f"{tag}: raised primary", primary)

    for path in ("/", "/prospects", "/leads"):
        def account(path=path):
            page.goto(base + path, wait_until="domcontentloaded")
            btn = page.locator(ACCOUNT).locator("visible=true").first
            btn.wait_for(state="visible", timeout=T)
            btn.click(timeout=T)
            page.wait_for_url("**/account**", timeout=T)
            check(f"{tag}: Account button on {path} opens /account", True)

        step(f"{tag}: Account from {path}", account)

    def quiet():
        page.goto(base + "/", wait_until="domcontentloaded")
        page.wait_for_selector(DOCK, state="attached", timeout=T)
        page.wait_for_selector(f"{DOCK}.quiet", state="attached", timeout=8000)
        check(f"{tag}: Home's dock goes .quiet after idle at {w}px", True)

    step(f"{tag}: Home quiet", quiet)


def check_reduced(br, base: str, vp: str) -> None:
    """A fresh context with prefers-reduced-motion: reduce. Route changes
    through the dock animate opacity only — no transform travels."""
    tag = f"{vp} reduced-motion"
    ctx = br.new_context(device_scale_factor=1, reduced_motion="reduce", **VIEWPORTS[vp])
    ctx.set_default_timeout(15000)
    page = ctx.new_page()
    attach_console(page, lambda: f"{vp}/reduced")
    try:
        sign_in(page, base)
        for src, dst in (("/prospects", "/leads"), ("/leads", "/prospects")):
            def run(src=src, dst=dst):
                if urlparse(page.url).path != src:
                    page.goto(base + src, wait_until="domcontentloaded")
                wait_dock(page)
                page.wait_for_timeout(300)      # entry fades done (opacity only anyway)
                r = page.evaluate(REDUCED_SAMPLE, [f'{DOCK} a[data-dock-item="{dst}"]', 600])
                if r.get("error"):
                    check(f"{tag}: {src} → {dst}", False, r["error"])
                    return
                check(f"{tag}: {src} → {dst} moved no transform ({r['frames']} frames)",
                      r["nbad"] == 0, f"{r['nbad']} element(s): {r['bad']}")
                check(f"{tag}: {src} → {dst} navigated", r["path"].startswith(dst)
                      or urlparse(page.url).path.startswith(dst), r["path"])

            step(f"{tag}: {src} → {dst}", run)
    finally:
        ctx.close()


# ---------------------------------------------------------------- the chat launcher, everywhere

LAUNCHER = '[data-testid="chat-launcher"]'

# Marks and counts the launchers a person can actually see: a non-zero box
# inside the viewport, not display:none / visibility:hidden, no ancestor at
# opacity 0, and the topmost element at its centre is the launcher (or inside
# it). The one that passes gets [data-ct-visible] so the click hits it.
LAUNCHER_PROBE = """(sel) => {
  const vw = document.documentElement.clientWidth, vh = innerHeight;
  const out = [];
  for (const e of document.querySelectorAll(sel)) {
    e.removeAttribute('data-ct-visible');
    const b = e.getBoundingClientRect();
    const why = [];
    if (!(b.width > 0 && b.height > 0)) why.push('no box');
    const cx = b.left + b.width / 2, cy = b.top + b.height / 2;
    if (!(cx >= 0 && cy >= 0 && cx <= vw && cy <= vh)) why.push('off-screen');
    const cs = getComputedStyle(e);
    if (cs.visibility === 'hidden' || cs.display === 'none') why.push('hidden');
    for (let a = e; a; a = a.parentElement)
      if (parseFloat(getComputedStyle(a).opacity) < 0.05) { why.push('opacity 0'); break; }
    if (!why.length) {
      const top = document.elementFromPoint(cx, cy);
      if (!top || !(top === e || e.contains(top)))
        why.push('covered by ' + (top ? (top.tagName.toLowerCase() + '.' + [...top.classList].slice(0, 2).join('.')) : 'nothing'));
    }
    out.push({ why, x: Math.round(b.left), y: Math.round(b.top) });
    if (!why.length) e.setAttribute('data-ct-visible', '');
  }
  const badges = [...document.querySelectorAll('[data-testid="chat-badge"]')];
  const stray = badges.filter((bd) => !bd.closest(sel)).length;
  return { all: out, visible: out.filter((o) => !o.why.length).length, badges: badges.length, stray };
}"""


def sweep_routes(page, base: str) -> tuple[list[str], list[str]]:
    """Every route the chat launcher must sit on: the fixed ones, plus each
    /leads and /media sub-page found under ui/src/routes. A [param] route
    takes a real id from the scratch DB's API, or is skipped with a note."""
    routes = ["/", "/prospects", "/leads", "/map", "/media", "/online", "/agent", "/account"]
    notes = []
    ids = {}

    def first(url, key):
        try:
            rows = page.context.request.get(base + url).json()
            return str(rows[0][key]) if isinstance(rows, list) and rows else None
        except Exception:                               # noqa: BLE001
            return None

    for top in ("leads", "media"):
        root = os.path.join(REPO, "ui", "src", "routes", top)
        found = []
        for dirpath, _dirs, files in os.walk(root):
            if "+page.svelte" not in files or dirpath == root:
                continue
            rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
            parts = rel.split("/")
            if any(p.startswith("[") for p in parts):
                param = next(p for p in parts if p.startswith("["))
                src = {("contacts", "[id]"): ("/api/contacts", "id"),
                       ("properties", "[gid]"): ("/api/tracked", "group_id")}.get((parts[0], param))
                if src and src not in ids:
                    ids[src] = first(*src)
                val = ids.get(src) if src else None
                if not val:
                    notes.append(f"/{top}/{rel}: no real id for {param}, skipped")
                    continue
                rel = "/".join(val if p == param else p for p in parts)
            found.append(f"/{top}/{rel}")
        routes += sorted(found)
    # The media editors take an optional ?id= / ?project=; the scratch
    # MEDIA_ROOT is empty, so there is no real item to open them on.
    notes.append("/media/edit, /media/shoot, /media/video: opened without ?id (scratch MEDIA_ROOT has no items)")
    return routes, notes


def check_launcher(page, tag: str) -> bool:
    """Exactly one launcher a person can see (waits up to T for it)."""
    try:
        page.wait_for_function(f"() => ({LAUNCHER_PROBE})({json.dumps(LAUNCHER)}).visible === 1", timeout=T)
    except Exception:                                   # noqa: BLE001
        pass
    info = page.evaluate(LAUNCHER_PROBE, LAUNCHER)
    ok = check(f"{tag}: exactly one visible, uncovered [chat-launcher]", info["visible"] == 1, info["all"])
    if info["badges"]:
        check(f"{tag}: [chat-badge] sits inside the launcher", info["stray"] == 0,
              f"{info['stray']} of {info['badges']} outside")
    return ok


def check_chat_everywhere(page, base: str, vp: str, done: set[str]) -> None:
    """Task 0048: one reachable chat launcher on every route, sub-pages
    included; it opens the chat. `done` = routes whose chat click the main
    route loop already exercised (only the visibility check repeats there)."""
    routes, notes = sweep_routes(page, base)
    for n in notes:
        print(f"       note: {n}")
    for path in routes:
        tag = f"{vp} chat {path}"

        def run(path=path, tag=tag):
            page.goto(base + path, wait_until="domcontentloaded")
            page.wait_for_selector(LAUNCHER, state="attached", timeout=T)
            if check_launcher(page, tag) and path not in done:
                check_chat(page, f"{LAUNCHER}[data-ct-visible]", tag, frost=not path.startswith("/map"))

        step(f"{tag}: launcher", run)

    # Home once the dock has gone quiet: the launcher must still be there
    def quiet():
        tag = f"{vp} chat / (dock quiet)"
        page.goto(base + "/", wait_until="domcontentloaded")
        page.wait_for_selector(f"{DOCK}.quiet", state="attached", timeout=8000)
        check_launcher(page, tag)

    step(f"{vp} chat / (dock quiet)", quiet)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--shots", metavar="DIR", help="save full-viewport screenshots here")
    ap.add_argument("--label", default="after",
                    help="screenshot name prefix: <label>-<viewport>-<route>.png (default: after)")
    ap.add_argument("--db", help="database to copy (default: prospects.db in this checkout)")
    ap.add_argument("--only", help="comma list of viewports (phone,ipad,ipad-l,desktop)")
    ap.add_argument("--no-dock", action="store_true", help="skip the dock / reduced-motion checks")
    ap.add_argument("--no-chat-sweep", action="store_true",
                    help="skip the one-chat-launcher check on every route and sub-page")
    ap.add_argument("--routes", help="comma list of routes to visit (default: all)")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    if args.shots:
        os.makedirs(args.shots, exist_ok=True)
    vps = [v.strip() for v in (args.only.split(",") if args.only else VIEWPORTS) if v.strip()]
    unknown = [v for v in vps if v not in VIEWPORTS]
    if unknown:
        sys.exit(f"unknown viewport(s) {unknown}; choose from {list(VIEWPORTS)}")
    routes = args.routes.split(",") if args.routes else ROUTES

    if NO_MEDIA:
        print("note: no zerko/ in this checkout; /api/media/* 503s are ignored")
    with boot(args.db, quiet=False) as base, sync_playwright() as p:
        br = p.chromium.launch()
        for vp in vps:
            print(f"\n== {vp} {VIEWPORTS[vp]['viewport']}")
            ctx = br.new_context(device_scale_factor=2, **VIEWPORTS[vp])
            ctx.set_default_timeout(15000)
            ctx.add_init_script(FIRST_PAINT)
            page = ctx.new_page()
            attach_console(page, lambda vp=vp: vp)
            sign_in(page, base)

            def shot(vp_, path, suffix=""):
                if args.shots:
                    page.screenshot(path=os.path.join(
                        args.shots, f"{args.label}-{vp_}-{route_name(path)}{suffix}.png"))

            for path in routes:
                if path == "/":
                    check_home(page, base, vp, shot)
                else:
                    check_route(page, base, vp, path, shot)
            if not args.no_dock:
                check_dock(page, base, vp, shot)
            if not args.no_chat_sweep:
                check_chat_everywhere(page, base, vp, set(routes))
            ctx.close()
            if not args.no_dock:
                check_reduced(br, base, vp)
        br.close()

    print()
    print(f"console/page errors: {len(errors)}")
    for e in errors:
        print("  ", e)
    print(f"{len(failures)} failed check(s)" if failures else "all checks passed")
    if failures:
        for f in failures:
            print("   -", f)
    return 1 if failures or errors else 0


if __name__ == "__main__":
    sys.exit(main())
