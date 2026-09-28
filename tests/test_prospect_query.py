"""Tests for the server-side prospect query, CSV export, saved views and the
auto-crawl schedule API.

    .venv/bin/python -m pytest tests/test_prospect_query.py -q

Self-contained like test_chat.py: DATA_DIR is a fresh temp directory set
before webapp is imported, so nothing here can touch a real prospects.db.
Run it on its own (each of these files pins DATA_DIR at import).
"""

from __future__ import annotations

import csv
import io
import os
import sys
import tempfile
from datetime import datetime, timedelta

DATA = tempfile.mkdtemp(prefix="pq-test-")
os.environ["DATA_DIR"] = DATA
for k in ("DB_PATH", "DATABASE_URL", "CACHE_DIR"):
    os.environ.pop(k, None)
os.environ["MEDIA_ROOT"] = tempfile.mkdtemp(prefix="pq-media-root-")
os.environ["DASHBOARD_USER"] = "owner"
os.environ["DASHBOARD_PASSWORD"] = "check-pass"
os.environ["AUTO_CRAWL"] = "0"
os.environ["PROSPECTS_NO_WARM"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

assert os.path.abspath(config.DB_PATH).startswith(os.path.abspath(DATA)), config.DB_PATH

import db  # noqa: E402

# ---- seed: 30 properties, 2 listings each for the even ones ---------------
SUBS = ["clifton", "camps-bay", "sea-point"]
TYPES = ["House", "Apartment / Flat", "Townhouse"]
with db.connect() as _c:
    for i in range(30):
        slug = SUBS[i % 3]
        members = 2 if i % 2 == 0 else 1
        for m in range(members):
            key = f"seed:{i}:{m}"
            db.upsert_listing(_c, {
                "listing_key": key, "source": ["alpha", "beta"][m],
                "source_id": f"{i}{m}", "listing_type": "sale",
                "url": f"https://seed.test/{i}/{m}", "suburb_slug": slug,
                "suburb": config.SUBURBS[slug]["name"],
                "title": f"Seed home {i}" + (" with pool" if i == 6 else ""),
                "price_zar": 3_000_000 + i * 1_000_000,
                "property_type": TYPES[i % 3], "bedrooms": 1 + i % 6,
                "bathrooms": 1 + i % 3, "floor_size_m2": 100 + i * 10,
                "erf_size_m2": 300 + i * 20,
                "agency": f"Agency {m}" if members == 2 else "Solo Realty",
                "listing_date": (datetime.now() - timedelta(days=i * 5))
                .strftime("%Y-%m-%d"),
                "photo_url": "https://img.test/x.jpg" if i % 4 else "-",
                "under_offer": 1 if i == 5 else 0,
            })
            _c.execute("INSERT INTO property_groups (group_id, listing_key,"
                       " agency_count, source_count) VALUES (?,?,?,?)",
                       (i, key, members, members))
            verdict = ["open", "probably_open", "unknown", "sole"][i % 4]
            _c.execute("INSERT INTO scores (listing_key, tier, prospect_score,"
                       " mandate_verdict, sellable, marketing_weakness)"
                       " VALUES (?,?,?,?,?,?)",
                       (key, ["hot", "warm", "cold"][i % 3], 100 - i, verdict,
                        0 if verdict == "sole" else 1, i % 10))
    # A 20% cut on property 5 (its first sighting was higher).
    _c.execute("INSERT INTO price_history (listing_key, price_zar, observed_at)"
               " VALUES ('seed:5:0', 10000000, '2026-01-01 00:00:00')")
    _c.commit()

import auth    # noqa: E402
import crawl_schedule  # noqa: E402
import prospect_query  # noqa: E402
import webapp  # noqa: E402

app = webapp.app
_now = auth._now()
with db.connect() as _c:
    _c.execute("INSERT INTO users (username, display_name, role, privileges,"
               " created_at, disabled) VALUES ('sam','Sam','member','[\"leads\"]',?,0)",
               (_now,))
    _c.commit()


def client_for(username):
    c = app.test_client()
    c.set_cookie(auth.COOKIE_NAME, auth.create_session(username, f"test/{username}"))
    return c


owner, sam = client_for("owner"), client_for("sam")


def q(qs="", client=None):
    r = (client or owner).get("/api/prospects/query" + ("?" + qs if qs else ""))
    assert r.status_code == 200, r.data[:300]
    return r.get_json()


# ------------------------------------------------------------------ query

def test_default_matches_legacy_list():
    legacy = owner.get("/api/prospects").get_json()
    d = q("limit=500")
    assert d["total"] == len(legacy)
    assert [r["listing_key"] for r in d["rows"]] == [r["listing_key"] for r in legacy]
    # sole mandates (i % 4 == 3: 7 of the 30) are hidden by default
    assert d["total"] == 23


def test_page_is_small_and_paged():
    d = q("limit=5")
    assert len(d["rows"]) == 5 and d["total"] > 5
    d2 = q("limit=5&offset=5")
    assert not {r["listing_key"] for r in d["rows"]} & {r["listing_key"] for r in d2["rows"]}
    assert "reasoning" not in d["rows"][0] and "listings" not in d["rows"][0]


def test_facets_ignore_their_own_filter():
    all_ = q()
    one = q("suburb=Clifton")
    assert all(r["suburb"] == "Clifton" for r in one["rows"])
    # picking Clifton still shows the other suburbs' counts
    assert one["facets"]["suburb"] == all_["facets"]["suburb"]
    assert one["total"] == all_["facets"]["suburb"]["Clifton"]
    # but other facets narrow to Clifton
    assert sum(one["facets"]["tier"].values()) == one["total"]


def test_filters():
    rows = q("tier=hot&limit=500")["rows"]
    assert rows and all(r["tier"] == "hot" for r in rows)
    rows = q("beds_min=3&beds_max=4&limit=500")["rows"]
    assert rows and all(3 <= r["bedrooms"] <= 4 for r in rows)
    rows = q("price_min=10000000&price_max=15000000&limit=500")["rows"]
    assert rows and all(10e6 <= r["price_zar"] <= 15e6 for r in rows)
    rows = q("ptype=Apartment&limit=500")["rows"]
    assert rows and all("Apartment" in r["property_type"] for r in rows)
    rows = q("agencies_min=2&limit=500")["rows"]
    assert rows and all(r["brand_count"] >= 2 for r in rows)
    rows = q("source=beta&limit=500")["rows"]
    assert rows and all(int(r["listing_key"].split(":")[1]) % 2 == 0 for r in rows)
    rows = q("q=pool")["rows"]
    assert [r["title"] for r in rows] == ["Seed home 6 with pool"]
    assert q("under_offer=1")["total"] == 1
    assert q("cut=15")["rows"][0]["listing_key"].startswith("seed:5:")
    rows = q("dom_min=50&limit=500")["rows"]
    assert rows and all(r["days_on_market"] >= 50 for r in rows)
    assert q("photo=0")["total"] > 0
    assert q("mandate=open")["total"] > 0
    # asking for sole mandates by name brings the sole book in
    sole = q("mandate=sole")
    assert sole["total"] > 0 and sole["sole"] is True


def test_sorts():
    rows = q("sort=priceasc&limit=500")["rows"]
    prices = [r["price_zar"] for r in rows]
    assert prices == sorted(prices)
    rows = q("sort=stale&limit=500")["rows"]
    dom = [r["days_on_market"] for r in rows]
    assert dom == sorted(dom, reverse=True)


def test_bad_params_are_ignored():
    d = q("beds_min=lots&tier=nope&sort=wat&limit=-3&offset=x")
    assert d["total"] == q()["total"] and len(d["rows"]) == 1


def test_etag_304():
    r = owner.get("/api/prospects/query?tier=warm")
    r2 = owner.get("/api/prospects/query?tier=warm",
                   headers={"If-None-Match": r.headers["ETag"]})
    assert r2.status_code == 304


def test_lead_filter():
    with db.connect() as c:
        import panel
        panel.ensure_schema(c)
        c.execute("INSERT INTO tracked_property (group_id, stage)"
                  " VALUES ('0', 'contacted')")
        c.commit()
    webapp._tracked_cache = None
    assert [r["group_id"] for r in q("lead=tracked")["rows"]] == [0]
    assert q("lead=contacted")["total"] == 1
    assert q("lead=untracked")["total"] == q()["total"] - 1


def test_summary():
    s = q()["summary"]
    assert s["total"] == q()["total"] and s["hot"] >= 1


# -------------------------------------------------------------------- csv

def test_csv_export():
    r = owner.get("/api/prospects/export.csv?tier=hot")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    assert "attachment" in r.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(r.data.decode("utf-8-sig"))))
    assert rows[0][0] == "Listing key"
    assert len(rows) - 1 == q("tier=hot")["total"]


# ------------------------------------------------------------------ views

def test_saved_views_per_user():
    d = owner.get("/api/prospects/views").get_json()
    assert d["views"] == [] and len(d["presets"]) >= 5
    r = owner.post("/api/prospects/views",
                   json={"name": "My hot", "params": "?tier=hot&offset=60"})
    assert r.status_code == 201
    v = r.get_json()
    assert v["params"] == "tier=hot"
    assert [x["name"] for x in owner.get("/api/prospects/views").get_json()["views"]] == ["My hot"]
    assert sam.get("/api/prospects/views").get_json()["views"] == []
    assert owner.post("/api/prospects/views", json={"name": ""}).status_code == 400
    assert owner.delete(f"/api/prospects/views/{v['id']}").status_code == 200
    assert owner.get("/api/prospects/views").get_json()["views"] == []


# --------------------------------------------------------------- schedule

def test_schedule_get_and_patch():
    d = owner.get("/api/crawl/schedule").get_json()
    assert d["settings"]["sweep_hours"] == config.AUTO_SWEEP_HOURS
    assert d["can_edit"] is True and d["settings"]["enabled"] is False
    assert sam.get("/api/crawl/schedule").get_json()["can_edit"] is False
    assert sam.patch("/api/crawl/schedule", json={"sweep_hours": 8}).status_code == 403
    assert owner.patch("/api/crawl/schedule", json={"sweep_hours": 0.5}).status_code == 400
    assert owner.patch("/api/crawl/schedule", json={"bogus": 1}).status_code == 400
    r = owner.patch("/api/crawl/schedule",
                    json={"sweep_hours": 8, "sweep_from": 18, "sweep_to": 7})
    assert r.status_code == 200
    d = r.get_json()
    assert d["settings"]["sweep_hours"] == 8 and d["settings"]["sweep_from"] == 18
    assert set(d["customised"]) == {"sweep_hours", "sweep_from", "sweep_to"}
    # persisted: a fresh read (as after a restart) sees it
    with db.connect() as c:
        assert crawl_schedule.load(c)["sweep_hours"] == 8
    r = owner.patch("/api/crawl/schedule", json={"reset": True})
    assert r.get_json()["customised"] == []


def test_schedule_logic():
    s = crawl_schedule.defaults() | {"sweep_hours": 12, "sweep_from": 0,
                                     "sweep_to": 0, "full_hour": 1}
    t0 = datetime(2026, 9, 28, 8, 0)
    # counted from the START: a sweep that ran 3 h does not push the next one
    st = {"auto_last_sweep_started": t0, "auto_last_sweep": t0 + timedelta(hours=3)}
    base = crawl_schedule.sweep_base(st)
    assert base == t0
    assert not crawl_schedule.sweep_due(t0 + timedelta(hours=11, minutes=59), base, s)
    assert crawl_schedule.sweep_due(t0 + timedelta(hours=12), base, s)
    # window 18-07: 22:00 is inside it, 10:00 is not
    w = s | {"sweep_from": 18, "sweep_to": 7}
    assert crawl_schedule.sweep_due(datetime(2026, 9, 28, 22, 0), base, w)
    assert not crawl_schedule.sweep_due(datetime(2026, 9, 29, 10, 0), base, w)
    nxt = crawl_schedule.next_sweep(datetime(2026, 9, 29, 10, 0), st, w, 1800)
    assert nxt.hour == 18
    # interrupted sweep (never ended) is retried after the retry gap only
    st2 = {"auto_last_sweep_started": t0}
    assert not crawl_schedule.sweep_interrupted(t0 + timedelta(minutes=10), st2, 1800)
    assert crawl_schedule.sweep_interrupted(t0 + timedelta(minutes=31), st2, 1800)
    st2["auto_last_sweep_ended"] = t0 + timedelta(minutes=5)   # stopped
    assert not crawl_schedule.sweep_interrupted(t0 + timedelta(hours=2), st2, 1800)
    # full pass catch-up window
    assert crawl_schedule.full_due(datetime(2026, 9, 28, 3, 0), None, s)
    assert not crawl_schedule.full_due(datetime(2026, 9, 28, 6, 0), None, s)
    assert not crawl_schedule.full_due(datetime(2026, 9, 28, 3, 0), None,
                                       s | {"full_enabled": False})


def test_idle_skipping():
    s = crawl_schedule.defaults() | {"skip_idle_after": 2, "reprobe_every": 3}
    idle = {}
    crawled = [("alpha", "clifton"), ("alpha", "camps-bay")]
    for _ in range(2):
        idle = crawl_schedule.record(idle, crawled, [],
                                     {("alpha", "camps-bay"): 4}, "sweep")
    skips = crawl_schedule.plan_skips(idle, ["clifton", "camps-bay"], ["alpha"], s)
    assert skips == [["alpha", "clifton"]]
    # skipped twice, then the third sweep re-probes it
    for _ in range(2):
        idle = crawl_schedule.record(idle, [("alpha", "camps-bay")],
                                     [("alpha", "clifton")], {}, "sweep")
    assert crawl_schedule.plan_skips(idle, ["clifton"], ["alpha"], s) == []
    # something new clears it
    idle = crawl_schedule.record(idle, [("alpha", "clifton")], [],
                                 {("alpha", "clifton"): 1}, "sweep")
    assert "alpha|clifton" not in idle
    # a full pass never adds idleness
    idle = crawl_schedule.record({}, crawled, [], {}, "full")
    assert idle == {}
    # whole-town areas are never skipped
    town = [k for k, v in config.SUBURBS.items() if v.get("scope") == "town"]
    if town:
        assert crawl_schedule.skippable(town, ["alpha"]) == []


def test_auto_tick_respects_single_job_guard(monkeypatch):
    started = []
    monkeypatch.setattr(webapp, "_start_job",
                        lambda *a, **k: started.append(k.get("kind")) or True)
    with db.connect() as c:
        crawl_schedule.save(c, {"enabled": True})
    try:
        webapp.job["running"] = True
        assert webapp._auto_tick(datetime.now()) is None
        webapp.job["running"] = False
        now = datetime(2026, 9, 28, 14, 0)
        with db.connect() as c:
            c.execute("DELETE FROM app_state WHERE key LIKE 'auto_last_%'")
            db.set_state(c, "auto_last_full_started",
                         (now - timedelta(hours=13)).isoformat())
            db.set_state(c, "auto_last_sweep_started",
                         (now - timedelta(hours=13)).isoformat())
        assert webapp._auto_tick(now) == "sweep"
        assert started == ["sweep"]
    finally:
        webapp.job["running"] = False
        with db.connect() as c:
            c.execute("DELETE FROM app_state WHERE key LIKE 'auto_%'")
            c.commit()


def test_prospect_query_type_groups():
    assert prospect_query.type_group("Apartment / Flat") == "Apartment"
    assert prospect_query.type_group("Freestanding") == "House"
    assert prospect_query.type_group("Gated Estate") == "Estate"
    assert prospect_query.type_group("") == "Other"


def test_job_finished_records_idle_pairs():
    from datetime import timezone
    started = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    with db.connect() as c:
        db.upsert_listing(c, {
            "listing_key": "fresh:1", "source": "alpha", "source_id": "f1",
            "listing_type": "sale", "url": "https://seed.test/fresh",
            "suburb_slug": "clifton", "suburb": "Clifton", "title": "Fresh",
            "price_zar": 9_000_000})
        c.commit()
    saved = dict(webapp.job)
    try:
        webapp.job.update(kind="sweep", plan={
            "suburbs": ["clifton", "bantry-bay"], "sources": ["alpha"],
            "types": ["sale"], "skip": [], "started_utc": started})
        webapp._job_finished("done")
        with db.connect() as c:
            idle = crawl_schedule.load_idle(c)
            assert db.get_state(c, "auto_last_sweep") is not None
            assert db.get_state(c, "auto_last_sweep_ended") is not None
        assert "alpha|clifton" not in idle          # found something new
        assert idle.get("alpha|bantry-bay") == [1, 0]  # one quiet sweep
        # a stopped sweep stamps its end but not a finish, and no idleness
        webapp._job_finished("stopped")
        with db.connect() as c:
            assert crawl_schedule.load_idle(c).get("alpha|bantry-bay") == [1, 0]
    finally:
        webapp.job.clear()
        webapp.job.update(saved)
        with db.connect() as c:
            c.execute("DELETE FROM app_state WHERE key LIKE 'auto_%'")
            c.commit()
