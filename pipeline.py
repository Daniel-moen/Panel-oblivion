"""Crawl orchestration.

Every portal is a different host with its own rate limit, so the sources are
crawled concurrently: Property24 plods along at ~15s per request while the
others finish in a fraction of the time. Wall-clock for a run is therefore
roughly the Property24 crawl alone, rather than the sum of eighteen crawls.

The thread pool is sized to the number of sources, so adding one adds a
thread against a different host rather than more load on an existing one.

SQLite is single-writer, so parse results funnel back through one lock-guarded
connection while the network work happens in parallel.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
import db
import dedupe
import lifecycle
import scorer
import sources as source_registry
from sources import base as sources_base


class Progress:
    """Thread-safe counters for the dashboard."""

    def __init__(self):
        self.lock = threading.Lock()
        self.total = 0
        self.done = 0
        self.stored = 0
        self.per_source: dict[str, dict] = {}

    def add_total(self, source: str, n: int) -> None:
        with self.lock:
            self.total += n
            s = self.per_source.setdefault(source, {"found": 0, "stored": 0, "done": 0})
            s["found"] += n

    def tick(self, source: str, stored: bool) -> None:
        with self.lock:
            self.done += 1
            s = self.per_source.setdefault(source, {"found": 0, "stored": 0, "done": 0})
            s["done"] += 1
            if stored:
                self.stored += 1
                s["stored"] += 1

    def snapshot(self) -> dict:
        with self.lock:
            return {"total": self.total, "done": self.done,
                    "stored": self.stored,
                    "per_source": {k: dict(v) for k, v in self.per_source.items()}}


def _crawl_source(name: str, suburbs: list[str], pages: int, conn, write_lock,
                  log, progress: Progress, stop: threading.Event) -> dict:
    """Crawl one portal across all requested suburbs."""
    try:
        src = source_registry.build(name, logger=log)
    except Exception as e:
        log(f"[{name}] could not start: {type(e).__name__}: {e}")
        return {"source": name, "stored": 0, "error": str(e)}

    stored = 0
    skipped_land = 0
    for slug in suburbs:
        if stop.is_set() or src.fetcher.circuit_open:
            break
        info = config.SUBURBS[slug]
        label = info["name"]
        # A whole-town area holds many suburbs' worth of stock, so it gets a
        # deeper page budget than a single suburb. Sources break out as soon
        # as a page adds nothing, so the extra allowance costs nothing on the
        # areas that do not need it.
        budget = (max(pages, config.MAX_PAGES_TOWN_SCOPE)
                  if info.get("scope") == "town" else pages)
        try:
            urls = src.search_urls(slug, budget)
        except Exception as e:
            log(f"[{src.label}] {label}: search failed ({type(e).__name__}: {e})")
            continue
        if not urls:
            log(f"[{src.label}] {label}: no listings found")
            continue

        with write_lock:
            seen = db.recently_seen(conn, name)
        fresh = [u for u in urls if not _already(u, name, seen)]
        skipped = len(urls) - len(fresh)
        log(f"[{src.label}] {label}: {len(fresh)} to fetch"
            + (f" ({skipped} seen recently, skipped)" if skipped else ""))
        progress.add_total(name, len(fresh))

        # Detail pages are fetched concurrently. The fetcher's rate limiter
        # still enforces this host's gap globally, so concurrency does not
        # raise the request RATE — it only lets the next request's wait
        # overlap the current one's download and parse, which is most of the
        # per-request cost once the adaptive gap has tightened.
        def _fetch_one(u):
            if stop.is_set() or src.fetcher.circuit_open:
                return None
            try:
                return src.parse_detail(u, slug)
            except Exception as e:                          # noqa: BLE001
                log(f"[{src.label}] parse error {type(e).__name__}: {u}")
                return None

        def _store(listing) -> None:
            """Runs on the crawl thread only — counters need no lock."""
            nonlocal stored, skipped_land
            ok = False
            if listing and config.EXCLUDE_VACANT_LAND and \
                    sources_base.is_vacant_land(listing):
                listing = None
                skipped_land += 1
            if listing:
                with write_lock:
                    db.upsert_listing(conn, listing)
                    conn.commit()
                stored += 1
                ok = True
                price = listing.get("price_zar")
                shown = f"R{price:,}" if price else "POA"
                title = (listing.get("title") or "")[:52]
                log(f"[{src.label}] + {title} — {shown}")
            progress.tick(name, ok)

        workers = max(1, config.SOURCES.get(name, {}).get("workers", 1))
        if workers > 1 and len(fresh) > 1:
            with ThreadPoolExecutor(max_workers=workers,
                                    thread_name_prefix=f"{name}-detail") as dpool:
                # map() streams results in submission order, so the log still
                # reads in page order rather than completion order.
                for listing in dpool.map(_fetch_one, fresh):
                    _store(listing)
                    if stop.is_set() or src.fetcher.circuit_open:
                        break
        else:
            for url in fresh:
                if stop.is_set() or src.fetcher.circuit_open:
                    break
                _store(_fetch_one(url))

    src.fetcher.close()          # persist the learned request spacing
    st = src.fetcher.stats
    if src.fetcher.circuit_open:
        log(f"[{src.label}] ABANDONED this run (blocked) — {stored} stored "
            f"before giving up")
    log(f"[{src.label}] done — {stored} stored "
        f"({st['fetched']} fetched, {st['cached']} cached, {st['failed']} failed"
        + (f", {skipped_land} vacant plots dropped" if skipped_land else "") + ")")
    return {"source": name, "stored": stored, **st}


def _already(url: str, source: str, seen: set[str]) -> bool:
    """Cheap check of whether this URL's listing id was scraped recently."""
    import re
    import sources as source_registry
    patterns = {
        "property24": r"/(\d+)(?:\?|$)",
        "privateproperty": r"/(T\d+)(?:[/?#]|$)",
        "pamgolding": r"/([a-z]{2}\d+)(?:[/?#]|$)",
        "remax": r"-(\d{5,})(?:[/?#]|$)",
        "rawson": r"/(\d{5,})(?:[/?#]|$)",
        "immoafrica": r"/(IA\d+)(?:[/?#]|$)",
        # MyProperty ids are numeric on some listings and a web reference
        # ("rl61722") on others, and both sit in the last path segment.
        "myproperty": r"/([a-z]{0,4}\d{4,})(?:[/?#]|$)",
    }
    # Every Prop Data tenant shares the platform's URL shape.
    for name in source_registry.propdata_names():
        patterns.setdefault(name, r"/(\d{5,})(?:/|$)")
    m = re.search(patterns.get(source, r"/(\d+)$"), url, re.I)
    if not m:
        return False
    ident = m.group(1)
    return ident in seen or ident.upper() in seen


def run(suburbs: list[str], source_names: list[str] | None = None,
        pages: int = 3, use_ai: bool = True, log=print,
        progress: Progress | None = None,
        stop: threading.Event | None = None,
        do_score: bool = True, only_stale: bool = False) -> dict:
    """Scrape the selected portals, group duplicates, then score."""
    source_names = [s for s in (source_names or config.enabled_sources())
                    if s in source_registry.REGISTRY]
    suburbs = [s for s in suburbs if s in config.SUBURBS]
    progress = progress or Progress()
    stop = stop or threading.Event()

    if not suburbs or not source_names:
        log("nothing to do — pick at least one suburb and one source")
        return {"scraped": 0}

    log(f"crawling {len(suburbs)} suburb(s) across {len(source_names)} portal(s): "
        f"{', '.join(config.SOURCES[s]['label'] for s in source_names)}")

    write_lock = threading.Lock()
    results = []
    with db.connect() as conn:
        with ThreadPoolExecutor(max_workers=len(source_names)) as pool:
            futures = {
                pool.submit(_crawl_source, name, suburbs, pages, conn,
                            write_lock, log, progress, stop): name
                for name in source_names
            }
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    results.append(fut.result())
                except Exception as e:
                    log(f"[{name}] crawl crashed: {type(e).__name__}: {e}")

        log("matching listings across portals...")
        stats = dedupe.rebuild_groups(conn)
        conn.commit()
        log(f"dedupe: {stats['listings']} listings -> {stats['groups']} properties; "
            f"{stats['multi_agency_groups']} marketed by multiple agencies "
            f"(open-mandate proof), {stats['multi_source_groups']} seen on "
            f"multiple portals")

        # Yield canary: a source whose crawled-suburb stock was mostly NOT
        # confirmed this run (parser regression, portal redesign, block) must
        # not feed the delisting sweep — the missing listings would read as a
        # mass delisting and poison the comps feed with phantom off-market
        # events. Excluded sources are swept again once they recover.
        suspect: set[str] = set()
        marks = ",".join("?" * len(suburbs))
        for res in results:
            name = res.get("source")
            if not name or name not in config.SOURCES:
                continue
            total, fresh = conn.execute(
                f"""SELECT COUNT(*),
                           COALESCE(SUM(last_seen > datetime('now', '-24 hours')), 0)
                    FROM listings WHERE source = ?
                    AND suburb_slug IN ({marks})""",
                (name, *suburbs)).fetchone()
            if total >= 10 and fresh < total * config.LIFECYCLE_MIN_COVERAGE:
                suspect.add(name)
                log(f"[{name}] canary: only {fresh}/{total} listings "
                    f"confirmed in this run's suburbs — excluded from the "
                    f"delisting sweep (parser regression or block?)")

        # delisting / sold-proxy sweep — feeds cma.py's "recent off-market"
        # comps; update() does not commit, so commit here.
        lc = lifecycle.update(conn, exclude_sources=suspect)
        conn.commit()
        log(f"lifecycle: {lc['active']} active, "
            f"{lc['newly_delisted']} newly delisted, "
            f"{lc['newly_relisted']} relisted, "
            f"{lc['delisted_total']} delisted total, "
            f"{lc['likely_sold_total']} likely sold (proxy)")

        scored = 0
        if do_score and not stop.is_set():
            scored = scorer.score_all(conn, use_ai=use_ai, logger=log,
                                      only_stale=only_stale)
            conn.commit()

        # Pre-pitch guarantee: re-fetch the stale halves of hot multi-agency
        # proof LIVE before anyone reads the report. Small fixed budget; a
        # portal outage must not kill the run.
        if do_score and not stop.is_set():
            import verify
            try:
                vs = verify.run(conn, log=log, stop=stop, use_ai=use_ai)
                if vs["checked"]:
                    log(f"verify: {vs['refetched']} listings re-fetched live "
                        f"across {vs['groups']} hot multi-agency properties "
                        f"— {vs['gone']} no longer served, "
                        f"{vs['rescored']} re-scored")
            except Exception as e:                      # noqa: BLE001
                log(f"verify skipped ({type(e).__name__}: {e})")
            conn.commit()

        # Erf + GV always follow a crawl — the erf is the key to the GV
        # value, CMA comps and the deeds tool, so every property that can
        # resolve should, whether the run was started from the CLI or the
        # dashboard. Both steps skip work already done, and neither is
        # allowed to kill the run on a portal outage.
        if not stop.is_set():
            import erf
            log("erf: resolving parcels (CoCT metro + WC provincial cadastre)")
            try:
                es = erf.resolve_all(conn, log=log, stop=stop)
                log(f"erf: {es['resolved']} exact, {es['check']} to verify, "
                    f"{es['candidates']} with candidates, "
                    f"{es['unresolved']} unresolved, "
                    f"{es['skipped']} already done")
            except Exception as e:                      # noqa: BLE001
                log(f"erf skipped ({type(e).__name__}: {e})")
            # Photo-location closes the gap the cadastre can't: a candidate
            # list narrows to one erf by matching listing photos against
            # satellite crops of each parcel.
            try:
                als = erf.ai_locate_all(log=log, stop=stop)
                if als["groups"]:
                    log(f"AI locate: {als['located']} located from photos, "
                        f"{als['errors']} failed")
            except Exception as e:                      # noqa: BLE001
                log(f"AI locate skipped ({type(e).__name__}: {e})")
        if not stop.is_set():
            import valuations
            try:
                vs = valuations.resolve_all(conn, progress=log)
                log(f"GV valuations: {vs['fetched']} fetched, "
                    f"{vs['cached']} cached, {vs['not_found']} not on roll, "
                    f"{vs['errors']} errors")
            except Exception as e:                      # noqa: BLE001
                log(f"GV valuations skipped ({type(e).__name__}: {e})")
            import sbm_roll
            try:
                sb = sbm_roll.resolve_all(conn, progress=log)
                log(f"SBM roll: {sb['matched']} matched, "
                    f"{sb['cached']} cached, {sb['not_found']} not on roll")
            except Exception as e:                      # noqa: BLE001
                log(f"SBM roll skipped ({type(e).__name__}: {e})")

        sellable = conn.execute(
            "SELECT COUNT(DISTINCT g.group_id) FROM scores s"
            " JOIN property_groups g ON g.listing_key = s.listing_key"
            " WHERE COALESCE(s.sellable, 1) = 1").fetchone()[0]
        blocked = conn.execute(
            "SELECT COUNT(DISTINCT g.group_id) FROM scores s"
            " JOIN property_groups g ON g.listing_key = s.listing_key"
            " WHERE s.sellable = 0").fetchone()[0]

    log(f"complete — {sellable} sellable properties, "
        f"{blocked} excluded as sole-mandate")
    return {"sources": results, "dedupe": stats, "scored": scored,
            "sellable": sellable, "blocked": blocked}
