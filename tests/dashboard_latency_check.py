"""Latency check: the dashboard stays fast while a crawl runs.

Plain script, no pytest needed (the repo has no test runner):

    DATA_DIR=$(mktemp -d) .venv/bin/python tests/dashboard_latency_check.py

It refuses to run without DATA_DIR pointing at an empty scratch directory,
because it seeds DATA_DIR/prospects.db with ~2000 synthetic listings. The
crawl is the fake portal (tests/fake_source.py via CRAWL_SOURCES_PLUGIN): no
network, real parse cost, one commit per listing. Two poller threads hit
/api/status and /api/prospects every 2 s like the SPA while the main thread
times the dashboard's pages and APIs. Every endpoint's p95 must stay under
LATENCY_BUDGET_S (default 1.0 s), the crawl must finish, and no log line may
say "database is locked".

Also checks the pieces underneath: connect() leaves no transaction open,
the app_state roundtrip, and the auto-crawl due/not-due helpers.
"""

from __future__ import annotations

import base64
import os
import random
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta

data = os.environ.get("DATA_DIR")
if not data or os.path.abspath(data) == os.path.abspath(os.path.dirname(os.path.dirname(__file__))):
    sys.exit("Set DATA_DIR to a scratch directory (e.g. DATA_DIR=$(mktemp -d)).")
if os.path.exists(os.path.join(data, "prospects.db")):
    sys.exit("DATA_DIR already holds a prospects.db; use an empty scratch directory.")
os.environ.setdefault("MEDIA_ROOT", tempfile.mkdtemp(prefix="media-root-"))
os.environ["DASHBOARD_USER"] = "owner"
os.environ["DASHBOARD_PASSWORD"] = "check-pass"
os.environ["AUTO_CRAWL"] = "0"
os.environ["CRAWL_SOURCES_PLUGIN"] = "tests.fake_source"
os.environ["FAKE_LISTINGS"] = "150"
os.environ["FAKE_NET_MS"] = "20"
os.environ.pop("PROSPECTS_NO_WARM", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import db      # noqa: E402

BUDGET = float(os.environ.get("LATENCY_BUDGET_S", "1.0"))
N_SEED = 2000
failures = []


def check(name, cond, extra: object = ""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({extra})" if extra and not cond else ""))
    if not cond:
        failures.append(name)


# --- connect() holds nothing -------------------------------------------------
cm = db.connect()
conn = cm.__enter__()
check("connect() leaves no transaction open", conn.in_transaction is False)
db.set_state(conn, "check_key", "v1")
check("app_state roundtrip", db.get_state(conn, "check_key") == "v1")
db.set_state(conn, "check_key", "v2")
check("app_state overwrite", db.get_state(conn, "check_key") == "v2")
check("app_state default", db.get_state(conn, "missing", "dflt") == "dflt")
check("set_state commits", conn.in_transaction is False)
cm.__exit__(None, None, None)

# --- seed a for-sale book with real weight ----------------------------------
suburbs = list(config.SUBURBS)
rng = random.Random(7)
t0 = time.monotonic()
with db.connect() as conn:
    for i in range(N_SEED):
        slug = suburbs[i % len(suburbs)]
        key = f"seed:{i}"
        db.upsert_listing(conn, {
            "listing_key": key, "source": "seed", "source_id": str(i),
            "listing_type": "sale", "url": f"https://seed.test/{i}",
            "suburb_slug": slug, "suburb": config.SUBURBS[slug].get("name", slug),
            "title": f"Seed home {i}", "price_zar": 5_000_000 + rng.randint(0, 400) * 100_000,
            "property_type": "House", "bedrooms": rng.randint(2, 6),
            "bathrooms": rng.randint(1, 5), "floor_size_m2": rng.randint(120, 900),
            "erf_size_m2": rng.randint(300, 2000), "agency": f"Agency {i % 40}",
            "agent_name": f"Agent {i % 120}", "description": "seeded " * 60,
            "photo_count": 12, "photo_url": "-", "street_address": f"{i} Seed Rd",
            "latitude": -33.9 + rng.random() / 20, "longitude": 18.38 + rng.random() / 20,
            "mandate_text": "", "mandate_explicit": 0,
        })
        # Two listings per property, so grouping has members to merge.
        conn.execute("INSERT OR REPLACE INTO property_groups (group_id, listing_key,"
                     " agency_count, source_count, match_evidence) VALUES (?,?,?,?,?)",
                     (i // 2, key, 2, 1, "seeded pair"))
        conn.execute("INSERT OR REPLACE INTO scores (listing_key, scored_by, mandate_verdict,"
                     " sellable, prospect_score, luxury_fit, open_mandate_confidence,"
                     " marketing_weakness, tier, reasoning, pitch_angle, red_flags)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (key, "heuristic", rng.choice(["open", "probably_open", "unknown"]),
                      1, rng.randint(10, 95), rng.randint(1, 10), rng.randint(1, 10),
                      rng.randint(1, 10), rng.choice(["hot", "warm", "cold"]),
                      "seeded reasoning " * 20, "seeded pitch", "[]"))
print(f"seeded {N_SEED} listings in {time.monotonic() - t0:.1f}s")

# --- the auto-crawl helpers ---------------------------------------------------
import webapp  # noqa: E402  (after seeding: the boot warm-up builds this book)

H = config.AUTO_CRAWL_HOUR
now = datetime(2026, 9, 25, H, 10)
off_hour = now.replace(hour=(H + 1) % 24)
MIN_H = config.AUTO_FULL_MIN_HOURS
check("full due: never ran, in the hour", webapp._full_due(now, None) is True)
check("full not due: outside the hour", webapp._full_due(off_hour, None) is False)
check("full not due: started 1h ago (redeploy in the hour)",
      webapp._full_due(now, now - timedelta(hours=1)) is False)
check("full due: boundary, exactly AUTO_FULL_MIN_HOURS ago",
      webapp._full_due(now, now - timedelta(hours=MIN_H)) is True)
check("full not due: just inside AUTO_FULL_MIN_HOURS",
      webapp._full_due(now, now - timedelta(hours=MIN_H) + timedelta(seconds=1)) is False)
SW = config.AUTO_SWEEP_HOURS
check("sweep due: nothing ever finished", webapp._sweep_due(now, None, None) is True)
check("sweep not due: swept 1h ago", webapp._sweep_due(now, now - timedelta(hours=1), None) is False)
check("sweep not due: old sweep but a fresh full pass",
      webapp._sweep_due(now, now - timedelta(hours=SW * 3), now - timedelta(hours=1)) is False)
check("sweep due: boundary, exactly AUTO_SWEEP_HOURS ago",
      webapp._sweep_due(now, now - timedelta(hours=SW), None) is True)
check("sweep not due: just inside AUTO_SWEEP_HOURS",
      webapp._sweep_due(now, now - timedelta(hours=SW) + timedelta(seconds=1), None) is False)
_saved = config.AUTO_SWEEP_HOURS
config.AUTO_SWEEP_HOURS = 0
check("sweep never due when AUTO_SWEEP_HOURS=0", webapp._sweep_due(now, None, None) is False)
config.AUTO_SWEEP_HOURS = _saved

# --- first-boot bootstrap of the sweep stamp -----------------------------------
# No stamp yet on a populated database: the last for-sale sighting (seeded
# rows were just seen) becomes the last sweep, so a deploy does not sweep.
with db.connect() as conn:
    conn.execute("DELETE FROM app_state WHERE key LIKE 'auto_%'")
    conn.commit()
st = webapp._auto_stamps()
real_now = datetime.now()
check("bootstrap derives a sweep stamp from last_seen", st["auto_last_sweep"] is not None)
check("bootstrap stamp is local time, not UTC",
      st["auto_last_sweep"] is not None
      and abs((real_now - st["auto_last_sweep"]).total_seconds()) < 600,
      st["auto_last_sweep"])
check("after bootstrap no sweep is due",
      webapp._sweep_due(real_now, st["auto_last_sweep"], st["auto_last_full"]) is False)
with db.connect() as conn:
    check("bootstrap stamp is persisted", db.get_state(conn, "auto_last_sweep") is not None)
# An empty listings table leaves it unset, so a brand-new database sweeps.
empty_db = os.path.join(data, "empty-bootstrap.db")
with db.connect(empty_db) as conn:
    webapp._bootstrap_sweep_stamp(conn)
    empty_stamp = db.get_state(conn, "auto_last_sweep")
check("empty database: no bootstrap stamp", empty_stamp is None, empty_stamp)
check("empty database: a sweep stays due", webapp._sweep_due(real_now, None, None) is True)
with db.connect() as conn:
    conn.execute("DELETE FROM app_state WHERE key LIKE 'auto_%'")
    conn.commit()

# --- latency while a crawl runs ----------------------------------------------
BASIC = {"Authorization": "Basic " + base64.b64encode(b"owner:check-pass").decode()}

# Let the boot warm-up land first, as it would long before anyone crawls.
deadline = time.monotonic() + 120
while (False, "sale") not in webapp._prospects_cache and time.monotonic() < deadline:
    time.sleep(0.2)
check("boot warm-up built the default book", (False, "sale") in webapp._prospects_cache)

ENDPOINTS = ["/", "/prospects", "/online", "/api/status", "/api/stats",
             "/api/home", "/api/prospects"]
samples: dict[str, list[float]] = {p: [] for p in ENDPOINTS}
bad_status: list[str] = []
samples_lock = threading.Lock()
stop_polling = threading.Event()


def timed_get(client, path):
    t = time.perf_counter()
    r = client.get(path, headers=BASIC)
    r.get_data()
    dt = time.perf_counter() - t
    if r.status_code != 200:
        bad_status.append(f"{path} -> {r.status_code}")
    return dt


def poller(path):
    c = webapp.app.test_client()
    while not stop_polling.is_set():
        timed_get(c, path)
        stop_polling.wait(2.0)


# --- /api/home payload shape (idle, then again mid-crawl below) -------------
def check_home(label, client):
    r = client.get("/api/home", headers=BASIC)
    check(f"/api/home {label}: 200", r.status_code == 200, r.status_code)
    home = r.get_json(silent=True) or {}
    check(f"/api/home {label}: hot is an int", isinstance(home.get("hot"), int),
          home.get("hot"))
    stats = client.get("/api/stats", headers=BASIC).get_json()
    check(f"/api/home {label}: stats has the /api/stats keys",
          isinstance(home.get("stats"), dict) and set(home["stats"]) == set(stats))
    series = home.get("series") or {}
    check(f"/api/home {label}: series.days has 14 days", len(series.get("days") or []) == 14)
    check(f"/api/home {label}: every series has 14 points",
          all(len(series.get(k) or []) == 14 for k in ("new_listings", "price_cuts", "scored")))
    check(f"/api/home {label}: events is a list (max 40)",
          isinstance(home.get("events"), list) and len(home["events"]) <= 40)
    check(f"/api/home {label}: crawl.running present",
          isinstance((home.get("crawl") or {}).get("running"), bool))
    return home


home = check_home("idle", webapp.app.test_client())
check("/api/home idle: seeded listings show in the series",
      sum(home.get("series", {}).get("new_listings") or []) >= N_SEED,
      home.get("series", {}).get("new_listings"))
check("/api/home idle: events carry t/kind/who/tone/text",
      all({"t", "kind", "who", "tone", "text"} <= set(e) and e["t"].endswith("Z")
          for e in home.get("events") or []) and bool(home.get("events")))

check("crawl starts", webapp._start_job(["bakoven"], ["fake"], pages=1, use_ai=False,
                                        listing_types=("rent",)))
pollers = [threading.Thread(target=poller, args=(p,), daemon=True)
           for p in ("/api/status", "/api/prospects")]
for t in pollers:
    t.start()

client = webapp.app.test_client()
home = check_home("mid-crawl", client)
check("/api/home mid-crawl: crawl.running and a live Crawling event",
      (home.get("crawl") or {}).get("running") is True
      and any(e.get("kind") == "crawl" and e.get("text", "").startswith("Crawling")
              for e in home.get("events") or []))
t_start = time.monotonic()
while webapp.job["running"] and time.monotonic() - t_start < 90:
    for path in ENDPOINTS:
        dt = timed_get(client, path)
        with samples_lock:
            samples[path].append(dt)
    time.sleep(0.1)
crawl_s = time.monotonic() - t_start
still_running = webapp.job["running"]
stop_polling.set()
for t in pollers:
    t.join(timeout=10)
# The crawl should be over; give the exit handshake a moment if not.
deadline = time.monotonic() + 30
while webapp.job["running"] and time.monotonic() < deadline:
    time.sleep(0.2)


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


print()
print(f"crawl ran {crawl_s:.1f}s  (budget: p95 < {BUDGET:.2f}s)")
print(f"{'endpoint':<16}{'n':>5}{'p50 ms':>10}{'p95 ms':>10}{'max ms':>10}")
for path in ENDPOINTS:
    xs = samples[path]
    if not xs:
        print(f"{path:<16}{0:>5}")
        continue
    print(f"{path:<16}{len(xs):>5}{pct(xs, .5) * 1000:>10.0f}"
          f"{pct(xs, .95) * 1000:>10.0f}{max(xs) * 1000:>10.0f}")
print()

check("crawl finished inside 90 s", not still_running)
check("crawl ended with phase done", webapp.job["phase"] == "done", webapp.job["phase"])
check("done == total == 150", webapp.job["done"] == webapp.job["total"] == 150,
      (webapp.job["done"], webapp.job["total"]))
check("ran as a separate process", "crawler: started pid" in " ".join(webapp.job["log"]))
check('no "database is locked" in the log',
      not any("database is locked" in line for line in webapp.job["log"]))
check("every request answered 200", not bad_status, bad_status[:5])
for path in ENDPOINTS:
    xs = samples[path]
    check(f"{path} sampled", len(xs) >= 3, len(xs))
    if xs:
        check(f"{path} p95 < {BUDGET:.2f}s", pct(xs, .95) < BUDGET, f"{pct(xs, .95):.3f}s")

print()
print(f"{len(failures)} failure(s)" if failures else "all checks passed")
sys.exit(1 if failures else 0)
