"""Local web dashboard for the prospecting engine.

    source .venv/bin/activate && python webapp.py
    -> http://localhost:5051

Pick suburbs and portals, hit Scrape, watch all five crawls run in parallel,
then browse the ranked prospects. Sole-mandate properties are hidden by
default because Oblivion cannot win business on them.
"""

from __future__ import annotations

import hmac
import json
import os
import threading
import time
from datetime import datetime

from flask import Flask, Response, jsonify, redirect, request

import config
import db
import dedupe
import erf
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
_DASH_USER = os.environ.get("DASHBOARD_USER", "oblivion")
_DASH_PASS = os.environ.get("DASHBOARD_PASSWORD", "")
_IS_HOSTED = bool(os.environ.get("PORT") or os.environ.get("RAILWAY_ENVIRONMENT"))


@app.before_request
def _require_auth():
    if not _DASH_PASS:
        if _IS_HOSTED:
            return Response(
                "DASHBOARD_PASSWORD is not set. Refusing to serve the "
                "prospect dashboard unauthenticated on a public host.\n"
                "Set it with:  railway variables --set DASHBOARD_PASSWORD=...",
                503, {"Content-Type": "text/plain"})
        return None                      # local, unauthenticated is fine
    auth = request.authorization
    if auth and auth.username == _DASH_USER and \
            hmac.compare_digest(auth.password or "", _DASH_PASS):
        return None
    return Response("Authentication required.", 401,
                    {"WWW-Authenticate": 'Basic realm="Oblivion Prospect Engine"'})

job = {
    "running": False,
    "phase": "idle",
    "log": [],
    "started": None,
    "done": 0,
    "total": 0,
    "per_source": {},
}
job_lock = threading.Lock()
_stop = threading.Event()


def log(msg: str) -> None:
    line = f"{datetime.now():%H:%M:%S}  {msg}"
    with job_lock:
        job["log"].append(line)
        job["log"] = job["log"][-600:]
    print(line, flush=True)


def _run(suburbs, source_names, pages, use_ai):
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
        job["phase"] = "crawling portals"
        # only_stale: after a crawl, score what actually changed. A reasoning
        # model spends real time per property, so re-judging the whole database
        # to absorb a handful of new listings turned a 1-minute crawl into a
        # 15-minute job. The "Re-score existing data" button still does a full
        # pass when you want one (e.g. after editing the prompt).
        pipeline.run(suburbs, source_names, pages=pages, use_ai=use_ai,
                     log=log, progress=progress, stop=_stop, only_stale=True)
        job["phase"] = "done"
    except Exception as e:
        job["phase"] = "error"
        log(f"ERROR: {type(e).__name__}: {e}")
    finally:
        snap = progress.snapshot()
        with job_lock:
            job.update(done=snap["done"], total=snap["total"],
                       per_source=snap["per_source"], running=False)


def _start_job(suburbs, srcs, pages, use_ai=True) -> bool:
    """Claim the single job slot and launch a crawl; False if already busy.

    Check-and-set under job_lock so the dashboard button and the auto-crawl
    scheduler can never both claim the slot.
    """
    with job_lock:
        if job["running"]:
            return False
        job.update(running=True, phase="starting", log=[], done=0, total=0,
                   per_source={}, started=datetime.now().isoformat())
    _stop.clear()
    threading.Thread(target=_run, args=(suburbs, srcs, pages, use_ai),
                     daemon=True).start()
    return True


@app.post("/api/scrape")
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

    if not _start_job(suburbs, srcs, pages, use_ai):
        return jsonify({"error": "a job is already running"}), 409
    return jsonify({"ok": True})


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
                # right time for its 12-18s pacing.
                if _start_job(suburbs, _auto_sources(include_p24=True),
                              pages=config.MAX_PAGES_PER_SUBURB):
                    _auto["last_full"] = now.date()
                    log("auto-crawl: nightly full pass started")
            elif config.AUTO_SWEEP_HOURS > 0 and (
                    _auto["last_sweep"] is None
                    or (now - _auto["last_sweep"]).total_seconds()
                    >= config.AUTO_SWEEP_HOURS * 3600):
                # Freshness sweep: page 1 of the fast portals only. Keeps
                # last_seen current, which is what the proof-freshness gate,
                # the delisting sweep and price history all feed on.
                if _start_job(suburbs, _auto_sources(include_p24=False),
                              pages=1):
                    _auto["last_sweep"] = now
                    log("auto-crawl: freshness sweep started (fast portals, "
                        "page 1)")
        except Exception as e:                          # noqa: BLE001
            print(f"auto-crawl scheduler error: {type(e).__name__}: {e}",
                  flush=True)


threading.Thread(target=_auto_crawl_loop, daemon=True).start()


@app.post("/api/stop")
def api_stop():
    _stop.set()
    log("stop requested — finishing current requests")
    return jsonify({"ok": True})


@app.post("/api/rescore")
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

    job.update(running=True, phase="starting", log=[], done=0, total=0)
    threading.Thread(target=rescore, daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/status")
def api_status():
    with job_lock:
        out = {k: job[k] for k in
               ("running", "phase", "log", "done", "total", "per_source")}
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
WHERE NOT EXISTS (
        SELECT 1 FROM property_groups g2
        JOIN listings l2 ON l2.listing_key = g2.listing_key
        JOIN tracker t2 ON t2.listing_number = l2.source_id
        WHERE g2.group_id = g.group_id
          AND l2.source = 'property24' AND t2.prospected = 1)
ORDER BY (s.prospect_score IS NULL) DESC, s.prospect_score DESC, l.price_zar DESC
"""


@app.get("/api/prospects")
def api_prospects():
    show_sole = request.args.get("sole") == "1"
    now = time.monotonic()
    with _prospects_lock:
        hit = _prospects_cache.get(show_sole)
        if hit and now - hit[0] < _PROSPECTS_TTL:
            return jsonify(hit[1])
    payload = _build_prospects(show_sole)
    with _prospects_lock:
        _prospects_cache[show_sole] = (time.monotonic(), payload)
    return jsonify(payload)


def _build_prospects(show_sole: bool) -> list:
    from sources.base import canonical_agency
    with db.connect() as conn:
        rows = conn.execute(PROSPECT_QUERY).fetchall()
        # One GV-roll lookup for the whole response, not one per row — the
        # dashboard hits this endpoint every 2s while a job runs, and
        # for_groups() walks two tables per call.
        gv_by_group = valuations.for_groups(conn)

    grouped: dict = {}
    for r in rows:
        gid = r["group_id"] if r["group_id"] is not None else f"solo-{r['listing_key']}"
        grouped.setdefault(gid, []).append(r)

    out = []
    for members in grouped.values():
        best = max(members, key=lambda m: ((m["photo_count"] or 0),
                                           len(m["description"] or "")))
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
        gid = best["group_id"]
        val = gv_by_group.get(str(gid)) if gid is not None else None
        d["gv_value"] = (val or {}).get("market_value")
        d["gv_roll"] = (val or {}).get("roll")
        # Only real (integer) groups have a CMA page; solo listings carry the
        # synthetic 'solo-<key>' id and cma_web has nothing to render for them.
        d["cma_url"] = f"/cma/{gid}" if isinstance(gid, int) else None
        out.append(d)

    out.sort(key=lambda d: (-(d.get("prospect_score") or -1),
                            -(d.get("price_zar") or 0)))
    return out


# ------------------------------------------------------- erf / cadastre jobs
#
# Bulk resolution talks to the public CoCT cadastre (fast, free); the AI
# locator downloads listing photos + satellite crops and asks a vision model
# to rank candidate parcels — seconds to a minute per property, so both run
# in background threads and the dashboard polls /api/erf/busy.
# /api/prospects is polled every 2s by the dashboard and costs ~90ms of
# GIL-holding query + grouping work. During a crawl that poll competes with
# the scrapers for the same interpreter, so identical back-to-back polls are
# served from a short-lived cache instead of recomputed. The TTL is below the
# poll interval, so the dashboard still updates every cycle.
_PROSPECTS_TTL = 1.5
_prospects_cache: dict = {}
_prospects_lock = threading.Lock()

_erf_job = {"running": False}
_ai_jobs: dict[str, dict] = {}
_reeval_jobs: dict[str, dict] = {}


@app.post("/api/erf/resolve")
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
                s = erf.resolve_all(conn, force=force, log=log)
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


@app.get("/api/erf/busy")
def api_erf_busy():
    return jsonify({"resolving": _erf_job["running"],
                    "locating": [k for k, v in _ai_jobs.items()
                                 if v.get("running")],
                    "reevaluating": [k for k, v in _reeval_jobs.items()
                                     if v.get("running")]})


@app.post("/api/listing/reevaluate")
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
    """
    with db.connect() as conn:
        url = photos.first_photo(conn, listing_key)
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


@app.get("/api/stats")
def api_stats():
    with db.connect() as conn:
        def one(sql):
            return conn.execute(sql).fetchone()[0]
        return jsonify({
            "listings": one("SELECT COUNT(*) FROM listings"),
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
                "SELECT source, COUNT(*) FROM listings GROUP BY source")},
        })


# ---------------------------------------------------------------- dashboard
#
# The dashboard page lives in dashboard.html next to this file and is re-read
# on every request, so markup/CSS/JS edits show on a plain browser refresh —
# no server restart, and no thousand-line HTML string cluttering this module.
_DASHBOARD_PATH = os.path.join(config.ROOT, "dashboard.html")


@app.get("/")
def index():
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


# --------------------------------------------------------------- CMA pages
#
# The CMA feature lives at its own URLs (/cma, /cma/<group_id>) — the main
# dashboard above is untouched. All HTML for these pages is rendered by
# cma_web.py; auth is covered by the app-wide _require_auth before_request.
import cma            # noqa: E402  (kept below the dashboard on purpose)
import cma_web        # noqa: E402
import owners         # noqa: E402
import valuations     # noqa: E402


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


@app.get("/api/cma/<int:group_id>")
def api_cma(group_id: int):
    with db.connect() as conn:
        result = cma.analyse(conn, group_id)
    if result is None:
        return jsonify({"error": f"property group {group_id} not found"}), 404
    return jsonify(result)


@app.route("/api/owner/<group_id>", methods=["GET", "POST", "DELETE"])
def api_owner(group_id):
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


@app.post("/api/gv/refresh")
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
