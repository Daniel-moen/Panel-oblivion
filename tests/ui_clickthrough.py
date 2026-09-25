"""UI click-through: every route, three device shapes, every console error.

Plain script, no pytest. It boots the app itself, on a scratch DATA_DIR
holding a COPY of prospects.db, on a free loopback port, signs in through
the /login form, and drives headless Chromium (Playwright):

    .venv/bin/python tests/ui_clickthrough.py                    # checks only
    .venv/bin/python tests/ui_clickthrough.py --shots /tmp/shots --label before

Viewports: phone 390x844 (mobile, touch), iPad 1024x768 and 1180x820 (touch).
Routes: / /prospects /leads /map /media /online /account.

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
Every other route: header.strip's Search and Quick log buttons do the same.

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--shots", metavar="DIR", help="save full-viewport screenshots here")
    ap.add_argument("--label", default="after", help="screenshot name prefix (default: after)")
    ap.add_argument("--db", help="database to copy (default: prospects.db in this checkout)")
    ap.add_argument("--only", help="comma list of viewports (phone,ipad,ipad-l)")
    ap.add_argument("--routes", help="comma list of routes to visit (default: all)")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    if args.shots:
        os.makedirs(args.shots, exist_ok=True)
    vps = [v for v in (args.only.split(",") if args.only else VIEWPORTS)]
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
            ctx.close()
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
