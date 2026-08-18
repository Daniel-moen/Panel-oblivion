"""Polite, cached, per-host-rate-limited HTTP fetching.

Each portal gets its own Fetcher with its own requests.Session and its own
rate limiter. Because the fetchers are independent and target different hosts,
sources are crawled concurrently without any one affecting another's limit.

Rate limiting is ADAPTIVE (AIMD), not a fixed guess. A hardcoded delay has to
be set to the worst case the portal has ever shown, and then pays that cost on
every request forever. Instead each fetcher starts at `delay`, shortens the
gap after a run of clean 200s, and doubles it the moment the portal answers
429/503. The learned gap is persisted per source (.ratestate.json) so the next
run starts from what was true last time instead of re-probing from scratch.

This is strictly more polite than a fixed delay under load — a fixed delay
cannot react at all when a portal starts throttling, whereas this backs off
on the first refusal and keeps backing off while refusals continue.

Responses are cached on disk (keyed by URL) so re-runs, parser iteration and
crash recovery don't re-hit the sites.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time

import requests

import config


def _noop(msg: str) -> None:
    print(msg, flush=True)


# Learned per-source request spacing, so a run starts where the last one
# finished rather than re-probing the portal's limit from scratch.
_STATE_PATH = os.path.join(config.DATA_DIR, ".ratestate.json")
_STATE_LOCK = threading.Lock()


def _load_state() -> dict:
    try:
        with open(_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(source: str, delay: float) -> None:
    with _STATE_LOCK:
        state = _load_state()
        state[source] = round(delay, 2)
        try:
            with open(_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=1, sort_keys=True)
        except OSError:
            pass


class Fetcher:
    """Adaptively rate-limited HTTP client for a single portal."""

    # Shorten the gap after this many consecutive clean responses...
    SPEEDUP_AFTER = 5
    # ...by this factor. 0.75 walks a 2.5s gap down to the 0.6s floor in
    # ~25 requests; the gentler 0.85 needed ~72, which is longer than many
    # per-suburb batches and meant the adaptation never actually paid off.
    SPEEDUP_FACTOR = 0.75
    # Widen it by this factor on any throttle (fast: react hard, react once).
    SLOWDOWN_FACTOR = 2.0
    # Give up on a portal that is refusing everything. A blocked host is not
    # a slow host: walking the whole 60/180/360s ladder for every URL costs
    # ~10 minutes EACH and cannot succeed, so one IP-blocked portal would add
    # 90 minutes to a run the other seventeen finish in a minute. Property24
    # blocks by IP and keeps the block alive while it is being poked, so the
    # only useful response is to stop poking and let the rest of the run go.
    GIVE_UP_AFTER_THROTTLES = 4      # ...before this source has ever succeeded
    GIVE_UP_AFTER_EXHAUSTED = 2      # ...consecutive URLs that burn the ladder
    # While a portal has not answered ONCE, the long end of the backoff ladder
    # is wasted time: a 360s sleep cannot talk an IP block into lifting, it
    # only delays the moment we notice and move on. Cap the wait until the
    # portal has proved it will talk to us at all.
    UNPROVEN_BACKOFF_CAP = 30.0

    def __init__(self, source: str, logger=None):
        self.source = source
        cfg = config.SOURCES[source]
        self.label = cfg["label"]
        self.jitter = cfg["jitter"]
        self.backoffs = list(cfg["backoffs"])
        self.base_url = cfg["base_url"]
        self.log = logger or _noop

        # Adaptive window. delay_min is the floor we will never go below no
        # matter how well things are going; delay_max is the ceiling a badly
        # throttling portal gets parked at.
        self.delay_min = cfg.get("delay_min", cfg["delay"])
        self.delay_max = cfg.get("delay_max", cfg["delay"] * 4)
        learned = _load_state().get(source)
        if learned:
            # Start a notch above what was learned — conditions may differ.
            self.delay = min(self.delay_max, max(self.delay_min, learned * 1.1))
        else:
            self.delay = cfg["delay"]
        self._start_delay = self.delay

        self.session = requests.Session()
        # Pool sized to the source's worker count so concurrent workers reuse
        # connections instead of opening a new TCP+TLS handshake each time.
        workers = max(1, cfg.get("workers", 1))
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=workers, pool_maxsize=workers * 2, max_retries=0)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-ZA,en;q=0.9",
            # brotli is installed (see requirements); these pages are ~200KB
            # of HTML and br cuts the transfer well below gzip.
            "Accept-Encoding": "br, gzip, deflate",
            "Referer": self.base_url + "/",
            "Upgrade-Insecure-Requests": "1",
        })

        self._lock = threading.Lock()
        self._next_ok = 0.0          # earliest monotonic time for next request
        self._ok_streak = 0
        self.blocked = False         # tripped the portal's throttle this run
        self.circuit_open = False    # abandoned for this run (see give-up rules)
        self._exhausted_runs = 0     # consecutive URLs that burned the ladder
        self.stats = {"fetched": 0, "cached": 0, "failed": 0, "throttled": 0}

    # ------------------------------------------------------------ caching
    def _cache_path(self, url: str) -> str:
        digest = hashlib.sha256(url.encode()).hexdigest()[:32]
        return os.path.join(config.CACHE_DIR, self.source, digest + ".html")

    def _cache_read(self, url: str) -> str | None:
        if not config.CACHE_ENABLED:
            return None
        path = self._cache_path(url)
        try:
            age_h = (time.time() - os.path.getmtime(path)) / 3600
        except OSError:
            return None
        if age_h > config.CACHE_TTL_HOURS:
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def _cache_write(self, url: str, body: str) -> None:
        if not config.CACHE_ENABLED:
            return
        path = self._cache_path(url)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
        except OSError:
            pass

    # ------------------------------------------------------------ throttle
    def _wait_turn(self) -> bool:
        """Block until this host's rate limit allows another request.

        Reserves the slot under the lock before sleeping, so concurrent
        workers queue up at `delay` spacing rather than all waking together
        and bursting — which is exactly what trips a burst-based throttle.

        Returns False if the source was written off while this caller was
        waiting: by then the gap can be a minute wide, and a worker parked
        in here would otherwise keep the run alive long after there is
        anything left to fetch.
        """
        while True:
            if self.circuit_open:
                return False
            with self._lock:
                now = time.monotonic()
                if now >= self._next_ok:
                    self._next_ok = now + self.delay + random.uniform(0, self.jitter)
                    return True
                sleep_for = self._next_ok - now
            time.sleep(min(sleep_for, 1.0))

    def _penalise(self, seconds: float) -> None:
        """Push this host's next-allowed time out after a throttle response."""
        with self._lock:
            self._next_ok = max(self._next_ok, time.monotonic() + seconds)

    def _on_success(self) -> None:
        """A clean 200 — consider shortening the gap."""
        with self._lock:
            self._ok_streak += 1
            if self._ok_streak < self.SPEEDUP_AFTER:
                return
            self._ok_streak = 0
            if self.delay <= self.delay_min:
                return
            self.delay = max(self.delay_min, self.delay * self.SPEEDUP_FACTOR)
            new = self.delay
        self.log(f"[{self.label}] steady — tightening to {new:.1f}s between requests")

    def _on_throttle(self) -> None:
        """A 429/503 — widen the gap hard and stop trying to speed up."""
        with self._lock:
            self._ok_streak = 0
            if self.delay >= self.delay_max:
                return
            self.delay = min(self.delay_max, self.delay * self.SLOWDOWN_FACTOR)
            new = self.delay
        self.log(f"[{self.label}] throttled — easing off to {new:.1f}s between requests")

    def _trip_circuit(self, why: str) -> None:
        if self.circuit_open:
            return
        self.circuit_open = True
        self.log(f"[{self.label}] giving up for this run — {why}. "
                 f"The other portals continue; re-run once the block clears.")

    def close(self) -> None:
        """Persist what this run learned about the portal's tolerance.

        Only a rate learned from real successes is worth keeping. A portal
        that refused everything drives the gap to its ceiling, and saving
        that would start the NEXT run at a minute per request for a limit
        that was never measured — punishing a blocked run twice.
        """
        learned_something = self.stats["fetched"] and not self.circuit_open
        if learned_something and abs(self.delay - self._start_delay) > 0.01:
            _save_state(self.source, self.delay)
        try:
            self.session.close()
        except Exception:                                   # noqa: BLE001
            pass

    # ------------------------------------------------------------ fetching
    def get(self, url: str, use_cache: bool = True) -> str | None:
        if use_cache:
            body = self._cache_read(url)
            if body is not None:
                self.stats["cached"] += 1
                return body

        # Already written off for this run — fail instantly rather than
        # spending another ten minutes of backoff proving it again.
        if self.circuit_open:
            self.stats["failed"] += 1
            return None

        for attempt, backoff in enumerate([0] + self.backoffs):
            if backoff:
                if not self.stats["fetched"]:
                    backoff = min(backoff, self.UNPROVEN_BACKOFF_CAP)
                self.log(f"[{self.label}] backing off {backoff}s")
                self._penalise(backoff)
            if not self._wait_turn():
                self.stats["failed"] += 1
                return None
            try:
                resp = self.session.get(url, timeout=30)
            except requests.RequestException as e:
                self.log(f"[{self.label}] request failed ({type(e).__name__}) {url}")
                if attempt >= len(self.backoffs):
                    self.stats["failed"] += 1
                    return None
                continue

            if resp.status_code == 200:
                self.stats["fetched"] += 1
                self._exhausted_runs = 0
                self._on_success()
                self._cache_write(url, resp.text)
                return resp.text
            if resp.status_code in (429, 503):
                self.stats["throttled"] += 1
                self.blocked = True
                self._on_throttle()
                if (not self.stats["fetched"]
                        and self.stats["throttled"] >= self.GIVE_UP_AFTER_THROTTLES):
                    self._trip_circuit(
                        f"{self.stats['throttled']} refusals and not one "
                        f"success — the IP looks blocked, not rate-limited")
                    self.stats["failed"] += 1
                    return None
                continue
            if resp.status_code == 404:
                self.stats["failed"] += 1
                return None
            self.log(f"[{self.label}] HTTP {resp.status_code} for {url}")
            self.stats["failed"] += 1
            return None

        self.log(f"[{self.label}] still throttled after all retries, skipping {url}")
        self.stats["failed"] += 1
        self._exhausted_runs += 1
        if self._exhausted_runs >= self.GIVE_UP_AFTER_EXHAUSTED:
            self._trip_circuit(f"{self._exhausted_runs} URLs in a row exhausted "
                               f"the full backoff ladder")
        return None

    def get_json(self, url: str, use_cache: bool = True):
        body = self.get(url, use_cache=use_cache)
        if not body:
            return None
        try:
            return json.loads(body)
        except ValueError:
            return None
