#!/usr/bin/env python3
"""Mint a fresh LOOM bearer token — run this on a trusted machine (your Mac).

LOOM's SPA client forbids the OAuth password grant, and login federates to
Azure AD B2C (a JavaScript form), so a real browser is required to log in.
This script does exactly that with Playwright, sniffs the bearer token off the
first authenticated pi-api call, and writes it to loom_token.json. The web app
(loom.py) then reads that file — it never runs a browser itself.

Run it whenever the token goes stale (LOOM tokens last ~1 hour). Automate it
with cron / launchd, e.g. every 45 minutes:

    */45 * * * *  cd ~/prospecting-auto && LOOM_USER=… LOOM_PASS=… \
                  ./venv/bin/python loom_login.py >> loom_login.log 2>&1

One-time setup (installs Playwright + uses your existing Chrome):
    pip install playwright && python loom_login.py   # channel=chrome, no download

Env: LOOM_USER, LOOM_PASS  (required)
     LOOM_TOKEN_PATH        (optional; default loom_token.json beside this file)
     LOOM_LOGIN_HEADFUL=1   (optional; show the browser to debug)
"""
from __future__ import annotations

import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

APP = "https://pi.loom.co.za/"
TOKEN_PATH = os.environ.get(
    "LOOM_TOKEN_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "loom_token.json"),
)
USER = os.environ.get("LOOM_USER", "")
PASS = os.environ.get("LOOM_PASS", "")
HEADLESS = os.environ.get("LOOM_LOGIN_HEADFUL", "") != "1"


def log(m: str) -> None:
    print(f"[loom_login] {m}", flush=True)


def mint_token() -> str:
    if not USER or not PASS:
        sys.exit("Set LOOM_USER and LOOM_PASS environment variables.")

    captured = {"tok": None}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=HEADLESS)
        ctx = browser.new_context()
        page = ctx.new_page()

        def on_request(req):
            if captured["tok"]:
                return
            if "pi-api.loom.co.za" in req.url:
                auth = req.headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    captured["tok"] = auth.split(" ", 1)[1]

        ctx.on("request", on_request)

        log("opening LOOM and signing in via Azure B2C …")
        page.set_default_navigation_timeout(90000)
        for attempt in range(3):
            try:
                page.goto(APP, wait_until="domcontentloaded", timeout=90000)
                break
            except Exception as e:  # noqa: BLE001
                log(f"goto attempt {attempt+1} slow ({e!r}); retrying")
        else:
            sys.exit("pi.loom.co.za did not load after 3 tries — network/site slow.")
        try:
            page.wait_for_selector("#password, input[type=password]", timeout=45000)
            user_sel = next((s for s in ("#signInName", "#email",
                                         "input[name=Unified]", "input[type=email]")
                             if page.query_selector(s)), "input[type=text]")
            page.fill(user_sel, USER)
            page.fill("#password" if page.query_selector("#password")
                      else "input[type=password]", PASS)
            (page.query_selector("#next") or page.query_selector("button[type=submit]")).click()
        except Exception as e:  # noqa: BLE001
            log(f"login form note: {e!r} (perhaps already signed in)")

        deadline = time.time() + 60
        while time.time() < deadline and not captured["tok"]:
            page.wait_for_timeout(500)
        if not captured["tok"]:
            page.goto(APP, wait_until="domcontentloaded")
            deadline = time.time() + 25
            while time.time() < deadline and not captured["tok"]:
                page.wait_for_timeout(500)

        browser.close()

    if not captured["tok"]:
        sys.exit("Could not capture a token — re-run with LOOM_LOGIN_HEADFUL=1 to watch.")
    return captured["tok"]


def main() -> None:
    tok = mint_token()
    tmp = TOKEN_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"access_token": tok,
                   "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, fh)
    os.replace(tmp, TOKEN_PATH)  # atomic — the web app never reads a half file
    log(f"wrote fresh token ({len(tok)} chars) to {TOKEN_PATH}")


if __name__ == "__main__":
    main()
