"""Auto-crawl schedule: settings, due-checks, next-run times, idle skipping.

Pure logic for webapp's _auto_crawl_loop, kept out of webapp.py so it can be
tested with plain datetimes. Settings are the config.AUTO_* env defaults,
overlaid by whatever the owner saved from the dashboard (app_state key
`auto_crawl_settings`, JSON), so they survive restarts and a redeploy with
different env vars never silently undoes a choice made in the UI.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import config

SETTINGS_KEY = "auto_crawl_settings"
IDLE_KEY = "auto_sweep_idle"

# A sweep is not started this close before the nightly pass: the pass
# refreshes everything the sweep would, and a sweep still running at the
# pass's hour would push the pass into its catch-up window.
FULL_GUARD_S = 90 * 60


def defaults() -> dict:
    """The env-var defaults, read at call time (tests poke config)."""
    return {
        "enabled": bool(config.AUTO_CRAWL),
        "full_enabled": True,
        "full_hour": int(config.AUTO_CRAWL_HOUR) % 24,
        "rentals": bool(config.AUTO_CRAWL_RENTALS),
        "sweep_hours": float(config.AUTO_SWEEP_HOURS),
        "sweep_from": int(getattr(config, "AUTO_SWEEP_FROM", 0)) % 24,
        "sweep_to": int(getattr(config, "AUTO_SWEEP_TO", 0)) % 24,
        "skip_idle_after": int(getattr(config, "AUTO_SWEEP_SKIP_IDLE", 3)),
        "reprobe_every": int(getattr(config, "AUTO_SWEEP_REPROBE", 4)),
    }


def clean(patch: dict) -> tuple[dict, list[str]]:
    """Validate a PATCH body into {key: value}; unknown keys are errors."""
    out, errs = {}, []
    base = defaults()
    for k, v in (patch or {}).items():
        if k not in base:
            errs.append(f"unknown setting {k!r}")
            continue
        try:
            if k in ("enabled", "full_enabled", "rentals"):
                if not isinstance(v, bool):
                    raise ValueError
                out[k] = v
            elif k in ("full_hour", "sweep_from", "sweep_to"):
                n = int(v)
                if not 0 <= n <= 23 or n != float(v):
                    raise ValueError
                out[k] = n
            elif k == "sweep_hours":
                n = float(v)
                if not (n == 0 or 1 <= n <= 168):
                    raise ValueError
                out[k] = n
            elif k == "skip_idle_after":
                n = int(v)
                if not 0 <= n <= 50:
                    raise ValueError
                out[k] = n
            elif k == "reprobe_every":
                n = int(v)
                if not 1 <= n <= 50:
                    raise ValueError
                out[k] = n
        except (TypeError, ValueError):
            errs.append(f"bad value for {k}: {v!r}")
    return out, errs


def load(conn) -> dict:
    import db
    s = defaults()
    try:
        saved = json.loads(db.get_state(conn, SETTINGS_KEY) or "{}")
    except ValueError:
        saved = {}
    if isinstance(saved, dict):
        good, _ = clean({k: v for k, v in saved.items() if k in s})
        s.update(good)
    return s


def overrides(conn) -> dict:
    import db
    try:
        saved = json.loads(db.get_state(conn, SETTINGS_KEY) or "{}")
    except ValueError:
        return {}
    return saved if isinstance(saved, dict) else {}


def save(conn, patch: dict) -> dict:
    """Merge a cleaned patch into the stored overrides; returns settings.
    A value equal to the env default is dropped from the overrides, so a
    later env change still takes effect for anything never customised."""
    import db
    saved = overrides(conn)
    base = defaults()
    for k, v in patch.items():
        if v == base.get(k):
            saved.pop(k, None)
        else:
            saved[k] = v
    db.set_state(conn, SETTINGS_KEY, json.dumps(saved))
    return load(conn)


# ------------------------------------------------------------- due checks

def in_window(hour: int, frm: int, to: int) -> bool:
    """Is `hour` inside [frm, to)? frm == to means always; wraps midnight."""
    if frm == to:
        return True
    if frm < to:
        return frm <= hour < to
    return hour >= frm or hour < to


def full_slot(now: datetime, hour: int) -> datetime:
    """The most recent nightly-pass slot at or before `now`."""
    slot = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return slot if slot <= now else slot - timedelta(days=1)


def full_due(now: datetime, last_started, s: dict) -> bool:
    """The nightly pass is due: we are in its hour or its catch-up window,
    and the last pass started at least AUTO_FULL_MIN_HOURS ago (or never)."""
    if not s.get("full_enabled", True):
        return False
    slot = full_slot(now, s["full_hour"])
    window = max(1.0, float(config.AUTO_FULL_CATCHUP_HOURS))
    if (now - slot).total_seconds() >= window * 3600:
        return False
    return last_started is None or (
        (now - last_started).total_seconds()
        >= config.AUTO_FULL_MIN_HOURS * 3600)


def sweep_base(st: dict):
    """What the sweep interval is counted from: the newer of the last sweep
    START and the last full-pass START (a full pass refreshes everything a
    sweep would). Finished stamps only stand in when nothing has a start
    stamp yet (the first-boot bootstrap writes a finished one)."""
    starts = [t for t in (st.get("auto_last_sweep_started"),
                          st.get("auto_last_full_started")) if t]
    if starts:
        return max(starts)
    done = [t for t in (st.get("auto_last_sweep"), st.get("auto_last_full"))
            if t]
    return max(done) if done else None


def sweep_due(now: datetime, base, s: dict) -> bool:
    if s["sweep_hours"] <= 0:
        return False
    if not in_window(now.hour, s["sweep_from"], s["sweep_to"]):
        return False
    return base is None or (now - base).total_seconds() >= s["sweep_hours"] * 3600


def sweep_interrupted(now: datetime, st: dict, retry_s: float) -> bool:
    """A sweep started, never ended (the process died under it) and has had
    `retry_s` to be sure: run it again rather than wait a whole interval.
    A sweep that ended badly (stopped, error) is not retried early — a
    person pressed Stop, or it would fail again."""
    started = st.get("auto_last_sweep_started")
    if started is None:
        return False
    ended = [t for t in (st.get("auto_last_sweep"),
                         st.get("auto_last_sweep_ended")) if t]
    if ended and max(ended) >= started:
        return False
    return (now - started).total_seconds() >= retry_s


def next_full(now: datetime, last_started, s: dict):
    if not s.get("full_enabled", True):
        return None
    if full_due(now, last_started, s):
        return now
    gap = timedelta(hours=config.AUTO_FULL_MIN_HOURS)
    slot = full_slot(now, s["full_hour"]) + timedelta(days=1)
    for _ in range(8):
        if last_started is None or slot - last_started >= gap:
            return slot
        slot += timedelta(days=1)
    return slot


def next_window_start(t: datetime, s: dict) -> datetime:
    """`t`, or the next time at/after it that the sweep window is open."""
    if in_window(t.hour, s["sweep_from"], s["sweep_to"]):
        return t
    c = t.replace(minute=0, second=0, microsecond=0)
    for _ in range(25):
        c += timedelta(hours=1)
        if in_window(c.hour, s["sweep_from"], s["sweep_to"]):
            return c
    return t


def next_sweep(now: datetime, st: dict, s: dict, retry_s: float):
    if s["sweep_hours"] <= 0:
        return None
    base = sweep_base(st)
    t = now if base is None else max(now, base + timedelta(hours=s["sweep_hours"]))
    started = st.get("auto_last_sweep_started")
    if started is not None and sweep_interrupted(
            started + timedelta(seconds=retry_s), st, retry_s):
        t = min(t, max(now, started + timedelta(seconds=retry_s)))
    t = next_window_start(t, s)
    nf = next_full(now, st.get("auto_last_full_started"), s)
    if nf is not None and timedelta(0) <= nf - t < timedelta(seconds=FULL_GUARD_S):
        # Swallowed by the nightly pass; the next sweep counts from it.
        t = next_window_start(nf + timedelta(hours=s["sweep_hours"]), s)
    return t


def full_soon(now: datetime, st: dict, s: dict) -> bool:
    nf = next_full(now, st.get("auto_last_full_started"), s)
    return nf is not None and nf > now and \
        (nf - now).total_seconds() < FULL_GUARD_S


# ----------------------------------------------------------- idle pairs

def load_idle(conn) -> dict:
    import db
    try:
        d = json.loads(db.get_state(conn, IDLE_KEY) or "{}")
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def pair(source: str, slug: str) -> str:
    return f"{source}|{slug}"


def skippable(suburbs, sources) -> list[tuple[str, str]]:
    """Pairs idle skipping may ever apply to: whole-town areas re-derive
    each listing's suburb from its URL, so their new stock is not filed
    under the crawled slug and would look idle forever — never skipped."""
    return [(src, slug) for src in sources for slug in suburbs
            if config.SUBURBS.get(slug, {}).get("scope") != "town"]


def plan_skips(idle: dict, suburbs, sources, s: dict) -> list[list[str]]:
    """[[source, slug]] to leave out of this sweep."""
    n, every = s.get("skip_idle_after", 0), max(1, s.get("reprobe_every", 4))
    if n <= 0:
        return []
    out = []
    for src, slug in skippable(suburbs, sources):
        idle_n, skipped = (idle.get(pair(src, slug)) or [0, 0])[:2]
        if idle_n >= n and skipped < every - 1:
            out.append([src, slug])
    return out


def record(idle: dict, crawled, skipped, news: dict, kind: str) -> dict:
    """Fold one finished job into the idle table.

    crawled: [(source, slug)] actually crawled; skipped: [(source, slug)]
    left out; news: {(source, slug): new-or-changed count}. A sweep counts
    an idle round for every crawled pair that found nothing; a full pass
    only ever clears idleness (it digs deeper than page 1, so "nothing
    new" there says little about page 1 tomorrow).
    """
    out = dict(idle)
    for src, slug in crawled:
        k = pair(src, slug)
        idle_n = (out.get(k) or [0, 0])[0]
        if news.get((src, slug), 0) > 0:
            out[k] = [0, 0]
        elif kind == "sweep":
            out[k] = [idle_n + 1, 0]
    for src, slug in skipped:
        k = pair(src, slug)
        idle_n, n_skip = (out.get(k) or [0, 0])[:2]
        out[k] = [idle_n, n_skip + 1]
    return {k: v for k, v in out.items() if v != [0, 0]}
