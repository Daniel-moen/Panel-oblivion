"""Local web dashboard for the prospecting engine.

    source .venv/bin/activate && python webapp.py
    -> http://localhost:5051

Pick suburbs and portals, hit Scrape, watch all five crawls run in parallel,
then browse the ranked prospects. Sole-mandate properties are hidden by
default because Oblivion cannot win business on them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote

from flask import Flask, Response, jsonify, redirect, request, send_from_directory

import agent_z
import auth
import config
import db
import dedupe
import erf
import finder
import media
import photos
import pipeline
import scorer
import sources as source_registry

app = Flask(__name__)

# ---------------------------------------------------------------- access
#
# This dashboard exposes Oblivion's prospect list and can start crawls, so it
# must not sit open on a public URL. Set DASHBOARD_PASSWORD (and optionally
# DASHBOARD_USER) and every request needs HTTP basic auth.
#
# With no password set the app binds to localhost only when run directly, so
# local use stays friction-free; a hosted deploy without the variable refuses
# to serve rather than silently publishing the data.
#
# A browser signs in once and keeps a session cookie instead (auth.py), and
# can register a passkey so the next sign-in is Touch ID rather than a typed
# password. Basic auth is still accepted on every route, unchanged, so curl
# and scripts keep working.
_DASH_USER = auth.DASH_USER
_DASH_PASS = auth.DASH_PASS
_IS_HOSTED = auth.IS_HOSTED

# The share-link surface, kept to one short list so it can be audited at a
# glance. `/media/s/<token>` is the screening-room page a client opens; the
# two API prefixes under it are what that page fetches. Nothing else — no
# asset directory, no prefix wildcard — is exempt.
_PUBLIC_SHARE_PAGE = "/media/s/"


def _is_public_share_path(path: str) -> bool:
    if path.startswith(_PUBLIC_SHARE_PAGE) and path.count("/") == 3 \
            and len(path) > len(_PUBLIC_SHARE_PAGE):
        return True                      # /media/s/<token>, not /media/s/ or /media/s/a/b
    return media.is_public_path(path)


#: The one place the dashboard password is compared — now in auth.py, which
#: also owns the session cookie that is the second way through the same door.
_credentials_ok = auth.credentials_ok


def _wsgi_authorised(environ) -> bool:
    """The same check again, for a raw WSGI environ (the /zerko mount).

    Cookie as well as basic: DispatcherMiddleware puts this outside Flask, so
    this function is the *only* authentication /zerko gets, and a browser
    signed in with a passkey has no password to send. Without the cookie arm
    the whole media library would 401 for exactly the people who are signed
    in most securely.
    """
    if not _DASH_PASS:
        # Matches _require_auth: with no password set the app is local-only.
        return not _IS_HOSTED
    if auth.basic_ok(environ):
        return True                      # basic auth is the owner
    # A signed-in browser, and only if the account holds `media`. The whole
    # library — including Zerko's own unauthenticated /thumbnails mount —
    # hangs off this one function, so the privilege has to be checked on this
    # side of the dispatcher as well as on /api/media/token.
    user = auth.current_user(environ)
    return bool(user and "media" in auth.privileges_for(user))


@app.before_request
def _require_auth():
    # Vapi's end-of-call webhook can't do basic auth; caller.py authenticates
    # it with its own shared-secret header instead.
    if request.path == "/api/caller/webhook":
        return None
    # The sign-in surface itself. A login page that needed a login would be a
    # closed loop; /logout has to work for a session that is already stale;
    # the passkey *login* endpoints are the ceremony that produces the
    # session, and are safe unauthenticated because a passkey assertion is
    # proof on its own (and is rate-limited per IP in auth.py). Registration
    # is NOT in this list — adding a device requires being signed in already.
    if request.path in auth.PUBLIC_PATHS:
        return None
    # Client share links. A client is handed a URL and nothing else — they
    # have no dashboard password and must not need one — so these routes
    # authenticate on the share token itself, which Zerko checks for expiry,
    # revocation, an optional password and a per-IP failure limit on every
    # call. The exemption is three explicit prefixes and no wildcard: the
    # share *page* below is a self-contained document, so not even the
    # dashboard's JavaScript bundle has to be opened up to serve it.
    if _is_public_share_path(request.path):
        return None
    if not _DASH_PASS:
        if _IS_HOSTED:
            return Response(
                "DASHBOARD_PASSWORD is not set. Refusing to serve the "
                "prospect dashboard unauthenticated on a public host.\n"
                "Set it with:  railway variables --set DASHBOARD_PASSWORD=...",
                503, {"Content-Type": "text/plain"})
        return None                      # local, unauthenticated is fine
    if _credentials_ok(request.authorization):
        return None
    if auth.current_user(request):
        return None
    # A browser that typed a URL gets the login page; anything else gets the
    # old 401, WWW-Authenticate included, so curl -u and every script that
    # already talks to this API carry on unchanged. The Accept test is what
    # separates them: fetch() and curl do not ask for text/html.
    if request.method == "GET" and "text/html" in (request.headers.get("Accept") or ""):
        return redirect("/login?next=" + quote(request.full_path.rstrip("?"), safe="/?=&"))
    return Response(json.dumps({"error": "auth_required"}), 401,
                    {"Content-Type": "application/json",
                     "WWW-Authenticate": 'Basic realm="Oblivion Prospect Engine"'})

job = {
    "running": False,
    "phase": "idle",
    "log": [],
    "started": None,
    "done": 0,
    "total": 0,
    "per_source": {},
    # Which book(s) the running job is crawling — ["sale"], ["rent"] or both.
    # Surfaced in /api/status so the progress strip can say so.
    "listing_types": ["sale"],
}
job_lock = threading.Lock()
_stop = threading.Event()


def log(msg: str) -> None:
    line = f"{datetime.now():%H:%M:%S}  {msg}"
    with job_lock:
        job["log"].append(line)
        job["log"] = job["log"][-600:]
    print(line, flush=True)


def _run(suburbs, source_names, pages, use_ai, listing_types=("sale",)):
    progress = pipeline.Progress()

    def poll_progress():
        while job["running"]:
            snap = progress.snapshot()
            with job_lock:
                job.update(done=snap["done"], total=snap["total"],
                           per_source=snap["per_source"])
            _stop.wait(1.0)

    threading.Thread(target=poll_progress, daemon=True).start()
    try:
        job["phase"] = ("crawling portals" if listing_types == ("sale",)
                        else f"crawling portals ({'+'.join(listing_types)})")
        # only_stale: after a crawl, score what actually changed. A reasoning
        # model spends real time per property, so re-judging the whole database
        # to absorb a handful of new listings turned a 1-minute crawl into a
        # 15-minute job. The "Re-score existing data" button still does a full
        # pass when you want one (e.g. after editing the prompt).
        pipeline.run(suburbs, source_names, pages=pages, use_ai=use_ai,
                     log=log, progress=progress, stop=_stop, only_stale=True,
                     listing_types=listing_types)
        job["phase"] = "done"
    except Exception as e:
        job["phase"] = "error"
        log(f"ERROR: {type(e).__name__}: {e}")
    finally:
        snap = progress.snapshot()
        with job_lock:
            job.update(done=snap["done"], total=snap["total"],
                       per_source=snap["per_source"], running=False)


def _start_job(suburbs, srcs, pages, use_ai=True,
               listing_types=("sale",)) -> bool:
    """Claim the single job slot and launch a crawl; False if already busy.

    Check-and-set under job_lock so the dashboard button and the auto-crawl
    scheduler can never both claim the slot.

    listing_types defaults to ("sale",) — the crawl this dashboard has always
    run. Pass ("sale", "rent") or ("rent",) to include the to-rent books.
    """
    listing_types = _clean_types(listing_types)
    with job_lock:
        if job["running"]:
            return False
        job.update(running=True, phase="starting", log=[], done=0, total=0,
                   per_source={}, started=datetime.now().isoformat(),
                   listing_types=list(listing_types))
    _stop.clear()
    threading.Thread(target=_run,
                     args=(suburbs, srcs, pages, use_ai, listing_types),
                     daemon=True).start()
    return True


# The crawl's two books. "sale" is everything this engine scores and sells on;
# "rent" is the to-rent stock, stored but never deduped, priced or scored.
_TYPE_CHOICES = {"sale": ("sale",), "rent": ("rent",),
                 "both": ("sale", "rent")}


def _clean_types(listing_types) -> tuple[str, ...]:
    """Normalise to an ordered ("sale", "rent") subset; sale-only by default."""
    want = {t for t in (listing_types or ()) if t in ("sale", "rent")}
    return tuple(t for t in ("sale", "rent") if t in want) or ("sale",)


@app.post("/api/scrape")
@auth.require_priv("crawl")
def api_scrape():
    if job["running"]:
        return jsonify({"error": "a job is already running"}), 409
    body = request.get_json(force=True) or {}
    suburbs = [s for s in body.get("suburbs", []) if s in config.SUBURBS]
    srcs = [s for s in body.get("sources", []) if s in source_registry.REGISTRY]
    if not suburbs:
        return jsonify({"error": "no valid suburbs selected"}), 400
    if not srcs:
        return jsonify({"error": "no valid portals selected"}), 400
    pages = max(1, min(int(body.get("pages", 2)), 5))
    use_ai = bool(body.get("use_ai", True))
    # Which book to crawl: "sale" (the default, so every existing caller is
    # unchanged), "rent", or "both".
    want = str(body.get("type", "sale")).lower()
    if want not in _TYPE_CHOICES:
        return jsonify({"error": "type must be 'sale', 'rent' or 'both'"}), 400
    listing_types = _TYPE_CHOICES[want]

    if not _start_job(suburbs, srcs, pages, use_ai, listing_types):
        return jsonify({"error": "a job is already running"}), 409
    return jsonify({"ok": True, "listing_types": list(listing_types)})


# ------------------------------------------------------------- auto-crawl
#
# The constant loop (config.AUTO_CRAWL): a nightly full pass over everything,
# plus a cheap page-1 freshness sweep of the fast portals every
# AUTO_SWEEP_HOURS. Runs inside this process as one more daemon thread —
# job state is an in-memory dict and the Procfile pins one worker, so an
# external cron could not see or respect a running dashboard job; this
# scheduler shares the same _start_job guard and shows up in the same
# progress display. On a Mac that sleeps overnight the pass simply fires on
# wake (the loop checks the calendar, not an interval).
_auto = {"last_full": None, "last_sweep": None}


def _auto_sources(include_p24: bool) -> list[str]:
    return [n for n in source_registry.REGISTRY
            if config.SOURCES.get(n, {}).get("enabled")
            and (include_p24 or n != "property24")]


def _auto_crawl_loop():
    while True:
        time.sleep(60)
        try:
            if not config.AUTO_CRAWL or job["running"]:
                continue
            now = datetime.now()
            suburbs = list(config.SUBURBS)
            if now.hour == config.AUTO_CRAWL_HOUR and \
                    _auto["last_full"] != now.date():
                # Nightly full pass — Property24 included: overnight is the
                # right time for its 12-18s pacing. Both books too: the rental
                # crawl is the same fetches against each portal's to-rent
                # pages, it costs nothing at the scorer (rentals are never
                # scored), and the night is where that extra crawl time
                # belongs.
                types = ("sale", "rent") if config.AUTO_CRAWL_RENTALS \
                    else ("sale",)
                if _start_job(suburbs, _auto_sources(include_p24=True),
                              pages=config.MAX_PAGES_PER_SUBURB,
                              listing_types=types):
                    _auto["last_full"] = now.date()
                    log("auto-crawl: nightly full pass started "
                        f"({'+'.join(types)})")
            elif config.AUTO_SWEEP_HOURS > 0 and (
                    _auto["last_sweep"] is None
                    or (now - _auto["last_sweep"]).total_seconds()
                    >= config.AUTO_SWEEP_HOURS * 3600):
                # Freshness sweep: page 1 of the fast portals only. Keeps
                # last_seen current, which is what the proof-freshness gate,
                # the delisting sweep and price history all feed on.
                #
                # Sale-only, deliberately: every consumer of a sweep is
                # for-sale machinery (delisting -> sold proxy, proof
                # freshness, price history), and nothing in the engine reads
                # a rental's last_seen. Adding rent here would roughly double
                # the sweep's request count against every portal — the same
                # budget that has to stay small enough to run every few hours
                # — to refresh a timestamp nobody queries. Rentals get their
                # refresh on the nightly pass instead.
                if _start_job(suburbs, _auto_sources(include_p24=False),
                              pages=1):
                    _auto["last_sweep"] = now
                    log("auto-crawl: freshness sweep started (fast portals, "
                        "page 1)")
        except Exception as e:                          # noqa: BLE001
            print(f"auto-crawl scheduler error: {type(e).__name__}: {e}",
                  flush=True)


threading.Thread(target=_auto_crawl_loop, daemon=True).start()


def _prune_cache_on_boot():
    # The crawl pipeline prunes too, but that can be hours away — and a
    # volume that filled up while the app was down blocks every SQLite
    # write until something frees space. Do it before serving traffic.
    import httpclient
    try:
        httpclient.prune_cache(log=lambda m: print(m, flush=True))
    except Exception as e:                              # noqa: BLE001
        print(f"boot cache prune failed: {type(e).__name__}: {e}", flush=True)


threading.Thread(target=_prune_cache_on_boot, daemon=True).start()


@app.post("/api/stop")
@auth.require_priv("crawl")
def api_stop():
    _stop.set()
    log("stop requested — finishing current requests")
    return jsonify({"ok": True})


@app.post("/api/rescore")
@auth.require_priv("crawl")
def api_rescore():
    if job["running"]:
        return jsonify({"error": "a job is already running"}), 409
    use_ai = bool((request.get_json(force=True) or {}).get("use_ai", True))

    def rescore():
        try:
            with db.connect() as conn:
                job["phase"] = "matching across portals"
                s = dedupe.rebuild_groups(conn)
                log(f"dedupe: {s['listings']} listings -> {s['groups']} properties; "
                    f"{s['multi_agency_groups']} multi-agency, "
                    f"{s['multi_source_groups']} on multiple portals")
                job["phase"] = "scoring"
                n = scorer.score_all(conn, use_ai=use_ai, logger=log)
                log(f"re-scored {n} property groups")
            job["phase"] = "done"
        except Exception as e:
            job["phase"] = "error"
            log(f"ERROR: {type(e).__name__}: {e}")
        finally:
            job["running"] = False

    # Re-score is for-sale work only, so the status strip should not still be
    # advertising the last crawl's book.
    job.update(running=True, phase="starting", log=[], done=0, total=0,
               listing_types=["sale"])
    threading.Thread(target=rescore, daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/status")
def api_status():
    with job_lock:
        out = {k: job[k] for k in
               ("running", "phase", "log", "done", "total", "per_source",
                "listing_types")}
    # The log keeps 600 lines but rides on a poll every few seconds; the
    # progress strip only shows the tail, so send the last 200.
    out["log"] = out["log"][-200:]
    ok, reason = scorer.ai_status()
    out["ai_ok"] = ok
    out["ai_reason"] = reason
    out["auto_crawl"] = config.AUTO_CRAWL
    if config.AUTO_CRAWL:
        out["auto_last_full"] = (str(_auto["last_full"])
                                 if _auto["last_full"] else None)
        out["auto_last_sweep"] = (_auto["last_sweep"].isoformat()
                                  if _auto["last_sweep"] else None)
    return jsonify(out)


PROSPECT_QUERY = """
SELECT l.*, s.prospect_score, s.luxury_fit, s.open_mandate_confidence,
       s.marketing_weakness, s.tier, s.reasoning, s.pitch_angle, s.red_flags,
       s.scored_by, s.mandate_verdict, s.sellable, s.mandate_expiry_note,
       g.group_id, g.agency_count, g.source_count, g.match_evidence,
       e.status AS erf_status, e.method AS erf_method, e.erf_number,
       e.portion AS erf_portion, e.official_address, e.official_suburb,
       e.parcel_area_m2, e.latitude AS erf_lat, e.longitude AS erf_lng,
       e.note AS erf_note, e.candidates AS erf_candidates,
       e.ai_status AS erf_ai_status, e.ai_best AS erf_ai_best,
       CASE WHEN t.listing_number IS NULL THEN NULL ELSE 'tracked' END AS tracker_status
FROM listings l
LEFT JOIN scores s ON s.listing_key = l.listing_key
LEFT JOIN property_groups g ON g.listing_key = l.listing_key
LEFT JOIN erf_lookup e ON e.listing_key = l.listing_key
LEFT JOIN tracker t ON t.listing_number = l.source_id AND l.source = 'property24'
-- One book at a time. 'sale' is what every existing caller gets; the rentals
-- view asks for 'rent' explicitly. A rental has no score, no property group
-- and no erf, so it simply arrives with those columns NULL.
WHERE l.listing_type = :listing_type
  AND NOT EXISTS (
        SELECT 1 FROM property_groups g2
        JOIN listings l2 ON l2.listing_key = g2.listing_key
        JOIN tracker t2 ON t2.listing_number = l2.source_id
        WHERE g2.group_id = g.group_id
          AND l2.source = 'property24' AND t2.prospected = 1)
ORDER BY (s.prospect_score IS NULL) DESC, s.prospect_score DESC, l.price_zar DESC
"""


# The prospects cache is keyed on what the rows are built from rather than on
# a clock: SQLite's data_version (bumped whenever any other connection
# commits) plus the in-memory erf-AI / re-eval job states that are merged into
# the rows. A 12k-row build is ~3s of CPU, so rebuilding it on every 2s poll
# with nothing changed was the dominant cost of an idle dashboard.
_version_conn = None
_version_lock = threading.Lock()


def _db_version() -> int:
    """PRAGMA data_version from ONE long-lived connection.

    The counter is per connection and only moves when a *different*
    connection commits, which is every writer in this app, so one dedicated
    connection sees them all. It only ever runs this pragma in autocommit
    mode, so it never holds a transaction (or a WAL snapshot) open.
    """
    global _version_conn
    with _version_lock:
        if _version_conn is None:
            _version_conn = sqlite3.connect(
                config.DB_PATH, check_same_thread=False, timeout=30)
        return _version_conn.execute("PRAGMA data_version").fetchone()[0]


def _jobs_fingerprint() -> tuple:
    """Hashable snapshot of the job dicts _build_prospects merges into rows
    (erf_ai_running/erf_ai_error, reevaluating/reeval_error). list() first:
    worker threads replace entries while this runs."""
    def snap(d):
        return tuple(sorted((k, bool(v.get("running")), v.get("error"))
                            for k, v in list(d.items())))
    return snap(_ai_jobs), snap(_reeval_jobs)


def _prospects_entry(show_sole: bool, listing_type: str = "sale") -> dict:
    """The cache entry for one (sole, book): full rows, rows by listing_key,
    and the slim list JSON once something has asked for it."""
    key = (show_sole, listing_type)
    version, fp = _db_version(), _jobs_fingerprint()
    now = time.monotonic()
    with _prospects_lock:
        hit = _prospects_cache.get(key)
    if hit:
        age = now - hit["built_at"]
        # Unchanged inputs keep the entry; the short floor stops a crawl,
        # which bumps data_version on every commit, from forcing a rebuild on
        # every poll; the ceiling lets days_on_market (computed against
        # now()) roll over on a database nobody is writing to.
        if age < _PROSPECTS_TTL or (
                age < _PROSPECTS_MAX_AGE
                and hit["version"] == version and hit["fingerprint"] == fp):
            return hit
    # Built outside the lock: two threads may race and both build, which is
    # wasted work but never a wrong answer.
    rows = _build_prospects(show_sole, listing_type)
    entry = {"built_at": time.monotonic(), "version": version,
             "fingerprint": fp, "rows": rows,
             "by_key": {r["listing_key"]: r for r in rows},
             "slim_json": None, "etag": None}
    with _prospects_lock:
        _prospects_cache[key] = entry
    return entry


def _prospects_payload(show_sole: bool, listing_type: str = "sale") -> list:
    return _prospects_entry(show_sole, listing_type)["rows"]


# Only read by the detail drawer, which fetches the whole row for one
# property from /api/prospect/<key>. Keeping them out of the list response
# is most of its size: reasoning, candidates and member listings are the
# bulk of every row, and the list/cards/filters never look at them.
_DETAIL_ONLY = {
    "reasoning", "red_flags", "erf_cands", "erf_note", "erf_ai", "evidence",
    "listings", "description", "match_evidence", "mandate_text",
    "official_suburb", "scored_by", "erf_lat", "erf_lng", "lat", "lng", "loc",
    "latitude", "longitude", "erf_portion", "erf_method", "erf_ai_status",
    "parcel_area_m2", "content_changed", "first_seen", "last_seen", "rates",
    "levies", "pool", "parking", "garages", "mandate_explicit",
    "reeval_error", "erf_ai_error", "source_count", "agency_count",
    "listing_date", "photo_count", "raw_overview"}


def _slim_json(entry: dict) -> tuple[bytes, str]:
    """The list response for one cache entry, serialised once.

    None values are dropped too (the client treats a missing key as null),
    but False/0 are kept: the cards test has_photo === false.
    """
    if entry["slim_json"] is None:
        slim = [{k: v for k, v in r.items()
                 if v is not None and k not in _DETAIL_ONLY}
                for r in entry["rows"]]
        body = json.dumps(slim, separators=(",", ":"), ensure_ascii=False,
                          default=str).encode("utf-8")
        # Assigned together, etag last: a racing reader sees either nothing
        # (and builds its own identical copy) or both.
        entry["slim_json"] = body
        entry["etag"] = hashlib.md5(body).hexdigest()
    return entry["slim_json"], entry["etag"]


# body bytes -> gzipped bytes, for the two big JSON responses. Keyed on the
# bytes object itself so a rebuilt payload is a new entry and the old one is
# collected with it. One entry per (book, sole) list and per map: tiny.
_gzip_cache: dict = {}
_gzip_lock = threading.Lock()


def _gzipped(body: bytes) -> bytes:
    with _gzip_lock:
        hit = _gzip_cache.get(id(body))
        if hit and hit[0] is body:
            return hit[1]
    import gzip
    gz = gzip.compress(body, compresslevel=5)
    with _gzip_lock:
        if len(_gzip_cache) > 8:
            _gzip_cache.clear()
        _gzip_cache[id(body)] = (body, gz)
    return gz


def _etag_response(body: bytes, etag: str) -> Response:
    """JSON bytes with an ETag, or a bodiless 304 when the client has them.

    no-cache (not no-store) so the browser keeps the copy but revalidates
    every time; the 304 then saves the whole transfer. The comparison is
    the weak one RFC 9110 prescribes for If-None-Match, so a proxy that
    weakens the tag (W/"...") after compressing still gets its 304.

    The body goes out gzipped when the client accepts it: a 15 MB list is
    ~2.3 MB on the wire, and compressing it here, once per build, means a
    phone on mobile data gets that regardless of what sits in front of the
    app (the Railway edge was compressing on the fly, per request).
    """
    if request.if_none_match.contains_weak(etag):
        rv = Response(status=304)
    elif "gzip" in (request.headers.get("Accept-Encoding") or "").lower():
        rv = Response(_gzipped(body), mimetype="application/json")
        rv.headers["Content-Encoding"] = "gzip"
    else:
        rv = Response(body, mimetype="application/json")
    rv.headers["Vary"] = "Accept-Encoding"
    rv.set_etag(etag)
    rv.headers["Cache-Control"] = "private, no-cache"
    return rv


def _book_args() -> tuple[bool, str]:
    # ?type=rent switches to the rental book. Anything else — including no
    # parameter at all, which is every caller that predates rentals — is the
    # for-sale view, unchanged.
    listing_type = "rent" if request.args.get("type") == "rent" else "sale"
    return request.args.get("sole") == "1", listing_type


@app.get("/api/prospects")
def api_prospects():
    body, etag = _slim_json(_prospects_entry(*_book_args()))
    return _etag_response(body, etag)


@app.get("/api/prospect/<path:listing_key>")
def api_prospect(listing_key):
    """One full row (every field the list response leaves out), for the
    detail drawer. Same ?sole / ?type meaning and same cache as the list."""
    row = _prospects_entry(*_book_args())["by_key"].get(listing_key)
    if row is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(row)


# Price-cut history is a whole-DB aggregate (~0.5s); lifecycle is one scan.
# Both only change when a crawl writes, so they are cached far longer than the
# prospects payload itself — /api/prospects is polled every 2s and during a
# crawl every one of those seconds is GIL time stolen from the scrapers.
_DEAL_CTX_TTL = 120.0
_deal_ctx_cache: tuple[float, dict, dict] | None = None
_deal_ctx_lock = threading.Lock()


def _deal_context() -> tuple[dict, dict]:
    """(price cuts, lifecycle) by listing_key — bulk, cached, never per row."""
    global _deal_ctx_cache
    now = time.monotonic()
    with _deal_ctx_lock:
        hit = _deal_ctx_cache
        if hit and now - hit[0] < _DEAL_CTX_TTL:
            return hit[1], hit[2]
    with db.connect() as conn:
        cuts = scorer.price_cut_history(conn)      # {} if the table is absent
        cycle = scorer.lifecycle_context(conn)     # {} if lifecycle never ran
    with _deal_ctx_lock:
        _deal_ctx_cache = (time.monotonic(), cuts, cycle)
    return cuts, cycle


def _build_prospects(show_sole: bool, listing_type: str = "sale") -> list:
    from sources.base import canonical_agency
    with db.connect() as conn:
        rows = conn.execute(
            PROSPECT_QUERY, {"listing_type": listing_type}).fetchall()
        # One GV-roll lookup for the whole response, not one per row — the
        # dashboard hits this endpoint every 2s while a job runs, and
        # for_groups() walks two tables per call.
        gv_by_group = valuations.for_groups(conn)
    cuts, cycle = _deal_context()

    grouped: dict = {}
    for r in rows:
        gid = r["group_id"] if r["group_id"] is not None else f"solo-{r['listing_key']}"
        grouped.setdefault(gid, []).append(r)

    out = []
    for members in grouped.values():
        best = max(members, key=lambda m: ((m["photo_count"] or 0),
                                           len(m["description"] or "")))
        # Rentals are never scored, so `sellable` is NULL on every one of
        # them and this sole-mandate filter has nothing to say about them.
        if not show_sole and best["sellable"] == 0:
            continue
        brands = {b for b in (canonical_agency(m["agency"]) for m in members) if b}
        d = dict(best)
        d.pop("raw_overview", None)
        d["description"] = (d.get("description") or "")[:300]
        d["brand_count"] = len(brands)
        d["agencies"] = sorted({m["agency"].strip() for m in members
                                if m["agency"] and m["agency"].strip()})
        d["listings"] = [{"source": m["source"], "url": m["url"],
                          "price_zar": m["price_zar"], "agency": m["agency"]}
                         for m in members]
        try:
            d["evidence"] = json.loads(best["match_evidence"] or "[]")[:3]
        except (ValueError, TypeError):
            d["evidence"] = []
        # erf resolution is written per group, so best's row speaks for all
        try:
            cands = json.loads(d.pop("erf_candidates", None) or "[]")
        except (ValueError, TypeError):
            cands = []
        d["erf_cand_count"] = len(cands)
        d["erf_cands"] = cands[:10]
        try:
            d["erf_ai"] = json.loads(d.pop("erf_ai_best", None) or "null")
        except (ValueError, TypeError):
            d["erf_ai"] = None
        job_state = _ai_jobs.get(best["listing_key"], {})
        d["erf_ai_running"] = bool(job_state.get("running"))
        d["erf_ai_error"] = job_state.get("error")
        d["reevaluating"] = any(
            _reeval_jobs.get(m["listing_key"], {}).get("running")
            for m in members)
        d["reeval_error"] = next(
            (_reeval_jobs[m["listing_key"]].get("error") for m in members
             if _reeval_jobs.get(m["listing_key"], {}).get("error")), None)
        # Days on market from the EARLIEST parseable listing date across the
        # group — the same basis the scorer feeds the AI, so the table and the
        # model's reasoning never disagree about how stale a listing is.
        listed = None
        for m in members:
            dt = scorer._parse_date(m["listing_date"])
            if dt and (listed is None or dt < listed):
                listed = dt
        d["days_on_market"] = (datetime.now() - listed).days if listed else None
        # Map position, most trustworthy source first: the resolved parcel's
        # centroid (cadastre fact), else any member's portal pin. `loc` says
        # which one won so the map can mark anything weaker as approximate.
        # Every candidate passes the South Africa sanity box — portals ship
        # the occasional junk pin (0-ish, or lat/lng swapped in ways the
        # parse-time fix can't catch) that would otherwise put a Camps Bay
        # villa in the Gulf of Guinea; those fall through to the suburb
        # centroid instead.
        def _sa(lat, lng):
            return (lat and lng and -35.5 < lat < -21.5 and 16.0 < lng < 33.5)
        d["lat"], d["lng"], d["loc"] = None, None, None
        if _sa(best["erf_lat"], best["erf_lng"]):
            d["lat"], d["lng"], d["loc"] = best["erf_lat"], best["erf_lng"], "erf"
        else:
            pin = next((m for m in members
                        if _sa(m["latitude"], m["longitude"])), None)
            if pin:
                d["lat"], d["lng"] = pin["latitude"], pin["longitude"]
                d["loc"] = "listing"
        d["region"] = config.SUBURBS.get(best["suburb_slug"], {}).get("region")
        # ---- deal signals, all read from the two bulk dicts (no per-row SQL).
        # Like the scorer, the group speaks with its loudest member's voice:
        # one portal showing the cut is proof the price moved.
        keys = [m["listing_key"] for m in members]
        cut = max((cuts.get(k, {}).get("total_cut_pct") or 0.0 for k in keys),
                  default=0.0)
        moves = max((cuts.get(k, {}).get("price_changes") or 0 for k in keys),
                    default=0)
        d["total_cut_pct"] = round(cut, 1) if cut > 0 else None
        d["price_changes"] = moves or None
        lc = [cycle.get(k) for k in keys]
        d["relisted"] = any(c and c["status"] == "relisted" for c in lc)
        off = []
        for c in lc:
            if not c or c["status"] != "relisted":
                continue
            gone = scorer._parse_date(c["delisted_at"])
            back = scorer._parse_date(c["relisted_at"])
            if gone and back and back > gone:
                off.append((back - gone).days)
        d["days_off_market"] = max(off) if off else None
        # Multi-brand proof is only as fresh as its stalest brand — a listing
        # a portal dropped weeks ago no longer proves anything about today.
        d["proof_age_hours"] = None
        if len(brands) > 1:
            age = scorer._proof_age_hours(members, sorted(brands))
            d["proof_age_hours"] = round(age, 1) if age is not None else None
        # Thumbnails: name the member that actually has a hero image, so the
        # card requests a photo that exists instead of a guaranteed 404.
        photo_key = next((m["listing_key"] for m in members
                          if (m["photo_url"] or "").strip() not in ("", "-")),
                         None)
        d["has_photo"] = photo_key is not None
        # Only when a SIBLING owns the image: /api/prospects is 30MB polled
        # every 2s, and a key that repeats listing_key earns nothing.
        if photo_key and photo_key != best["listing_key"]:
            d["photo_key"] = photo_key
        ppm2 = best["price_per_m2"]
        # Sales only: a rent divided by floor area is a different number in a
        # different unit, and the column header says "R/m²" asking price.
        if (not ppm2 and listing_type == "sale"
                and best["price_zar"] and best["floor_size_m2"]):
            ppm2 = best["price_zar"] / best["floor_size_m2"]
        d["price_per_m2"] = round(ppm2) if ppm2 else None
        gid = best["group_id"]
        val = gv_by_group.get(str(gid)) if gid is not None else None
        d["gv_value"] = (val or {}).get("market_value")
        d["gv_roll"] = (val or {}).get("roll")
        # Asking vs the municipal valuation — 1.0 is on the roll, 2.0 is double.
        d["price_vs_gv"] = (round(best["price_zar"] / d["gv_value"], 2)
                            if d["gv_value"] and best["price_zar"] else None)
        # Only real (integer) groups have a CMA page; solo listings carry the
        # synthetic 'solo-<key>' id and cma_web has nothing to render for them.
        d["cma_url"] = f"/cma/{gid}" if isinstance(gid, int) else None
        out.append(d)

    out.sort(key=lambda d: (-(d.get("prospect_score") or -1),
                            -(d.get("price_zar") or 0)))
    return out


# -------------------------------------------------------------------- map
#
# /map plots the prospect list. Position quality varies wildly by portal —
# a resolved erf gives a parcel centroid, some listings publish a pin, and
# prime Atlantic Seaboard stock frequently publishes nothing at all. Rather
# than dropping the addressless ones, they are GENERALISED: placed on their
# suburb's centroid (median of every located listing in that suburb) with a
# small deterministic jitter so a stack of them fans out, and flagged
# `loc: "suburb"` so the page renders them as approximate.
_SUBURB_CENTROID_TTL = 300.0
_suburb_centroids_cache: tuple[float, dict] | None = None


def _suburb_centroids() -> dict[str, tuple[float, float]]:
    global _suburb_centroids_cache
    now = time.monotonic()
    if _suburb_centroids_cache and now - _suburb_centroids_cache[0] < _SUBURB_CENTROID_TTL:
        return _suburb_centroids_cache[1]
    import statistics
    by_suburb: dict[str, tuple[list, list]] = {}
    with db.connect() as conn:
        for r in conn.execute(
                """SELECT suburb_slug, latitude, longitude FROM listings
                   WHERE listing_type = 'sale'
                     AND latitude IS NOT NULL AND longitude IS NOT NULL"""):
            # Sanity box for South Africa — a swapped or junk pin must not
            # drag a suburb's centroid into the ocean.
            if -35.5 < r["latitude"] < -21.5 and 16.0 < r["longitude"] < 33.5:
                lats, lngs = by_suburb.setdefault(r["suburb_slug"], ([], []))
                lats.append(r["latitude"])
                lngs.append(r["longitude"])
    cents = {slug: (statistics.median(lats), statistics.median(lngs))
             for slug, (lats, lngs) in by_suburb.items() if lats}
    _suburb_centroids_cache = (now, cents)
    return cents


@app.get("/api/map")
def api_map():
    """Every prospect as one map point, enriched enough to read at a glance.

    Deal signals (cut %, relisted, proof freshness, GV ratio, pitch) ride
    along so the page can render tooltips, badges and the dossier popup
    without a second round trip per pin.
    """
    show_sole = request.args.get("sole") == "1"
    rows = _prospects_payload(show_sole)
    centroids = _suburb_centroids()
    # ~7 MB of points, identical until either input is rebuilt, so it is
    # serialised once per (rows, centroids) pair. Identity, not id(): the
    # cached tuple holds both objects, so their ids can't be recycled.
    hit = _map_cache.get(show_sole)
    if hit and hit[0] is rows and hit[1] is centroids:
        return _etag_response(hit[2], hit[3])
    points, unmapped = [], 0
    for d in rows:
        lat, lng, loc = d.get("lat"), d.get("lng"), d.get("loc")
        if lat is None:
            c = centroids.get(d["suburb_slug"])
            if c:
                # ±~250m jitter, deterministic per group so pins don't hop
                # around between refreshes.
                h = int(hashlib.md5(
                    str(d["group_id"]).encode()).hexdigest()[:8], 16)
                lat = c[0] + ((h & 0xFFF) / 0xFFF - 0.5) * 0.005
                lng = c[1] + (((h >> 12) & 0xFFF) / 0xFFF - 0.5) * 0.005
                loc = "suburb"
            else:
                unmapped += 1
                continue
        pt = {
            "gid": d["group_id"], "key": d.get("photo_key") or d["listing_key"],
            "title": d.get("title"), "url": d.get("url"),
            "price_zar": d.get("price_zar"),
            "tier": d.get("tier") or "cold",
            "score": d.get("prospect_score"),
            "verdict": d.get("mandate_verdict") or "unknown",
            "suburb": d.get("suburb"),
            "region": d.get("region"),
            "lat": round(lat, 6), "lng": round(lng, 6), "loc": loc,
            "brand_count": d.get("brand_count"),
            "agencies": d.get("agencies") or [],
        }
        # Everything below is optional: at ~9k points a key that says "no"
        # costs as much on the wire as one that says something, so absent
        # means false/unknown and the page treats it that way.
        pitch = (d.get("pitch_angle") or "").strip()
        for k, v in (
                ("sellable", d.get("sellable")),
                ("under_offer", bool(d.get("under_offer"))),
                ("price_reduced", bool(d.get("price_reduced"))),
                ("relisted", bool(d.get("relisted"))),
                ("has_photo", bool(d.get("has_photo"))),
                ("days_on_market", d.get("days_on_market")),
                ("days_off_market", d.get("days_off_market")),
                ("bedrooms", d.get("bedrooms")),
                ("property_type", d.get("property_type")),
                ("expiry_note", d.get("mandate_expiry_note")),
                ("total_cut_pct", d.get("total_cut_pct")),
                ("price_changes", d.get("price_changes")),
                ("proof_age_hours", d.get("proof_age_hours")),
                ("gv_value", d.get("gv_value")),
                ("price_vs_gv", d.get("price_vs_gv")),
                ("floor_size_m2", d.get("floor_size_m2")),
                ("price_per_m2", d.get("price_per_m2")),
                ("luxury_fit", d.get("luxury_fit")),
                ("open_conf", d.get("open_mandate_confidence")),
                ("marketing_weakness", d.get("marketing_weakness")),
                ("pitch", pitch[:200] + ("…" if len(pitch) > 200 else "")),
                ("cma", 1 if d.get("cma_url") else 0)):
            if v:
                pt[k] = v
        points.append(pt)
    # Byte-for-byte what jsonify() produced (same provider, compact, trailing
    # newline), just kept.
    body = (app.json.dumps({"points": points, "unmapped": unmapped},
                           separators=(",", ":")) + "\n").encode("utf-8")
    etag = hashlib.md5(body).hexdigest()
    _map_cache[show_sole] = (rows, centroids, body, etag)
    return _etag_response(body, etag)


# show_sole -> (rows, centroids, body, etag); see api_map.
_map_cache: dict = {}


_MAP_PATH = os.path.join(config.ROOT, "map.html")

# The SvelteKit front end prerenders to ui/build (index.html, map.html, the
# _app/ asset directory, favicon.svg). When that build is present it serves
# the pages; without it — a fresh checkout, or before `npm run build` — the
# legacy single-file dashboard.html and map.html still answer, so the app
# never depends on a Node toolchain being installed.
_UI_BUILD = os.path.join(config.ROOT, "ui", "build")


@app.get("/map")
def map_page():
    if os.path.exists(os.path.join(_UI_BUILD, "map.html")):
        return send_from_directory(_UI_BUILD, "map.html")
    with open(_MAP_PATH, encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------- erf / cadastre jobs
#
# Bulk resolution talks to the public CoCT cadastre (fast, free); the AI
# locator downloads listing photos + satellite crops and asks a vision model
# to rank candidate parcels — seconds to a minute per property, so both run
# in background threads and the dashboard polls /api/erf/busy.
#
# /api/prospects is polled every 2s by the dashboard and a full build is ~3s
# of GIL-holding query + grouping work, so builds are cached per database
# version (see _prospects_entry). _PROSPECTS_TTL is the floor an entry lives
# regardless: during a crawl data_version moves on every commit, and without
# it each poll would rebuild. _PROSPECTS_MAX_AGE is the ceiling, so the
# now()-relative fields (days_on_market) still roll over when nothing writes.
_PROSPECTS_TTL = 1.5
_PROSPECTS_MAX_AGE = 600.0
_prospects_cache: dict = {}
_prospects_lock = threading.Lock()

_erf_job = {"running": False}
_ai_jobs: dict[str, dict] = {}
_reeval_jobs: dict[str, dict] = {}


@app.post("/api/erf/resolve")
@auth.require_priv("crawl")
def api_erf_resolve():
    if _erf_job["running"]:
        return jsonify({"error": "erf resolution already running"}), 409
    force = bool((request.get_json(silent=True) or {}).get("force"))

    def work():
        try:
            log("erf: resolving against the City of Cape Town cadastre "
                "(metro) and the Western Cape provincial cadastre "
                "(everywhere else)…")
            with db.connect() as conn:
                s = erf.resolve_all(conn, force=force, retry_failed=True,
                                    log=log)
            log(f"erf: {s['resolved']} exact, {s['check']} to verify, "
                f"{s['candidates']} with candidates, "
                f"{s['unresolved']} unresolved, {s['skipped']} already done")
        except Exception as e:            # noqa: BLE001
            log(f"erf ERROR: {type(e).__name__}: {e}")
        finally:
            _erf_job["running"] = False

    _erf_job["running"] = True
    threading.Thread(target=work, daemon=True).start()
    return jsonify({"ok": True})


@app.post("/api/erf/locate")
@auth.require_priv("crawl")
def api_erf_locate():
    key = (request.get_json(silent=True) or {}).get("listing_key")
    if not key:
        return jsonify({"error": "listing_key required"}), 400
    if _ai_jobs.get(key, {}).get("running"):
        return jsonify({"error": "already locating this property"}), 409

    def work():
        try:
            erf.ai_locate(key, log=log)
            _ai_jobs[key] = {"running": False}
        except Exception as e:            # noqa: BLE001
            log(f"ai-locate ERROR: {type(e).__name__}: {e}")
            _ai_jobs[key] = {"running": False,
                             "error": f"{type(e).__name__}: {e}"}

    _ai_jobs[key] = {"running": True}
    log(f"ai-locate: started for {key}")
    threading.Thread(target=work, daemon=True).start()
    return jsonify({"ok": True})


_locate_all_job = {"running": False, "stop": threading.Event()}


@app.post("/api/erf/locate-all")
@auth.require_priv("crawl")
def api_erf_locate_all():
    """Run the AI photo-locator over every candidate property — on demand.

    Deliberately not part of any crawl (config.AI_LOCATE_AUTO): each
    property is a paid vision call, and a full backlog is hours of them.
    """
    if _locate_all_job["running"]:
        return jsonify({"error": "bulk locate already running"}), 409
    _locate_all_job["stop"].clear()

    def work():
        try:
            s = erf.ai_locate_all(log=log, stop=_locate_all_job["stop"])
            log(f"ai-locate: bulk run done — {s['located']} located, "
                f"{s['errors']} failed of {s['groups']} candidates")
        except Exception as e:            # noqa: BLE001
            log(f"ai-locate bulk ERROR: {type(e).__name__}: {e}")
        finally:
            _locate_all_job["running"] = False

    _locate_all_job["running"] = True
    threading.Thread(target=work, daemon=True).start()
    return jsonify({"ok": True})


@app.post("/api/erf/locate-all/stop")
@auth.require_priv("crawl")
def api_erf_locate_all_stop():
    _locate_all_job["stop"].set()
    log("ai-locate: bulk stop requested — finishing current property")
    return jsonify({"ok": True})


@app.get("/api/erf/busy")
def api_erf_busy():
    return jsonify({"resolving": _erf_job["running"],
                    "locating_all": _locate_all_job["running"],
                    "locating": [k for k, v in _ai_jobs.items()
                                 if v.get("running")],
                    "reevaluating": [k for k, v in _reeval_jobs.items()
                                     if v.get("running")]})


@app.post("/api/listing/reevaluate")
@auth.require_priv("crawl")
def api_listing_reevaluate():
    """Refetch one property from its portal(s), then re-score and re-resolve.

    The per-row "re-eval" button: forces live fetches (cache dropped for the
    detail URLs), re-parses with the current parsers — which is also how a
    listing stored with a mis-parsed size gets corrected — re-groups, asks
    the AI for a fresh score, and re-runs the cadastre erf match.
    """
    key = (request.get_json(silent=True) or {}).get("listing_key")
    if not key:
        return jsonify({"error": "listing_key required"}), 400
    if _reeval_jobs.get(key, {}).get("running"):
        return jsonify({"error": "already re-evaluating this property"}), 409

    def work():
        try:
            with db.connect() as conn:
                members = [dict(m) for m in
                           scorer.group_for_listing(conn, key)]
                if not members:
                    members = [dict(r) for r in conn.execute(
                        "SELECT * FROM listings WHERE listing_key = ?", (key,))]
                if not members:
                    raise ValueError(f"unknown listing {key}")

                log(f"re-eval: refetching {len(members)} portal page(s)…")
                srcs: dict = {}
                for m in members:
                    name = m["source"]
                    if name not in srcs:
                        srcs[name] = source_registry.build(name, logger=log)
                    src = srcs[name]
                    # Drop the cached page so the portal is asked live —
                    # a stale price or a delisting must show up here.
                    try:
                        os.remove(src.fetcher._cache_path(m["url"]))
                    except OSError:
                        pass
                    try:
                        listing = src.parse_detail(m["url"], m["suburb_slug"])
                    except Exception as e:              # noqa: BLE001
                        log(f"re-eval: [{src.label}] parse failed "
                            f"{type(e).__name__}: {e}")
                        listing = None
                    if listing:
                        db.upsert_listing(conn, listing)
                        conn.commit()
                        log(f"re-eval: [{src.label}] refreshed — "
                            f"{(listing.get('title') or '')[:60]}")
                    else:
                        log(f"re-eval: [{src.label}] no data for {m['url']} "
                            "(possibly delisted)")

                dedupe.rebuild_groups(conn)
                conn.commit()

                fresh = scorer.group_for_listing(conn, key)
                if fresh:
                    res = scorer.score_members(
                        conn, fresh, backends=scorer.build_backends(True))
                    conn.commit()
                    log(f"re-eval: re-scored — {res.get('tier', '?')} "
                        f"{res.get('prospect_score')}")

                try:
                    er = erf.resolve_one(conn, key)
                    log(f"re-eval: erf {er['status']}"
                        + (f" — erf {er['erf_number']}, "
                           f"{er['official_address']}"
                           if er.get("erf_number") else ""))
                except Exception as e:                  # noqa: BLE001
                    log(f"re-eval: erf lookup failed "
                        f"{type(e).__name__}: {e}")
            _reeval_jobs[key] = {"running": False}
            log(f"re-eval: done for {key}")
        except Exception as e:                          # noqa: BLE001
            log(f"re-eval ERROR: {type(e).__name__}: {e}")
            _reeval_jobs[key] = {"running": False,
                                 "error": f"{type(e).__name__}: {e}"}

    _reeval_jobs[key] = {"running": True}
    log(f"re-eval: started for {key}")
    threading.Thread(target=work, daemon=True).start()
    return jsonify({"ok": True})


@app.post("/api/erf/confirm")
@auth.require_priv("crawl")
def api_erf_confirm():
    body = request.get_json(silent=True) or {}
    try:
        with db.connect() as conn:
            res = erf.confirm(conn, body.get("listing_key"), body.get("erf"))
        log(f"erf: confirmed erf {res['erf_number']} — "
            f"{res['official_address']}, {res['official_suburb']}")
        return jsonify(res)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/photo/<path:listing_key>")
def api_photo(listing_key):
    """Hero-image redirect for a listing; resolved lazily and remembered.

    Thumbnails point here so the page never blocks on portal fetches: the
    common case is a stored URL (crawl-time capture or a previous resolve) and
    costs one redirect. On a miss the listing page is fetched — cache first,
    then network, serialised per portal — which fills the column for good.

    ?fetch=0 stays off the network entirely (stored URL or page cache only).
    The map page uses it: hundreds of cards resolving thumbnails at once must
    not fan out into hundreds of live portal fetches.
    """
    allow_fetch = request.args.get("fetch") != "0"
    with db.connect() as conn:
        url = photos.first_photo(conn, listing_key, allow_fetch=allow_fetch)
    if url:
        return redirect(url, code=302)
    return ("", 404)


@app.get("/api/row/<ident>")
def api_row(ident):
    """A tab-separated spreadsheet row for one property.

    Tab-separated because that is what Excel and Google Sheets both paste
    across columns — no API, no credentials. See sheets.py.
    """
    import sheets
    cols = request.args.get("cols")
    columns = sheets.parse_columns(cols) if cols else None
    with db.connect() as conn:
        fields = sheets.fields_for(conn, ident)
    if not fields:
        return jsonify({"error": f"no property for {ident}"}), 404
    return jsonify({
        "row": sheets.tsv_row(fields, columns),
        "header": sheets.tsv_header(columns),
        "columns": [h for _, h in (columns or sheets.COLUMNS)],
    })


@app.get("/api/config")
def api_config():
    """Suburb and portal pickers as JSON — what the page needs to render them.

    Same shapes the legacy dashboard gets inlined at render time, so the
    SvelteKit front end reads one endpoint instead of a templated page.
    """
    # regions() is moving to 3-tuples (slug, name, scope) with whole-town
    # entries listed first; until every checkout carries that change, pad
    # 2-tuples with scope="suburb" so the page renders either way.
    subs = {
        region: [[t[0], t[1], t[2] if len(t) > 2 else "suburb"] for t in items]
        for region, items in config.regions().items()}
    srcs = [[n, config.SOURCES[n]["label"],
             bool(config.SOURCES[n].get("enabled")),
             config.SOURCES[n].get("blocked_reason", "")]
            for n in source_registry.REGISTRY if n in config.SOURCES]
    return jsonify({"suburbs": subs, "sources": srcs})


@app.post("/api/find")
def api_find():
    """Plain-English brief -> recommended areas + properties (finder.py).
    Body: {brief, sole, type}. type 'rent' briefs against the to-rent book —
    monthly rent, furnishing, occupation date — and anything else, including
    no type at all (every caller that predates rentals), is the for-sale
    book, unchanged. Synchronous: two model calls, ~10-30s with AI, instant
    on the keyword fallback."""
    body = request.get_json(silent=True) or {}
    listing_type = "rent" if body.get("type") == "rent" else "sale"
    rows = _prospects_payload(bool(body.get("sole")), listing_type)
    try:
        return jsonify(finder.recommend(body.get("brief") or "", rows,
                                        listing_type=listing_type))
    except ValueError as e:
        return jsonify({"error": "bad_brief", "message": str(e)}), 400
    except Exception as e:      # noqa: BLE001 — surface it in the UI, not a 500 page
        return jsonify({"error": "find_failed",
                        "message": f"{type(e).__name__}: {e}"}), 500


@app.post("/api/agent")
def api_agent():
    """Agent Z — the finder as a conversation (agent_z.py).

    Body: {messages: [{role, content}, …], sole, type}. Stateless: the client
    posts the whole thread each turn and the server keeps none of it. `type`
    pins the book when the caller knows it; left off, Z reads the thread and
    decides sale or rent itself — which is why the payload is built lazily,
    one book only, through the same cached helper /api/prospects uses.
    Synchronous: two model calls, ~10-30s with AI, instant on the keyword
    fallback."""
    body = request.get_json(silent=True) or {}
    sole = bool(body.get("sole"))
    pinned = body.get("type") if body.get("type") in ("sale", "rent") else None
    try:
        return jsonify(agent_z.respond(
            body.get("messages") or [],
            lambda t: _prospects_payload(sole, t),
            listing_type=pinned))
    except ValueError as e:
        return jsonify({"error": "bad_message", "message": str(e)}), 400
    except Exception as e:      # noqa: BLE001 — surface it in the chat, not a 500 page
        return jsonify({"error": "agent_failed",
                        "message": f"{type(e).__name__}: {e}"}), 500


# ------------------------------------------------------------- team chat
#
# The floating widget on every page is the agents talking to each other —
# Agent Z is /api/agent and a different thing entirely. Deliberately plain:
# no sockets, no read receipts, no accounts. The client polls with the id of
# the last message it holds and gets whatever landed since.

_CHAT_TAIL = 100          # how far back a cold open reads
_CHAT_MAX = 200           # cap on one catch-up, so a long absence is not a flood
_CHAT_BODY_MAX = 2000
_CHAT_SENDER_MAX = 40

# C0 controls and DEL, minus tab and newline: a message may be several lines,
# but nothing in it should be able to move a cursor or ring a terminal bell.
_CHAT_CTRL = {c: None for c in list(range(32)) + [127] if c not in (9, 10)}


def _chat_body(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return text.translate(_CHAT_CTRL).strip()[:_CHAT_BODY_MAX]


def _chat_sender(value: str) -> str:
    """One line, whitespace collapsed — a name, not a paragraph."""
    text = str(value or "").translate(_CHAT_CTRL)
    return " ".join(text.split())[:_CHAT_SENDER_MAX]


def _chat_row(r) -> dict:
    return {"id": r["id"], "sender": r["sender"], "body": r["body"],
            "at": r["created_at"]}


@app.get("/api/chat")
def api_chat():
    """Team chat: messages after `after`, or the tail of the book without it.

    Always ascending, so the client can append. `latest` is the newest id in
    the table — the cursor to send back next time, and what tells a client
    holding nothing that there is nothing to hold.
    """
    raw = request.args.get("after")
    try:
        after = int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        after = None
    with db.connect() as conn:
        if after is None:
            rows = conn.execute(
                "SELECT * FROM team_chat ORDER BY id DESC LIMIT ?",
                (_CHAT_TAIL,)).fetchall()[::-1]
        else:
            rows = conn.execute(
                "SELECT * FROM team_chat WHERE id > ? ORDER BY id ASC LIMIT ?",
                (after, _CHAT_MAX)).fetchall()
        latest = conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM team_chat").fetchone()[0]
    return jsonify({"messages": [_chat_row(r) for r in rows], "latest": latest})


@app.post("/api/chat")
def api_chat_say():
    """Post one message. Body: {sender, body}. Returns the stored row, so the
    sender's own message appears with the id and timestamp everyone else will
    see rather than an optimistic local copy."""
    payload = request.get_json(silent=True) or {}
    body = _chat_body(payload.get("body"))
    if not body:
        return jsonify({"error": "empty_message",
                        "message": "Nothing to send."}), 400
    sender = _chat_sender(payload.get("sender")) or "Someone"
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO team_chat (sender, body, created_at) VALUES (?, ?, ?)",
            (sender, body, at))
        mid = cur.lastrowid
    return jsonify({"message": {"id": mid, "sender": sender,
                                "body": body, "at": at}})


@app.get("/api/stats")
def api_stats():
    with db.connect() as conn:
        def one(sql):
            return conn.execute(sql).fetchone()[0]
        return jsonify({
            # The headline stat has always meant "for-sale listings"; keeping
            # it that way stops a rental crawl from silently inflating it.
            "listings": one("SELECT COUNT(*) FROM listings"
                            " WHERE listing_type='sale'"),
            "rentals": one("SELECT COUNT(*) FROM listings"
                           " WHERE listing_type='rent'"),
            "properties": one("SELECT COUNT(DISTINCT group_id) FROM property_groups"),
            "sellable": one("SELECT COUNT(DISTINCT g.group_id) FROM scores s"
                            " JOIN property_groups g ON g.listing_key=s.listing_key"
                            " WHERE COALESCE(s.sellable,1)=1"),
            "sole": one("SELECT COUNT(DISTINCT g.group_id) FROM scores s"
                        " JOIN property_groups g ON g.listing_key=s.listing_key"
                        " WHERE s.sellable=0"),
            "multi_agency": one("SELECT COUNT(DISTINCT group_id) FROM"
                                " property_groups WHERE agency_count>1"),
            "erf_ready": one("SELECT COUNT(DISTINCT group_id) FROM erf_lookup"
                             " WHERE status IN ('ok','check','confirmed')"),
            "by_source": {r[0]: r[1] for r in conn.execute(
                "SELECT source, COUNT(*) FROM listings"
                " WHERE listing_type='sale' GROUP BY source")},
        })


# ---------------------------------------------------------------- dashboard
#
# The dashboard page lives in dashboard.html next to this file and is re-read
# on every request, so markup/CSS/JS edits show on a plain browser refresh —
# no server restart, and no thousand-line HTML string cluttering this module.
_DASHBOARD_PATH = os.path.join(config.ROOT, "dashboard.html")


def _legacy_dashboard():
    with open(_DASHBOARD_PATH, encoding="utf-8") as f:
        page = f.read()
    # regions() is moving to 3-tuples (slug, name, scope) with whole-town
    # entries listed first; until every checkout carries that change, pad
    # 2-tuples with scope="suburb" so the page renders either way.
    subs = json.dumps({
        region: [[t[0], t[1], t[2] if len(t) > 2 else "suburb"] for t in items]
        for region, items in config.regions().items()})
    srcs = json.dumps([[n, config.SOURCES[n]["label"],
                        bool(config.SOURCES[n].get("enabled")),
                        config.SOURCES[n].get("blocked_reason", "")]
                       for n in source_registry.REGISTRY if n in config.SOURCES])
    return page.replace("__SUBURBS__", subs).replace("__SOURCES__", srcs)


@app.get("/")
def index():
    if os.path.exists(os.path.join(_UI_BUILD, "index.html")):
        return send_from_directory(_UI_BUILD, "index.html")
    return _legacy_dashboard()


@app.get("/prospects")
def prospects_page():
    return send_from_directory(_UI_BUILD, "prospects.html")


@app.get("/agent")
def agent_page():
    """Agent Z — the conversational finder. Prerendered like /prospects."""
    return send_from_directory(_UI_BUILD, "agent.html")


@app.get("/account")
def account_page():
    """Passkeys and signed-in sessions. Prerendered like /prospects."""
    return send_from_directory(_UI_BUILD, "account.html")


@app.get("/leads")
def leads_page():
    return send_from_directory(_UI_BUILD, "leads.html")


@app.get("/leads/<path:_rest>")
def leads_subpage(_rest):
    # Prerendered where possible, else the SPA shell reads the real URL.
    f = os.path.join(_UI_BUILD, "leads", _rest + ".html")
    if os.path.exists(f):
        return send_from_directory(_UI_BUILD, os.path.join("leads", _rest + ".html"))
    return send_from_directory(_UI_BUILD, "200.html")


@app.get("/properties")
@app.get("/properties/<path:_rest>")
def properties_redirect(_rest=""):
    return redirect("/leads/properties" + ("/" + _rest if _rest else ""))


# ------------------------------------------------------------------- media
#
# The Media section is the vendored Zerko library (zerko/, mounted at /zerko
# by media.py). These routes are only the front end: the SvelteKit pages, the
# token the client needs to talk to the mounted API, and the standalone
# share page a client opens with no password at all.

@app.get("/media")
def media_page():
    return send_from_directory(_UI_BUILD, "media.html")


@app.get("/media/<path:_rest>")
def media_subpage(_rest):
    # /media/s/<token> is Flask-rendered (below) and never reaches here.
    f = os.path.join(_UI_BUILD, "media", _rest + ".html")
    if os.path.exists(f):
        return send_from_directory(_UI_BUILD, os.path.join("media", _rest + ".html"))
    return send_from_directory(_UI_BUILD, "200.html")


@app.get("/api/media/token")
@auth.require_priv("media")
def api_media_token():
    """Mint a Zerko bearer token for whoever is already signed in here.

    There is no second login: the dashboard's own sign-in is the
    authentication event, and this turns it into the JWT the mounted FastAPI
    app expects. The Zerko account is created on first use and its role
    follows the dashboard: `media` + `admin` is a Zerko admin, `media` alone
    an editor (media.zerko_role_for). Holding `media` is what it takes to get
    a token at all. A GET, but not a read: it hands out a credential.
    """
    basic = request.authorization
    user = ((basic.username if basic else None)
            or auth.current_user(request) or _DASH_USER)
    payload, err = media.mint_token(user)
    if err:
        return jsonify({"error": err, **media.status()}), 503
    return jsonify(payload)


@app.get("/api/media/status")
def api_media_status():
    """Whether the backend imported and whether there is a footage drive —
    what the Media pages need to explain themselves instead of looking
    broken."""
    return jsonify(media.status())


@app.get("/hero-<name>.jpg")
def ui_hero(name):
    return send_from_directory(_UI_BUILD, f"hero-{name}.jpg")


@app.get("/legacy")
def legacy_dashboard():
    """The pre-SvelteKit dashboard, still reachable once the build takes over."""
    return _legacy_dashboard()


@app.get("/_app/<path:p>")
def ui_assets(p):
    # send_from_directory 404s on its own when the build directory is absent.
    return send_from_directory(os.path.join(_UI_BUILD, "_app"), p)


@app.get("/favicon.svg")
def ui_favicon():
    return send_from_directory(_UI_BUILD, "favicon.svg")


_HERO_PATH = re.compile(r"^/hero-[^/]+\.jpg$")


@app.after_request
def _cache_headers(rv):
    """Browser caching for the front end's static files.

    /_app/immutable/ is SvelteKit output with a content hash in every file
    name, so a changed file is a new URL and the old one can be kept
    forever. Hero images and the favicon change rarely: a week, then the
    ETag/Last-Modified send_from_directory emits revalidates them. HTML
    pages are no-cache so a redeploy shows on the next load. Anything a view
    already gave a Cache-Control of its own (the ETag'd JSON) is left alone,
    as is every other response.
    """
    path = request.path
    if rv.status_code not in (200, 304):
        return rv
    if path.startswith("/_app/immutable/"):
        rv.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path == "/favicon.svg" or _HERO_PATH.match(path):
        rv.headers["Cache-Control"] = "public, max-age=604800"
    elif (request.method == "GET" and rv.mimetype == "text/html"
          and "Cache-Control" not in rv.headers):
        rv.headers["Cache-Control"] = "no-cache"
    return rv


# --------------------------------------------------------------- CMA pages
#
# The CMA feature lives at its own URLs (/cma, /cma/<group_id>) — the main
# dashboard above is untouched. All HTML for these pages is rendered by
# cma_web.py; auth is covered by the app-wide _require_auth before_request.
import brief          # noqa: E402
import caller         # noqa: E402
import cma            # noqa: E402  (kept below the dashboard on purpose)
import cma_web        # noqa: E402
import owners         # noqa: E402
import panel          # noqa: E402
import share_page     # noqa: E402
import valuations     # noqa: E402

app.register_blueprint(auth.bp)
app.register_blueprint(panel.bp)
app.register_blueprint(caller.bp)
app.register_blueprint(share_page.bp)
caller.start_autopilot()   # no-op unless CALLER_AUTOPILOT=1

# The call-brief cache, created once at boot rather than per request: unlike
# the panel's tables nothing writes to it outside the brief endpoints, so one
# CREATE IF NOT EXISTS here covers every reader.
with db.connect() as _boot_conn:
    brief.ensure_schema(_boot_conn)
    # Accounts, invites and the passkeys/sessions migrations. At boot rather
    # than on the first sign-in so an upgrade of a running single-account
    # deployment adopts its existing passkeys and sessions before anyone
    # knocks — including a browser that is already holding a cookie.
    auth.ensure_schema(_boot_conn)

# The media library, adapted from ASGI and hung off this same WSGI stack at
# /zerko. Last, because DispatcherMiddleware wraps whatever wsgi_app is at the
# time — every Flask route above must already be registered. Importing the
# backend itself is deferred to the first /zerko request, so a checkout
# without the media dependencies (or a deploy without a footage drive) starts
# and serves the prospecting dashboard exactly as before.
media.set_guard(_wsgi_authorised)
# Roles and permissions (Zerko v1.2) follow the dashboard: media.role_for()
# turns these privileges into the Zerko role each mirror account holds.
media.set_privileges(
    lambda u: auth.PRIVILEGES if (u or "").lower() == _DASH_USER.lower()
    else auth.privileges_for(u))
media.mount(app)


@app.get("/cma")
def cma_index():
    with db.connect() as conn:
        return cma_web.render_index(conn)


@app.get("/cma/<int:group_id>")
def cma_report(group_id: int):
    with db.connect() as conn:
        page = cma_web.render_report(conn, group_id)
    if page is None:
        return Response(f"property group {group_id} not found", 404,
                        {"Content-Type": "text/plain"})
    return page


@app.get("/cma/<int:group_id>/download")
def cma_download(group_id: int):
    """The same report as a standalone HTML file the agent can keep or send.

    Owner details and other internal-only blocks are omitted (client=True) —
    a downloaded file leaves the building, so it must be safe to forward.
    """
    with db.connect() as conn:
        page = cma_web.render_report(conn, group_id, client=True)
    if page is None:
        return Response(f"property group {group_id} not found", 404,
                        {"Content-Type": "text/plain"})
    return Response(page, headers={
        "Content-Type": "text/html; charset=utf-8",
        "Content-Disposition":
            f'attachment; filename="cma-report-{group_id}.html"'})


@app.get("/api/cma/<int:group_id>")
def api_cma(group_id: int):
    with db.connect() as conn:
        result = cma.analyse(conn, group_id)
    if result is None:
        return jsonify({"error": f"property group {group_id} not found"}), 404
    return jsonify(result)


@app.route("/api/owner/<group_id>", methods=["GET", "POST", "DELETE"])
def api_owner(group_id):
    # One route, three verbs: reading an owner's details is open to everyone
    # signed in (the whole dashboard is), writing or purging them is `leads`.
    if request.method != "GET" and not auth.has_priv("leads"):
        return auth.forbidden("leads")
    with db.connect() as conn:
        owners.ensure_table(conn)
        if request.method == "GET":
            return jsonify(owners.get(conn, group_id) or {})
        if request.method == "DELETE":
            deleted = owners.delete(conn, group_id)
            log(f"owner: purged details for group {group_id}"
                if deleted else f"owner: nothing stored for group {group_id}")
            return jsonify({"deleted": deleted})
        body = request.get_json(silent=True) or {}
        fields = {k: v for k, v in body.items() if k in owners.FIELDS}
        try:
            row = owners.set_manual(conn, group_id, **fields)
        except Exception as e:                          # noqa: BLE001
            return jsonify({"error": e.args[0] if e.args else str(e)}), 400
        return jsonify(row)


@app.post("/api/deed/<group_id>")
@auth.require_priv("leads")
def api_deed(group_id):
    """Fetch registered-owner + deed info from LOOM for one property group.

    Resolves the group's erf/suburb/SG code from erf_lookup, calls LOOM, and
    persists the result into owner_details (same store owners.set_manual uses),
    so a fetched owner shows up everywhere the manual capture does.
    """
    import loom  # kept local: pulls no browser deps, only requests
    with db.connect() as conn:
        owners.ensure_table(conn)
        # Match on the group's current listing keys, not erf_lookup.group_id:
        # dedupe renumbers groups on every run, so the id stamped at erf time
        # drifts (e.g. 3132 vs 3133) while the listing_key stays stable. Solo
        # groups come through as 'solo-<listing_key>'.
        gid = str(group_id)
        erf = conn.execute(
            "SELECT e.erf_number, e.official_suburb, e.sg26_code FROM erf_lookup e "
            "WHERE e.status IN ('ok','confirmed','check') AND e.erf_number IS NOT NULL "
            "AND (e.listing_key IN (SELECT listing_key FROM property_groups "
            "                        WHERE CAST(group_id AS TEXT) = ?) "
            "     OR e.listing_key = ? OR e.group_id = ?) "
            "ORDER BY e.status = 'confirmed' DESC LIMIT 1",
            (gid, gid[5:] if gid.startswith("solo-") else "", gid)).fetchone()
        if not erf:
            return jsonify({"error": "no_erf",
                            "message": "Resolve this property's erf number first."}), 400
        try:
            data = loom.fetch_deed(erf=erf["erf_number"],
                                   town=erf["official_suburb"],
                                   sg26_code=erf["sg26_code"])
        except loom.LoomAuthError as e:
            return jsonify({"error": "loom_auth", "message": str(e)}), 503
        except loom.LoomError as e:
            return jsonify({"error": "loom", "message": str(e)}), 502

        fields = {k: data.get(k) for k in owners.FIELDS
                  if k != "notes" and data.get(k) is not None}
        fields["notes"] = (f"LOOM · erf {erf['erf_number']} {erf['official_suburb']}"
                           + (f" · {data['owner_type']}" if data.get("owner_type") else ""))
        try:
            row = owners.set_manual(conn, str(group_id), **fields)
        except Exception as e:                          # noqa: BLE001
            return jsonify({"error": e.args[0] if e.args else str(e)}), 400
        panel.record_owner(conn, str(group_id), data, fields["notes"])
        log(f"deed: LOOM lookup for group {group_id} → "
            f"{data.get('owner_name') or 'no owner'} ({data.get('deed_number') or '—'})")
        return jsonify({**row, "owner_type": data.get("owner_type"),
                        "town_name": data.get("town_name")})


# ------------------------------------------------------------- call briefs
#
# The sheet an agent reads before phoning an owner. Everything deterministic
# is free and instant; the AI rewrite is a separate POST so nothing spends a
# model call just because a drawer was opened.

@app.get("/api/brief/<gid>")
def api_brief(gid: str):
    with db.connect() as conn:
        body = brief.build(conn, gid, refresh=request.args.get("refresh") == "1")
    if body is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(body)


@app.post("/api/brief/<gid>/ai")
def api_brief_ai(gid: str):
    ok, reason = scorer.ai_status()
    if not ok:
        return jsonify({"error": "ai_unavailable", "message": reason}), 503
    # Synchronous: finder's calls are capped well inside gunicorn's 120s, and
    # a job + poll would be more machinery than one round-trip deserves.
    with db.connect() as conn:
        body = brief.build(conn, gid, want_ai=True, refresh=True)
    if body is None:
        return jsonify({"error": "not_found"}), 404
    if not body.get("ai"):
        ok, reason = scorer.ai_status()
        return jsonify({"error": "ai_unavailable",
                        "message": reason or "no provider answered"}), 503
    return jsonify(body)


@app.get("/api/brief/<gid>/text")
def api_brief_text(gid: str):
    with db.connect() as conn:
        body = brief.build(conn, gid)
    if body is None:
        return jsonify({"error": "not_found"}), 404
    return Response(brief.to_text(body), 200,
                    {"Content-Type": "text/plain; charset=utf-8"})


@app.get("/brief/<gid>")
def brief_page(gid: str):
    """Standalone page for the phone in the agent's other hand."""
    with db.connect() as conn:
        body = brief.build(conn, gid)
    if body is None:
        return Response("No such property.", 404,
                        {"Content-Type": "text/plain; charset=utf-8"})
    return Response(brief.render_page(body), 200,
                    {"Content-Type": "text/html; charset=utf-8"})


@app.get("/api/deed/status")
def api_deed_status():
    import loom
    return jsonify(loom.token_status())


@app.post("/api/gv/refresh")
@auth.require_priv("crawl")
def api_gv_refresh():
    # Runs synchronously on purpose: after the first crawl every lookup is
    # served from the 90-day disk cache (~22 cached hits, no network), so a
    # background job + polling would be more machinery than the work itself.
    force = bool((request.get_json(silent=True) or {}).get("force"))
    try:
        with db.connect() as conn:
            counts = valuations.resolve_all(conn, force=force, progress=log)
    except Exception as e:                              # noqa: BLE001
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502
    return jsonify(counts)


if __name__ == "__main__":
    # Hosted platforms inject $PORT and require binding all interfaces.
    # Locally stay on loopback so the dashboard isn't exposed on the LAN.
    port = int(os.environ.get("PORT", 5051))
    host = "0.0.0.0" if _IS_HOSTED else "127.0.0.1"
    app.run(host=host, port=port, debug=False)
