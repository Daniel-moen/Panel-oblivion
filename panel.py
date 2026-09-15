"""Management panel: the human-owned layer on top of the prospecting engine.

The engine finds and scores listings; this module tracks the properties a
person chose to pursue — pipeline stage, contacts, every contact attempt,
mandate outcomes, notes and tasks. Everything keys on the property group id
(``property_groups.group_id`` as TEXT, or ``solo-<listing_key>`` for an
ungrouped listing — the same ids /api/prospects hands out).

Flask routes live on the ``bp`` blueprint; webapp.py registers it.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

import db

bp = Blueprint("panel", __name__)

STAGES = ["new", "researching", "contact_found", "contacted", "meeting",
          "valuation_sent", "mandate_signed", "listed", "sold", "lost", "parked"]
PRIORITIES = ["low", "normal", "high"]
CONTACT_ROLES = ["owner", "agent", "attorney", "tenant", "other"]
CHANNELS = ["call", "whatsapp", "sms", "email", "visit", "letter"]
OUTCOMES = ["no_answer", "spoke", "left_message", "callback_requested",
            "not_interested", "interested", "meeting_set"]
MANDATE_TYPES = ["sole", "open", "dual", "joint", "sole_with_exclusion", "none_lost"]
LOST_REASONS = ["went_with_other_agency", "not_selling", "price_disagreement",
                "sold_privately", "other"]
TASK_KINDS = ["follow_up", "valuation", "send_cma", "mandate_renewal", "other"]

DDL = """
CREATE TABLE IF NOT EXISTS tracked_property (
    group_id     TEXT PRIMARY KEY,
    stage        TEXT NOT NULL DEFAULT 'new',
    priority     TEXT NOT NULL DEFAULT 'normal',
    assigned_to  TEXT,
    source       TEXT NOT NULL DEFAULT 'manual',   -- manual | tracker_import | auto_rule
    tracked_at   TEXT DEFAULT (datetime('now')),
    archived_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_tracked_stage ON tracked_property(stage, archived_at);

CREATE TABLE IF NOT EXISTS contacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id      TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'owner',
    name          TEXT,
    phone         TEXT,
    email         TEXT,
    id_number     TEXT,
    company       TEXT,
    provider      TEXT NOT NULL DEFAULT 'manual',  -- manual | loom | virtualagent
    consent_basis TEXT,
    notes         TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_contacts_group ON contacts(group_id);
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone);

CREATE TABLE IF NOT EXISTS interactions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id          TEXT NOT NULL,
    contact_id        INTEGER,
    channel           TEXT NOT NULL,
    direction         TEXT NOT NULL DEFAULT 'outbound',
    outcome           TEXT,
    summary           TEXT,
    occurred_at       TEXT DEFAULT (datetime('now')),
    next_follow_up_at TEXT,
    actor             TEXT
);
CREATE INDEX IF NOT EXISTS idx_interactions_group ON interactions(group_id, occurred_at);

CREATE TABLE IF NOT EXISTS mandates (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id           TEXT NOT NULL,
    type               TEXT NOT NULL,
    signed_at          TEXT,
    expires_at         TEXT,
    duration_days      INTEGER,
    listing_price      INTEGER,
    commission_pct     REAL,
    competing_agencies TEXT,
    lost_reason        TEXT,
    lost_to            TEXT,
    notes              TEXT,
    document_path      TEXT,
    created_at         TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mandates_group ON mandates(group_id);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id   TEXT NOT NULL,
    body       TEXT NOT NULL,
    pinned     INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notes_group ON notes(group_id);

CREATE TABLE IF NOT EXISTS activities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload     TEXT,
    occurred_at TEXT DEFAULT (datetime('now')),
    actor       TEXT
);
CREATE INDEX IF NOT EXISTS idx_activities_group ON activities(group_id, occurred_at);

CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id   TEXT,
    title      TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'other',
    due_at     TEXT,
    done_at    TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(done_at, due_at);

CREATE TABLE IF NOT EXISTS tags (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT UNIQUE NOT NULL,
    color TEXT
);
CREATE TABLE IF NOT EXISTS property_tags (
    group_id TEXT NOT NULL,
    tag_id   INTEGER NOT NULL,
    PRIMARY KEY (group_id, tag_id)
);

CREATE TABLE IF NOT EXISTS saved_views (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT UNIQUE NOT NULL,
    filters TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS panel_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


# ------------------------------------------------------------------ schema

def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    _migrate_legacy(conn)


def _migrate_legacy(conn: sqlite3.Connection) -> None:
    """One-shot import of the pre-panel stores: owner_details → contacts,
    tracker.prospected=1 → tracked_property(parked)."""
    done = conn.execute("SELECT value FROM panel_meta WHERE key='legacy_migrated'").fetchone()
    if done:
        return
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    n_contacts = n_tracked = 0
    if "owner_details" in tables:
        for o in conn.execute("SELECT * FROM owner_details").fetchall():
            gid = str(o["group_id"])
            if not (o["owner_name"] or o["phone"] or o["email"]):
                continue
            conn.execute(
                "INSERT OR IGNORE INTO tracked_property(group_id, stage, source) "
                "VALUES (?, 'contact_found', 'owner_import')", (gid,))
            bits = []
            if o["deed_number"]:
                bits.append(f"Deed {o['deed_number']}")
            if o["purchase_date"] or o["purchase_price"]:
                bits.append("bought " + " ".join(filter(None, [
                    o["purchase_date"],
                    f"for R{int(o['purchase_price']):,}".replace(",", " ") if o["purchase_price"] else None])))
            if o["bond_holder"]:
                bits.append(f"bond: {o['bond_holder']}")
            note = " · ".join(filter(None, [o["notes"], " · ".join(bits)]))
            conn.execute(
                "INSERT INTO contacts(group_id, role, name, phone, email, provider, "
                "notes, created_at) VALUES (?, 'owner', ?, ?, ?, ?, ?, ?)",
                (gid, o["owner_name"], o["phone"], o["email"],
                 o["provider"] or "manual", note or None, o["updated_at"]))
            n_contacts += 1
    if "tracker" in tables:
        rows = conn.execute("""
            SELECT DISTINCT COALESCE(CAST(g.group_id AS TEXT), 'solo-' || l.listing_key) AS gid
            FROM tracker t
            JOIN listings l ON l.source = 'property24' AND l.source_id = t.listing_number
            LEFT JOIN property_groups g ON g.listing_key = l.listing_key
            WHERE t.prospected = 1""").fetchall()
        for r in rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO tracked_property(group_id, stage, source) "
                "VALUES (?, 'parked', 'tracker_import')", (r["gid"],))
            n_tracked += cur.rowcount
    conn.execute("INSERT INTO panel_meta(key, value) VALUES ('legacy_migrated', ?)",
                 (json.dumps({"at": datetime.now().isoformat(timespec="seconds"),
                              "contacts": n_contacts, "tracked": n_tracked}),))


# ----------------------------------------------------------------- helpers

def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def _one(cur) -> dict | None:
    r = cur.fetchone()
    return dict(r) if r else None


def _bad(msg, code=400):
    return jsonify({"error": msg}), code


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _pick(data: dict, fields: tuple, allowed: dict | None = None):
    """Subset of data limited to fields; validates enum columns."""
    out = {}
    for f in fields:
        if f in data:
            v = data[f]
            if allowed and f in allowed and v is not None and v not in allowed[f]:
                raise ValueError(f"{f} must be one of {', '.join(allowed[f])}")
            out[f] = v
    return out


def _log(conn, gid: str, kind: str, payload: dict | None = None, actor=None):
    conn.execute("INSERT INTO activities(group_id, kind, payload, actor) VALUES (?,?,?,?)",
                 (gid, kind, json.dumps(payload or {}), actor))


def _tracked(conn, gid: str) -> dict | None:
    return _one(conn.execute("SELECT * FROM tracked_property WHERE group_id=?", (gid,)))


def _set_stage(conn, gid: str, stage: str, actor=None, reason: str | None = None):
    cur = _tracked(conn, gid)
    if cur and cur["stage"] != stage:
        conn.execute("UPDATE tracked_property SET stage=? WHERE group_id=?", (stage, gid))
        _log(conn, gid, "stage_change", {"from": cur["stage"], "to": stage,
                                         "reason": reason}, actor)


# The listing-side summary a tracked row needs to be readable in a table:
# best listing per group, plus score/erf/lifecycle. Mirrors the joins in
# webapp.PROSPECT_QUERY but only for tracked groups, so it stays cheap.
_SUMMARY_SQL = """
WITH members AS (
    SELECT tp.group_id AS gid, l.*
    FROM tracked_property tp
    JOIN listings l ON (
         (tp.group_id NOT LIKE 'solo-%' AND l.listing_key IN
             (SELECT listing_key FROM property_groups WHERE CAST(group_id AS TEXT) = tp.group_id))
      OR (tp.group_id LIKE 'solo-%' AND l.listing_key = substr(tp.group_id, 6)))
),
best AS (
    SELECT gid, listing_key, url, title, suburb, suburb_slug, price_zar, property_type,
           bedrooms, bathrooms, street_address_raw, agency, photo_url, last_seen,
           ROW_NUMBER() OVER (PARTITION BY gid ORDER BY photo_count DESC,
                              length(COALESCE(description,'')) DESC) AS rn
    FROM members
)
SELECT b.gid, b.listing_key, b.url, b.title, b.suburb, b.suburb_slug, b.price_zar,
       b.property_type, b.bedrooms, b.bathrooms, b.street_address_raw, b.agency,
       b.photo_url, b.last_seen,
       s.tier, s.prospect_score, s.mandate_verdict,
       e.erf_number, e.official_address, e.status AS erf_status,
       (SELECT COUNT(*) FROM members m WHERE m.gid = b.gid) AS listing_count,
       (SELECT COUNT(DISTINCT agency) FROM members m WHERE m.gid = b.gid) AS agency_count
FROM best b
LEFT JOIN scores s ON s.listing_key = b.listing_key
LEFT JOIN erf_lookup e ON e.listing_key = b.listing_key
WHERE b.rn = 1
"""


def _summaries(conn) -> dict[str, dict]:
    return {r["gid"]: r for r in _rows(conn.execute(_SUMMARY_SQL))}


def _panel_rollup(conn, gids: list[str]) -> dict[str, dict]:
    """Per-group: primary contact, last/next contact, attempts, current mandate,
    open task count, tag names — everything the table shows at a glance."""
    out = {g: {} for g in gids}
    if not gids:
        return out
    q = ",".join("?" * len(gids))
    for r in _rows(conn.execute(f"""
        SELECT group_id, MAX(occurred_at) AS last_contact_at, COUNT(*) AS attempts,
               SUM(outcome = 'spoke') AS spoke_count,
               MAX(next_follow_up_at) AS next_follow_up_at
        FROM interactions WHERE group_id IN ({q}) GROUP BY group_id""", gids)):
        out[r["group_id"]].update(r)
    for r in _rows(conn.execute(f"""
        SELECT i.group_id, i.outcome AS last_outcome, i.channel AS last_channel
        FROM interactions i
        JOIN (SELECT group_id, MAX(id) AS id FROM interactions
              WHERE group_id IN ({q}) GROUP BY group_id) x ON x.id = i.id""", gids)):
        out[r["group_id"]].update(r)
    for r in _rows(conn.execute(f"""
        SELECT c.group_id, c.id AS contact_id, c.name AS contact_name,
               c.phone AS contact_phone, c.email AS contact_email, c.role AS contact_role
        FROM contacts c
        JOIN (SELECT group_id, MIN(id) AS id FROM contacts
              WHERE group_id IN ({q}) GROUP BY group_id) x ON x.id = c.id""", gids)):
        out[r["group_id"]].update(r)
    for r in _rows(conn.execute(f"""
        SELECT group_id, COUNT(*) AS contact_count FROM contacts
        WHERE group_id IN ({q}) GROUP BY group_id""", gids)):
        out[r["group_id"]].update(r)
    for r in _rows(conn.execute(f"""
        SELECT m.group_id, m.type AS mandate_type, m.signed_at AS mandate_signed_at,
               m.expires_at AS mandate_expires_at, m.listing_price AS mandate_price,
               m.lost_to AS mandate_lost_to
        FROM mandates m
        JOIN (SELECT group_id, MAX(id) AS id FROM mandates
              WHERE group_id IN ({q}) GROUP BY group_id) x ON x.id = m.id""", gids)):
        out[r["group_id"]].update(r)
    for r in _rows(conn.execute(f"""
        SELECT group_id, COUNT(*) AS open_tasks, MIN(due_at) AS next_task_due
        FROM tasks WHERE done_at IS NULL AND group_id IN ({q}) GROUP BY group_id""", gids)):
        out[r["group_id"]].update(r)
    for r in _rows(conn.execute(f"""
        SELECT pt.group_id, t.name FROM property_tags pt JOIN tags t ON t.id = pt.tag_id
        WHERE pt.group_id IN ({q})""", gids)):
        out[r["group_id"]].setdefault("tags", []).append(r["name"])
    for r in _rows(conn.execute(f"""
        SELECT group_id, COUNT(*) AS note_count FROM notes
        WHERE group_id IN ({q}) GROUP BY group_id""", gids)):
        out[r["group_id"]].update(r)
    return out


def _enrich(conn, tracked: list[dict]) -> list[dict]:
    gids = [t["group_id"] for t in tracked]
    summ = _summaries(conn)
    roll = _panel_rollup(conn, gids)
    out = []
    for t in tracked:
        d = dict(t)
        d.update({k: v for k, v in (summ.get(t["group_id"]) or {}).items() if k != "gid"})
        d.update(roll.get(t["group_id"], {}))
        d.setdefault("tags", [])
        d["cma_url"] = (f"/cma/{t['group_id']}"
                        if not str(t["group_id"]).startswith("solo-") else None)
        out.append(d)
    return out


def record_owner(conn, gid: str, data: dict, note: str | None = None,
                 provider: str = "loom") -> None:
    """Mirror a deeds/VA lookup into the panel: track the property if it isn't,
    and add (or refresh) an owner contact. Idempotent per (gid, provider)."""
    ensure_schema(conn)
    if not (data.get("owner_name") or data.get("phone") or data.get("email")):
        return
    if not _tracked(conn, gid):
        conn.execute("INSERT INTO tracked_property(group_id, stage, source) "
                     "VALUES (?, 'contact_found', ?)", (gid, provider))
        _log(conn, gid, "tracked", {"stage": "contact_found", "via": provider})
    bits = [note]
    if data.get("deed_number"):
        bits.append(f"Deed {data['deed_number']}")
    if data.get("purchase_date") or data.get("purchase_price"):
        price = data.get("purchase_price")
        bits.append("bought " + " ".join(filter(None, [
            data.get("purchase_date"),
            f"for R{int(price):,}".replace(",", " ") if price else None])))
    if data.get("bond_holder"):
        bits.append(f"bond: {data['bond_holder']}")
    notes = " · ".join(b for b in bits if b)
    existing = conn.execute(
        "SELECT id FROM contacts WHERE group_id=? AND provider=? AND role='owner'",
        (gid, provider)).fetchone()
    if existing:
        conn.execute("UPDATE contacts SET name=?, phone=COALESCE(?, phone), "
                     "email=COALESCE(?, email), notes=? WHERE id=?",
                     (data.get("owner_name"), data.get("phone"), data.get("email"),
                      notes, existing["id"]))
        return
    cur = conn.execute(
        "INSERT INTO contacts(group_id, role, name, phone, email, company, provider, "
        "consent_basis, notes) VALUES (?, 'owner', ?, ?, ?, ?, ?, 'public_record', ?)",
        (gid, data.get("owner_name"), data.get("phone"), data.get("email"),
         data.get("owner_type"), provider, notes))
    _log(conn, gid, "contact_added", {"id": cur.lastrowid, "name": data.get("owner_name"),
                                      "role": "owner", "via": provider})
    t = _tracked(conn, gid)
    if t and t["stage"] in ("new", "researching"):
        _set_stage(conn, gid, "contact_found", reason=f"{provider} lookup")


# ------------------------------------------------------------ /api/tracked

@bp.get("/api/panel/meta")
def api_meta():
    return jsonify({"stages": STAGES, "priorities": PRIORITIES, "roles": CONTACT_ROLES,
                    "channels": CHANNELS, "outcomes": OUTCOMES,
                    "mandate_types": MANDATE_TYPES, "lost_reasons": LOST_REASONS,
                    "task_kinds": TASK_KINDS})


@bp.get("/api/tracked")
def api_tracked_list():
    stage = request.args.get("stage")
    archived = request.args.get("archived") == "1"
    q = "SELECT * FROM tracked_property WHERE " + \
        ("archived_at IS NOT NULL" if archived else "archived_at IS NULL")
    params: list = []
    if stage:
        q += " AND stage = ?"
        params.append(stage)
    q += " ORDER BY tracked_at DESC"
    with db.connect() as conn:
        ensure_schema(conn)
        rows = _rows(conn.execute(q, params))
        return jsonify(_enrich(conn, rows))


@bp.get("/api/tracked/ids")
def api_tracked_ids():
    """group_id → stage for every live tracked property; the prospect list
    uses it to badge cards without pulling the whole panel payload."""
    with db.connect() as conn:
        ensure_schema(conn)
        return jsonify({r["group_id"]: r["stage"] for r in _rows(conn.execute(
            "SELECT group_id, stage FROM tracked_property WHERE archived_at IS NULL"))})


@bp.post("/api/tracked")
def api_track():
    data = _body()
    gid = str(data.get("group_id") or "").strip()
    if not gid:
        return _bad("group_id required")
    stage = data.get("stage") or "new"
    if stage not in STAGES:
        return _bad("bad stage")
    with db.connect() as conn:
        ensure_schema(conn)
        existing = _tracked(conn, gid)
        if existing:
            if existing["archived_at"]:
                conn.execute("UPDATE tracked_property SET archived_at=NULL WHERE group_id=?", (gid,))
                _log(conn, gid, "restored")
            return jsonify(_enrich(conn, [_tracked(conn, gid)])[0])
        conn.execute(
            "INSERT INTO tracked_property(group_id, stage, priority, assigned_to, source) "
            "VALUES (?,?,?,?,?)",
            (gid, stage, data.get("priority") or "normal", data.get("assigned_to"),
             data.get("source") or "manual"))
        _log(conn, gid, "tracked", {"stage": stage})
        return jsonify(_enrich(conn, [_tracked(conn, gid)])[0]), 201


@bp.get("/api/tracked/<gid>")
def api_tracked_get(gid):
    with db.connect() as conn:
        ensure_schema(conn)
        t = _tracked(conn, gid)
        if not t:
            return _bad("not tracked", 404)
        d = _enrich(conn, [t])[0]
        d["contacts"] = _rows(conn.execute(
            "SELECT * FROM contacts WHERE group_id=? ORDER BY id", (gid,)))
        d["interactions"] = _rows(conn.execute(
            "SELECT i.*, c.name AS contact_name FROM interactions i "
            "LEFT JOIN contacts c ON c.id = i.contact_id "
            "WHERE i.group_id=? ORDER BY i.occurred_at DESC, i.id DESC", (gid,)))
        d["mandates"] = _rows(conn.execute(
            "SELECT * FROM mandates WHERE group_id=? ORDER BY id DESC", (gid,)))
        d["notes"] = _rows(conn.execute(
            "SELECT * FROM notes WHERE group_id=? ORDER BY pinned DESC, id DESC", (gid,)))
        d["tasks"] = _rows(conn.execute(
            "SELECT * FROM tasks WHERE group_id=? ORDER BY done_at IS NOT NULL, due_at", (gid,)))
        acts = _rows(conn.execute(
            "SELECT * FROM activities WHERE group_id=? ORDER BY occurred_at DESC, id DESC LIMIT 200",
            (gid,)))
        for a in acts:
            try:
                a["payload"] = json.loads(a["payload"] or "{}")
            except ValueError:
                a["payload"] = {}
        d["activities"] = acts
        d["listings"] = _rows(conn.execute("""
            SELECT l.listing_key, l.source, l.url, l.price_zar, l.agency, l.agent_name,
                   l.listing_date, l.first_seen, l.last_seen, ll.status AS lifecycle
            FROM listings l LEFT JOIN listing_lifecycle ll ON ll.listing_key = l.listing_key
            WHERE l.listing_key IN (
                SELECT listing_key FROM property_groups WHERE CAST(group_id AS TEXT) = ?)
               OR l.listing_key = ?""", (gid, gid[5:] if gid.startswith("solo-") else "")))
        keys = [l["listing_key"] for l in d["listings"]]
        if keys:
            d["price_history"] = _rows(conn.execute(
                f"SELECT listing_key, price_zar, observed_at FROM price_history "
                f"WHERE listing_key IN ({','.join('?' * len(keys))}) ORDER BY observed_at",
                keys))
        else:
            d["price_history"] = []
        return jsonify(d)


@bp.patch("/api/tracked/<gid>")
def api_tracked_patch(gid):
    data = _body()
    try:
        fields = _pick(data, ("stage", "priority", "assigned_to", "archived"),
                       {"stage": STAGES, "priority": PRIORITIES})
    except ValueError as e:
        return _bad(str(e))
    with db.connect() as conn:
        ensure_schema(conn)
        if not _tracked(conn, gid):
            return _bad("not tracked", 404)
        if "stage" in fields:
            _set_stage(conn, gid, fields["stage"], data.get("actor"), data.get("reason"))
        for col in ("priority", "assigned_to"):
            if col in fields:
                conn.execute(f"UPDATE tracked_property SET {col}=? WHERE group_id=?",
                             (fields[col], gid))
        if "archived" in fields:
            conn.execute("UPDATE tracked_property SET archived_at=? WHERE group_id=?",
                         (datetime.now().isoformat(timespec="seconds") if fields["archived"] else None, gid))
            _log(conn, gid, "archived" if fields["archived"] else "restored")
        return jsonify(_enrich(conn, [_tracked(conn, gid)])[0])


@bp.delete("/api/tracked/<gid>")
def api_tracked_delete(gid):
    """Hard delete (POPIA purge): the tracked row and everything hanging off it."""
    with db.connect() as conn:
        ensure_schema(conn)
        for t in ("contacts", "interactions", "mandates", "notes", "activities",
                  "tasks", "property_tags", "tracked_property"):
            conn.execute(f"DELETE FROM {t} WHERE group_id=?", (gid,))
        return jsonify({"deleted": gid})


# --------------------------------------------------------- child resources

def _child_routes(name: str, fields: tuple, enums: dict, on_create=None, order="id DESC"):
    """Generic list/create/patch/delete for a per-property child table."""

    def list_():
        def fn(gid):
            with db.connect() as conn:
                ensure_schema(conn)
                return jsonify(_rows(conn.execute(
                    f"SELECT * FROM {name} WHERE group_id=? ORDER BY {order}", (gid,))))
        fn.__name__ = f"{name}_list"
        return fn

    def create():
        def fn(gid):
            data = _body()
            try:
                vals = _pick(data, fields, enums)
            except ValueError as e:
                return _bad(str(e))
            with db.connect() as conn:
                ensure_schema(conn)
                if not _tracked(conn, gid):
                    # Adding a contact/note to an untracked property tracks it.
                    conn.execute("INSERT INTO tracked_property(group_id) VALUES (?)", (gid,))
                    _log(conn, gid, "tracked", {"stage": "new", "via": name})
                cols = ["group_id"] + list(vals)
                cur = conn.execute(
                    f"INSERT INTO {name}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    [gid] + list(vals.values()))
                row = _one(conn.execute(f"SELECT * FROM {name} WHERE id=?", (cur.lastrowid,)))
                if on_create:
                    on_create(conn, gid, row, data)
                return jsonify(row), 201
        fn.__name__ = f"{name}_create"
        return fn

    def patch():
        def fn(gid, rid):
            data = _body()
            try:
                vals = _pick(data, fields, enums)
            except ValueError as e:
                return _bad(str(e))
            if not vals:
                return _bad("nothing to update")
            with db.connect() as conn:
                ensure_schema(conn)
                sets = ",".join(f"{k}=?" for k in vals)
                cur = conn.execute(f"UPDATE {name} SET {sets} WHERE id=? AND group_id=?",
                                   list(vals.values()) + [rid, gid])
                if cur.rowcount == 0:
                    return _bad("not found", 404)
                return jsonify(_one(conn.execute(f"SELECT * FROM {name} WHERE id=?", (rid,))))
        fn.__name__ = f"{name}_patch"
        return fn

    def delete():
        def fn(gid, rid):
            with db.connect() as conn:
                ensure_schema(conn)
                cur = conn.execute(f"DELETE FROM {name} WHERE id=? AND group_id=?", (rid, gid))
                if cur.rowcount == 0:
                    return _bad("not found", 404)
                _log(conn, gid, f"{name}_deleted", {"id": rid})
                return jsonify({"deleted": rid})
        fn.__name__ = f"{name}_delete"
        return fn

    base = f"/api/tracked/<gid>/{name}"
    bp.add_url_rule(base, view_func=list_(), methods=["GET"])
    bp.add_url_rule(base, view_func=create(), methods=["POST"])
    bp.add_url_rule(base + "/<int:rid>", view_func=patch(), methods=["PATCH"])
    bp.add_url_rule(base + "/<int:rid>", view_func=delete(), methods=["DELETE"])


def _after_contact(conn, gid, row, data):
    _log(conn, gid, "contact_added", {"id": row["id"], "name": row["name"], "role": row["role"]})
    t = _tracked(conn, gid)
    if t and t["stage"] in ("new", "researching"):
        _set_stage(conn, gid, "contact_found", reason="contact added")


def _after_interaction(conn, gid, row, data):
    _log(conn, gid, "interaction", {"id": row["id"], "channel": row["channel"],
                                    "outcome": row["outcome"], "summary": row["summary"]})
    t = _tracked(conn, gid)
    if t:
        if row["outcome"] == "meeting_set" and t["stage"] in STAGES[:4]:
            _set_stage(conn, gid, "meeting", reason="meeting set")
        elif t["stage"] in ("new", "researching", "contact_found"):
            _set_stage(conn, gid, "contacted", reason=f"{row['channel']} logged")
    if row["next_follow_up_at"]:
        conn.execute(
            "INSERT INTO tasks(group_id, title, kind, due_at) VALUES (?,?,?,?)",
            (gid, f"Follow up ({row['channel']})"
                  + (f": {row['summary'][:60]}" if row["summary"] else ""),
             "follow_up", row["next_follow_up_at"]))


def _after_mandate(conn, gid, row, data):
    _log(conn, gid, "mandate", {"id": row["id"], "type": row["type"],
                                "lost_to": row["lost_to"], "expires_at": row["expires_at"]})
    if row["type"] == "none_lost":
        _set_stage(conn, gid, "lost", reason=row["lost_reason"] or "mandate lost")
        return
    _set_stage(conn, gid, "mandate_signed", reason=f"{row['type']} mandate")
    exp = row["expires_at"]
    if not exp and row["signed_at"] and row["duration_days"]:
        try:
            exp = (datetime.fromisoformat(row["signed_at"])
                   + timedelta(days=int(row["duration_days"]))).date().isoformat()
            conn.execute("UPDATE mandates SET expires_at=? WHERE id=?", (exp, row["id"]))
            row["expires_at"] = exp
        except ValueError:
            pass
    if exp:
        try:
            remind = (datetime.fromisoformat(exp) - timedelta(days=14)).date().isoformat()
            conn.execute(
                "INSERT INTO tasks(group_id, title, kind, due_at) VALUES (?,?,?,?)",
                (gid, f"Mandate ({row['type']}) expires {exp} — renew", "mandate_renewal", remind))
        except ValueError:
            pass


def _after_note(conn, gid, row, data):
    _log(conn, gid, "note", {"id": row["id"], "body": (row["body"] or "")[:200]})


_child_routes("contacts",
              ("role", "name", "phone", "email", "id_number", "company", "provider",
               "consent_basis", "notes"),
              {"role": CONTACT_ROLES}, _after_contact, order="id")
_child_routes("interactions",
              ("contact_id", "channel", "direction", "outcome", "summary", "occurred_at",
               "next_follow_up_at", "actor"),
              {"channel": CHANNELS, "outcome": OUTCOMES, "direction": ["outbound", "inbound"]},
              _after_interaction, order="occurred_at DESC, id DESC")
_child_routes("mandates",
              ("type", "signed_at", "expires_at", "duration_days", "listing_price",
               "commission_pct", "competing_agencies", "lost_reason", "lost_to", "notes",
               "document_path"),
              {"type": MANDATE_TYPES, "lost_reason": LOST_REASONS}, _after_mandate)
_child_routes("notes", ("body", "pinned"), {}, _after_note, order="pinned DESC, id DESC")
_child_routes("tasks", ("title", "kind", "due_at", "done_at"), {"kind": TASK_KINDS},
              order="done_at IS NOT NULL, due_at")


# ------------------------------------------------------------------- tasks

@bp.get("/api/tasks")
def api_tasks():
    due = request.args.get("due")  # today | overdue | open | all
    today = datetime.now().date().isoformat()
    where, params = "1=1", []
    if due == "today":
        where = "done_at IS NULL AND date(due_at) <= ?"
        params = [today]
    elif due == "overdue":
        where = "done_at IS NULL AND date(due_at) < ?"
        params = [today]
    elif due in (None, "open"):
        where = "done_at IS NULL"
    with db.connect() as conn:
        ensure_schema(conn)
        tasks = _rows(conn.execute(
            f"SELECT * FROM tasks WHERE {where} ORDER BY due_at IS NULL, due_at LIMIT 500", params))
        gids = sorted({t["group_id"] for t in tasks if t["group_id"]})
        summ = _summaries(conn) if gids else {}
        for t in tasks:
            s = summ.get(t["group_id"]) or {}
            t["property"] = {k: s.get(k) for k in ("title", "suburb", "street_address_raw", "price_zar")}
        return jsonify(tasks)


# ------------------------------------------------------------------- stats

@bp.get("/api/panel/stats")
def api_stats():
    today = datetime.now().date().isoformat()
    with db.connect() as conn:
        ensure_schema(conn)
        by_stage = {r["stage"]: r["n"] for r in _rows(conn.execute(
            "SELECT stage, COUNT(*) n FROM tracked_property WHERE archived_at IS NULL GROUP BY stage"))}
        mandates = {r["type"]: r["n"] for r in _rows(conn.execute(
            "SELECT type, COUNT(*) n FROM mandates GROUP BY type"))}
        one = lambda q, p=(): conn.execute(q, p).fetchone()[0]
        return jsonify({
            "tracked": sum(by_stage.values()),
            "by_stage": {s: by_stage.get(s, 0) for s in STAGES},
            "mandates": mandates,
            "overdue_tasks": one("SELECT COUNT(*) FROM tasks WHERE done_at IS NULL AND date(due_at) < ?", (today,)),
            "due_today": one("SELECT COUNT(*) FROM tasks WHERE done_at IS NULL AND date(due_at) = ?", (today,)),
            "interactions_7d": one("SELECT COUNT(*) FROM interactions WHERE occurred_at >= datetime('now','-7 days')"),
            "expiring_mandates_30d": one(
                "SELECT COUNT(*) FROM mandates WHERE type != 'none_lost' AND expires_at IS NOT NULL "
                "AND date(expires_at) BETWEEN ? AND date(?, '+30 days')", (today, today)),
        })


# ------------------------------------------------------------------- today
#
# The lead-management home screen: everything that needs a human today, in
# priority order, each row carrying enough to act on it (call / WhatsApp /
# log / snooze) without opening the property.

STALE_DAYS = 10          # active lead with no contact attempt this long = stale
ACTIVE_STAGES = ("contact_found", "contacted", "meeting", "valuation_sent")


@bp.get("/api/panel/today")
def api_today():
    today = datetime.now().date().isoformat()
    with db.connect() as conn:
        ensure_schema(conn)
        tracked = _rows(conn.execute(
            "SELECT * FROM tracked_property WHERE archived_at IS NULL"))
        enriched = {t["group_id"]: t for t in _enrich(conn, tracked)}

        def prop(gid):
            e = enriched.get(gid) or {}
            return {k: e.get(k) for k in (
                "group_id", "listing_key", "title", "suburb", "street_address_raw", "official_address",
                "price_zar", "stage", "priority", "tier", "contact_id", "contact_name",
                "contact_phone", "contact_email", "last_contact_at", "last_outcome",
                "last_channel", "attempts", "mandate_type", "mandate_expires_at", "photo_url")}

        tasks = _rows(conn.execute(
            "SELECT * FROM tasks WHERE done_at IS NULL AND due_at IS NOT NULL "
            "AND date(due_at) <= date(?, '+7 days') ORDER BY due_at", (today,)))
        overdue, due_today, upcoming = [], [], []
        for t in tasks:
            t["property"] = prop(t["group_id"])
            d = t["due_at"][:10]
            (overdue if d < today else due_today if d == today else upcoming).append(t)

        expiring = _rows(conn.execute(
            "SELECT m.* FROM mandates m JOIN (SELECT group_id, MAX(id) id FROM mandates GROUP BY group_id) x "
            "ON x.id = m.id WHERE m.type != 'none_lost' AND m.expires_at IS NOT NULL "
            "AND date(m.expires_at) BETWEEN ? AND date(?, '+45 days') ORDER BY m.expires_at", (today, today)))
        for m in expiring:
            m["property"] = prop(m["group_id"])

        stale = []
        for e in enriched.values():
            if e["stage"] not in ACTIVE_STAGES:
                continue
            last = e.get("last_contact_at")
            ref = last or e.get("tracked_at") or ""
            try:
                days = (datetime.now() - datetime.fromisoformat(ref.replace(" ", "T"))).days
            except ValueError:
                days = None
            if days is not None and days >= STALE_DAYS and not e.get("open_tasks"):
                stale.append({**prop(e["group_id"]), "days_quiet": days})
        stale.sort(key=lambda s: -s["days_quiet"])

        # Has a name/number but nobody has tried yet: the cheapest win there is.
        ready = [prop(e["group_id"]) for e in enriched.values()
                 if e["stage"] in ("contact_found", "new", "researching")
                 and (e.get("contact_phone") or e.get("contact_name"))
                 and not e.get("attempts") and not e.get("open_tasks")]
        ready.sort(key=lambda p: (p["tier"] != "hot", -(p["price_zar"] or 0)))

        fresh = _rows(conn.execute("""
            SELECT tp.group_id, a.occurred_at, a.kind FROM tracked_property tp
            JOIN activities a ON a.group_id = tp.group_id
            WHERE tp.archived_at IS NULL AND a.kind IN ('price_cut','delisted','relisted')
              AND a.occurred_at >= datetime('now','-7 days') ORDER BY a.occurred_at DESC LIMIT 20"""))
        for f in fresh:
            f["property"] = prop(f["group_id"])

        # Hot, open-mandate prospects not yet tracked — the engine's best
        # handful, so the panel pulls you back into prospecting too.
        hot = _rows(conn.execute("""
            SELECT COALESCE(CAST(g.group_id AS TEXT), 'solo-' || l.listing_key) AS group_id,
                   l.listing_key, l.title, l.suburb, l.street_address_raw, l.price_zar,
                   l.photo_url, s.prospect_score, s.tier, s.mandate_verdict, s.pitch_angle
            FROM scores s JOIN listings l ON l.listing_key = s.listing_key
            LEFT JOIN property_groups g ON g.listing_key = l.listing_key
            WHERE s.tier = 'hot' AND s.sellable = 1
              AND s.mandate_verdict IN ('open','probably_open')
              AND COALESCE(CAST(g.group_id AS TEXT), 'solo-' || l.listing_key)
                  NOT IN (SELECT group_id FROM tracked_property)
            ORDER BY s.prospect_score DESC LIMIT 40"""))
        seen, hot_u = set(), []
        for h in hot:
            if h["group_id"] in seen:
                continue
            seen.add(h["group_id"]); hot_u.append(h)
            if len(hot_u) == 6:
                break

        wins = _rows(conn.execute(
            "SELECT m.*, m.group_id AS gid FROM mandates m WHERE m.type != 'none_lost' "
            "AND m.created_at >= datetime('now','-30 days') ORDER BY m.id DESC LIMIT 5"))
        for w in wins:
            w["property"] = prop(w["group_id"])

        return jsonify({
            "date": today,
            "overdue": overdue, "due_today": due_today, "upcoming": upcoming[:15],
            "expiring": expiring, "stale": stale[:15], "ready": ready[:20], "engine_events": fresh,
            "hot_untracked": hot_u, "recent_wins": wins,
            "counts": {"tracked": len(tracked),
                       "active": sum(1 for e in enriched.values() if e["stage"] in ACTIVE_STAGES),
                       "interactions_7d": conn.execute(
                           "SELECT COUNT(*) FROM interactions WHERE occurred_at >= datetime('now','-7 days')").fetchone()[0]},
        })


@bp.post("/api/tasks/<int:tid>/snooze")
def api_snooze(tid):
    days = int((_body().get("days") or 1))
    with db.connect() as conn:
        ensure_schema(conn)
        cur = conn.execute(
            "UPDATE tasks SET due_at = date('now', ?) WHERE id=? AND done_at IS NULL",
            (f"+{days} days", tid))
        if cur.rowcount == 0:
            return _bad("not found", 404)
        return jsonify(_one(conn.execute("SELECT * FROM tasks WHERE id=?", (tid,))))


@bp.post("/api/tasks/<int:tid>/done")
def api_task_done(tid):
    with db.connect() as conn:
        ensure_schema(conn)
        done = _body().get("done", True)
        conn.execute("UPDATE tasks SET done_at=? WHERE id=?",
                     (datetime.now().isoformat(sep=" ", timespec="seconds") if done else None, tid))
        return jsonify(_one(conn.execute("SELECT * FROM tasks WHERE id=?", (tid,))))


# ---------------------------------------------------------------- contacts
#
# People, not rows. The contacts table is per property; the same owner can
# legitimately appear on several (a trust with three flats). The directory
# and person page merge on normalised phone / email / name so you see one
# human with all their properties and every conversation.

def _norm_phone(p):
    d = "".join(ch for ch in str(p or "") if ch.isdigit())
    if d.startswith("27") and len(d) == 11:
        d = "0" + d[2:]
    return d or None


def _person_key(c) -> str:
    return (_norm_phone(c["phone"]) and "p:" + _norm_phone(c["phone"])) \
        or (c["email"] and "e:" + c["email"].strip().lower()) \
        or ("n:" + " ".join((c["name"] or "").lower().split())) \
        or f"id:{c['id']}"


def _people(conn) -> dict[str, dict]:
    """person_key -> merged person with member contact ids and group ids."""
    people: dict[str, dict] = {}
    for c in _rows(conn.execute("SELECT * FROM contacts ORDER BY id")):
        k = _person_key(c)
        p = people.setdefault(k, {"key": k, "id": c["id"], "name": c["name"], "phone": c["phone"],
                                  "email": c["email"], "role": c["role"], "company": c["company"],
                                  "providers": set(), "contact_ids": [], "group_ids": [],
                                  "first_seen": c["created_at"]})
        p["name"] = p["name"] or c["name"]; p["phone"] = p["phone"] or c["phone"]
        p["email"] = p["email"] or c["email"]; p["company"] = p["company"] or c["company"]
        p["providers"].add(c["provider"]); p["contact_ids"].append(c["id"])
        if c["group_id"] not in p["group_ids"]:
            p["group_ids"].append(c["group_id"])
    for p in people.values():
        p["providers"] = sorted(p["providers"])
    return people


@bp.get("/api/contacts")
def api_contacts():
    q = (request.args.get("q") or "").strip().lower()
    with db.connect() as conn:
        ensure_schema(conn)
        people = _people(conn)
        summ = _summaries(conn)
        tracked = {t["group_id"]: t for t in _rows(conn.execute("SELECT * FROM tracked_property"))}
        last = {}
        for r in _rows(conn.execute(
                "SELECT contact_id, group_id, MAX(occurred_at) t, COUNT(*) n, "
                "SUM(outcome='spoke') spoke FROM interactions GROUP BY contact_id, group_id")):
            last[(r["contact_id"], r["group_id"])] = r
        out = []
        for p in people.values():
            ints = [last[k] for k in last if k[0] in p["contact_ids"] or (k[0] is None and k[1] in p["group_ids"])]
            p["attempts"] = sum(i["n"] for i in ints)
            p["spoke"] = sum(i["spoke"] or 0 for i in ints)
            p["last_contact_at"] = max((i["t"] for i in ints), default=None)
            p["properties"] = [{"group_id": g, "address": (summ.get(g) or {}).get("street_address_raw")
                                or (summ.get(g) or {}).get("title"), "suburb": (summ.get(g) or {}).get("suburb"),
                                "price_zar": (summ.get(g) or {}).get("price_zar"),
                                "stage": (tracked.get(g) or {}).get("stage")} for g in p["group_ids"]]
            p["mandates"] = conn.execute(
                f"SELECT COUNT(*) FROM mandates WHERE type != 'none_lost' AND group_id IN "
                f"({','.join('?' * len(p['group_ids']))})", p["group_ids"]).fetchone()[0]
            if q and not any(q in str(v or "").lower() for v in
                             (p["name"], p["phone"], p["email"], p["company"],
                              *(pp["address"] or "" for pp in p["properties"]))):
                continue
            out.append(p)
        out.sort(key=lambda p: (p["last_contact_at"] or "", p["first_seen"] or ""), reverse=True)
        return jsonify(out)


@bp.get("/api/contacts/<int:cid>")
def api_contact(cid):
    with db.connect() as conn:
        ensure_schema(conn)
        c = _one(conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)))
        if not c:
            return _bad("not found", 404)
        person = _people(conn).get(_person_key(c))
        gids = person["group_ids"]
        cids = person["contact_ids"]
        tracked = _rows(conn.execute(
            f"SELECT * FROM tracked_property WHERE group_id IN ({','.join('?' * len(gids))})", gids))
        props = _enrich(conn, tracked)
        qc, qg = ",".join("?" * len(cids)), ",".join("?" * len(gids))
        interactions = _rows(conn.execute(f"""
            SELECT i.*, c.name AS contact_name FROM interactions i
            LEFT JOIN contacts c ON c.id = i.contact_id
            WHERE i.contact_id IN ({qc}) OR (i.contact_id IS NULL AND i.group_id IN ({qg}))
            ORDER BY i.occurred_at DESC, i.id DESC LIMIT 300""", cids + gids))
        mandates = _rows(conn.execute(
            f"SELECT * FROM mandates WHERE group_id IN ({qg}) ORDER BY id DESC", gids))
        records = _rows(conn.execute(
            f"SELECT * FROM contacts WHERE id IN ({qc}) ORDER BY id", cids))
        addr = {p["group_id"]: (p.get("street_address_raw") or p.get("title")) for p in props}
        for i in interactions:
            i["address"] = addr.get(i["group_id"])
        for m in mandates:
            m["address"] = addr.get(m["group_id"])
        return jsonify({**person, "contact": c, "records": records, "properties": props,
                        "interactions": interactions, "mandates": mandates})


@bp.patch("/api/contacts/<int:cid>")
def api_contact_patch(cid):
    data = _body()
    try:
        vals = _pick(data, ("role", "name", "phone", "email", "id_number", "company", "notes"),
                     {"role": CONTACT_ROLES})
    except ValueError as e:
        return _bad(str(e))
    if not vals:
        return _bad("nothing to update")
    with db.connect() as conn:
        ensure_schema(conn)
        cur = conn.execute(f"UPDATE contacts SET {','.join(k + '=?' for k in vals)} WHERE id=?",
                           list(vals.values()) + [cid])
        if cur.rowcount == 0:
            return _bad("not found", 404)
        return jsonify(_one(conn.execute("SELECT * FROM contacts WHERE id=?", (cid,))))
