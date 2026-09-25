"""Frame times under 4x CPU throttling: Home's scroll and reveal, /prospects scroll.

Plain script, no pytest. Boots the app exactly as ui_clickthrough.py does
(scratch DATA_DIR, a copy of prospects.db, a free port, signed in through
/login), throttles the CPU 4x through CDP (Emulation.setCPUThrottlingRate) and
samples requestAnimationFrame intervals while:

  home-scroll     from the top, window.scrollTo in 40px steps every 16 ms,
                  through the reveal to the bottom of the overview
  home-reveal     click button[data-home-reveal] (its smooth scroll), 900 ms
  prospects-scroll  the same stepped scroll on /prospects, for comparison
  route-change    click a dock tab (nav[data-testid=dock] a[data-dock-item]),
                  Prospects → Leads → Prospects, first visits, 700 ms each
  dock-glide      the same two tabs once both routes are warm, three round
                  trips, 600 ms each: mostly the highlight's glide

for the phone (390x844, mobile + touch), the iPad (1024x768, touch) and a
desktop (1440x900).

    .venv/bin/python tests/ui_perf.py                     # fails if any p95 > 33.4 ms
    .venv/bin/python tests/ui_perf.py --json perf.json --no-fail

Prints n / p50 / p95 / max and the count of frames over 33.4 ms (two frames
at 60 Hz) per measure. Headless Chromium draws blur in software, so the
numbers are pessimistic; compare runs, not devices.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui_clickthrough import REPO, VIEWPORTS, boot, sign_in  # noqa: E402

LONG_MS = 33.4
THROTTLE = 4
DEVICES = ("phone", "ipad", "desktop")

# rAF sampler: resolves with the frame intervals (ms), the first partial one dropped.
SAMPLER = """
window.__sample = (until) => new Promise((res) => {
  const t = []; let last = performance.now();
  function f(now) { t.push(now - last); last = now;
    if (until()) requestAnimationFrame(() => res(t.slice(1))); else requestAnimationFrame(f); }
  requestAnimationFrame(f);
});
"""

# Stepped scroll from `from` to `to` (px), 40px every 16 ms, sampled throughout.
STEP_SCROLL = """([from, to]) => {
  window.scrollTo({ top: from, behavior: 'instant' });
  let y = from, done = false;
  const iv = setInterval(() => { y = Math.min(to, y + 40); window.scrollTo(0, y);
                                 if (y >= to) { clearInterval(iv); done = true; } }, 16);
  return window.__sample(() => done);
}"""

REVEAL = """(ms) => {
  const b = document.querySelector('button[data-home-reveal]');
  if (!b) return null;
  const t0 = performance.now();
  const p = window.__sample(() => performance.now() - t0 >= ms);
  b.click();
  return p;
}"""


# Click the dock tab for `href` and sample frames for `ms` (null if no tab).
DOCK_CLICK = """([href, ms]) => {
  const a = document.querySelector(`nav[data-testid="dock"] a[data-dock-item="${href}"]`);
  if (!a) return null;
  const t0 = performance.now();
  const p = window.__sample(() => performance.now() - t0 >= ms);
  a.click();
  return p;
}"""


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def summarize(frames):
    if not frames:
        return {"n": 0}
    return {"n": len(frames), "p50": round(pct(frames, .5), 1), "p95": round(pct(frames, .95), 1),
            "max": round(max(frames), 1), "over": sum(1 for x in frames if x > LONG_MS)}


def overview_bottom(page) -> int:
    """Scroll offset that puts the bottom of [data-home-overview] (or the page) at the bottom."""
    return page.evaluate("""() => {
      const max = document.scrollingElement.scrollHeight - innerHeight;
      const o = document.querySelector('[data-home-overview]');
      if (!o) return max;
      const b = o.getBoundingClientRect().bottom + scrollY - innerHeight;
      return Math.max(0, Math.min(max, Math.ceil(b)));
    }""")


def settle(page, ms=800):
    page.evaluate("() => window.scrollTo({ top: 0, behavior: 'instant' })")
    page.wait_for_timeout(ms)


def measure_device(br, base, dev):
    out, notes = {}, []
    ctx = br.new_context(**VIEWPORTS[dev])
    ctx.set_default_timeout(120000)
    ctx.add_init_script(SAMPLER)
    page = ctx.new_page()
    sign_in(page, base)
    cdp = ctx.new_cdp_session(page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": THROTTLE})

    # --- Home
    page.goto(base + "/", wait_until="load")
    try:
        page.wait_for_function(
            "() => { const l = document.querySelector('[data-home-line]'); return l && l.textContent.trim(); }",
            timeout=30000)
    except Exception:                                   # noqa: BLE001
        notes.append("home: [data-home-line] never got text")
    page.wait_for_timeout(1500)
    settle(page)
    to = overview_bottom(page)
    if to <= 0:
        notes.append("home: nothing to scroll")
    out["home-scroll"] = summarize(page.evaluate(STEP_SCROLL, [0, to]) if to > 0 else [])
    out["home-scroll"]["px"] = to

    settle(page, 1200)
    frames = page.evaluate(REVEAL, 900)
    if frames is None:
        notes.append("home: no button[data-home-reveal]")
    out["home-reveal"] = summarize(frames or [])
    out["home-reveal"]["scrollY_after"] = page.evaluate("() => scrollY")

    # --- Prospects
    page.goto(base + "/prospects", wait_until="load")
    try:
        page.wait_for_selector("[data-prospect]", timeout=120000)
    except Exception:                                   # noqa: BLE001
        notes.append("prospects: no [data-prospect] cards")
    page.wait_for_timeout(2000)
    settle(page)
    to = min(page.evaluate("() => document.scrollingElement.scrollHeight - innerHeight"), 2400)
    out["prospects-scroll"] = summarize(page.evaluate(STEP_SCROLL, [0, to]) if to > 0 else [])
    out["prospects-scroll"]["px"] = to

    # --- the dock: route changes (cold), then the glide between warm routes
    def hop(href, ms):
        frames = page.evaluate(DOCK_CLICK, [href, ms])
        if frames is None:
            notes.append(f"dock: no tab {href}")
            return []
        try:
            page.wait_for_url(f"**{href}**", timeout=30000)
        except Exception:                               # noqa: BLE001
            notes.append(f"dock: {href} did not load")
        page.wait_for_timeout(600)                      # let the new page settle
        return frames

    settle(page, 400)
    frames = []
    for href in ("/leads", "/prospects"):
        frames += hop(href, 700)
    out["route-change"] = summarize(frames)
    frames = []
    for _ in range(3):
        for href in ("/leads", "/prospects"):
            frames += hop(href, 600)
    out["dock-glide"] = summarize(frames)
    ctx.close()
    return out, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", metavar="PATH", help="write the numbers here")
    ap.add_argument("--no-fail", action="store_true", help="report only; exit 0 whatever the p95")
    ap.add_argument("--db", help="database to copy (default: prospects.db in this checkout)")
    ap.add_argument("--only", help="comma list of devices (" + ",".join(DEVICES) + ")")
    args = ap.parse_args()
    devices = DEVICES
    if args.only:
        devices = tuple(d.strip() for d in args.only.split(",") if d.strip())
        unknown = [d for d in devices if d not in DEVICES]
        if unknown:
            ap.error(f"unknown device(s): {', '.join(unknown)}")
    from playwright.sync_api import sync_playwright

    results, notes = {}, []
    with boot(args.db, quiet=False) as base, sync_playwright() as p:
        br = p.chromium.launch()
        for dev in devices:
            results[dev], n = measure_device(br, base, dev)
            notes += [f"{dev} {x}" for x in n]
        br.close()

    print(f"\nframe intervals at {THROTTLE}x CPU throttle (ms; 'over' = frames > {LONG_MS})")
    print(f"{'measure':<24}{'n':>5}{'p50':>8}{'p95':>8}{'max':>8}{'over':>6}")
    bad = []
    for dev, ms in results.items():
        for name, s in ms.items():
            label = f"{dev} {name}"
            if not s.get("n"):
                print(f"{label:<24}{0:>5}   (no frames)")
                bad.append(f"{label}: no frames")
                continue
            print(f"{label:<24}{s['n']:>5}{s['p50']:>8.1f}{s['p95']:>8.1f}{s['max']:>8.1f}{s['over']:>6}")
            if s["p95"] > LONG_MS:
                bad.append(f"{label}: p95 {s['p95']} ms > {LONG_MS}")
    for n in notes:
        print("note:", n)

    if args.json:
        try:
            rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                                 capture_output=True, text=True).stdout.strip()
        except OSError:
            rev = ""
        with open(args.json, "w") as f:
            json.dump({"throttle": THROTTLE, "long_ms": LONG_MS, "git": rev,
                       "when": time.strftime("%Y-%m-%dT%H:%M:%S"), "results": results,
                       "notes": notes}, f, indent=2)
        print(f"wrote {args.json}")

    print()
    if bad:
        print("over budget:" if not args.no_fail else "over budget (--no-fail):")
        for b in bad:
            print("   -", b)
    else:
        print(f"every p95 within {LONG_MS} ms")
    return 1 if bad and not args.no_fail else 0


if __name__ == "__main__":
    sys.exit(main())
