"""Registered-owner contact details per property group — self-sourced.

erf.py resolves each listing to its land parcel (erf number / SG26 code,
stored in `erf_lookup` and shared across a property group via the TEXT
`group_id` column). The one datum the public cadastre does NOT carry is the
registered owner's name and contact details — that lives in the SA Deeds
Registry. This engine deliberately depends on no commercial deeds platform
(LOOM, Lightstone, WinDeed, SearchWorks): owner details are looked up by a
human against primary/public sources and captured here via set_manual().

Primary sources worth knowing:
  * DeedsWeb (deeds.gov.za) — the Deeds Office's own online search; official
    searches at state-regulated fees, no reseller mark-up.
  * The erf number + official address in `erf_lookup` is the search key; the
    CoCT GV roll (valuations.py) confirms you have the right rating unit.

POPIA note
----------
Deeds Registry records are public record in South Africa, and processing a
registered owner's name to pitch them directly for a sale mandate rests on
the legitimate-interest ground (POPIA s11(1)(f)) — but that ground demands
restraint:

  * store the minimum needed to make contact (name, one phone, one email);
  * use it only for the mandate pitch it was collected for;
  * honour objections immediately — delete() exists so a person's data can
    be purged the moment they ask (or the pitch is dead);
  * never bulk-export this table or ship it to a third party.
"""

from __future__ import annotations

import json
import sqlite3

# ------------------------------------------------------------------ storage

DDL = """
CREATE TABLE IF NOT EXISTS owner_details (
    group_id       TEXT PRIMARY KEY,   -- erf_lookup.group_id
    owner_name     TEXT,
    phone          TEXT,
    email          TEXT,
    deed_number    TEXT,               -- e.g. 'T 12345/2019'
    purchase_price INTEGER,            -- ZAR, last transfer
    purchase_date  TEXT,
    bond_holder    TEXT,               -- bank holding the mortgage bond
    provider       TEXT,               -- always 'manual' (self-sourced)
    raw            TEXT,               -- JSON: whatever the source showed
    notes          TEXT,               -- e.g. which source, search date
    updated_at     TEXT DEFAULT (datetime('now'))
);
"""

# Caller-settable columns, i.e. everything except group_id/provider/updated_at.
FIELDS = ("owner_name", "phone", "email", "deed_number", "purchase_price",
          "purchase_date", "bond_holder", "raw", "notes")


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)


def _row_to_dict(cursor, row) -> dict | None:
    if row is None:
        return None
    return {d[0]: row[i] for i, d in enumerate(cursor.description)}


def get(conn: sqlite3.Connection, group_id: str) -> dict | None:
    """The stored owner row for a property group, or None."""
    cur = conn.execute(
        "SELECT * FROM owner_details WHERE group_id = ?", (str(group_id),))
    return _row_to_dict(cur, cur.fetchone())


def for_groups(conn: sqlite3.Connection) -> dict[str, dict]:
    """All owner rows keyed by group_id — one query for a dashboard render."""
    cur = conn.execute("SELECT * FROM owner_details")
    cols = [d[0] for d in cur.description]
    return {row[0]: dict(zip(cols, row)) for row in cur.fetchall()}


def set_manual(conn: sqlite3.Connection, group_id: str, **fields) -> dict:
    """Upsert manually-entered owner details for a group.

    Partial updates: only the fields passed are written; anything already
    stored and not mentioned is left alone. `raw` may be a dict/list (it is
    JSON-encoded) or a pre-encoded string. Returns the full stored row.
    """
    unknown = set(fields) - set(FIELDS)
    if unknown:
        raise ValueError(
            f"unknown owner field(s) {sorted(unknown)}; allowed: {FIELDS}")
    if "raw" in fields and not isinstance(fields["raw"], (str, type(None))):
        fields["raw"] = json.dumps(fields["raw"], ensure_ascii=False)
    if fields.get("purchase_price") is not None:
        fields["purchase_price"] = int(fields["purchase_price"])

    group_id = str(group_id)
    cols = list(fields)
    conn.execute(
        f"""INSERT INTO owner_details (group_id, provider
                {''.join(', ' + c for c in cols)})
            VALUES (?, 'manual'{', ?' * len(cols)})
            ON CONFLICT(group_id) DO UPDATE SET
                provider = 'manual',
                updated_at = datetime('now')
                {''.join(f", {c} = excluded.{c}" for c in cols)}""",
        [group_id] + [fields[c] for c in cols],
    )
    conn.commit()
    row = get(conn, group_id)
    assert row is not None  # the upsert above guarantees the row exists
    return row


def delete(conn: sqlite3.Connection, group_id: str) -> bool:
    """Purge a person's stored details (POPIA objection / dead pitch)."""
    cur = conn.execute(
        "DELETE FROM owner_details WHERE group_id = ?", (str(group_id),))
    conn.commit()
    return cur.rowcount > 0


# -------------------------------------------------------------- smoke test

if __name__ == "__main__":
    import db

    with db.connect() as conn:
        ensure_table(conn)

        gid = None
        row = conn.execute(
            "SELECT group_id FROM erf_lookup WHERE group_id IS NOT NULL "
            "LIMIT 1").fetchone()
        if row:
            gid = str(row[0])
        assert gid, "no group_id in erf_lookup to test against"
        had_real_row = get(conn, gid) is not None
        assert not had_real_row, (
            f"group {gid} already has owner details; not smoke-testing "
            "over real data")
        print(f"smoke-testing on group_id={gid!r}")

        stored = set_manual(
            conn, gid,
            owner_name="Test Owner", phone="+27 82 000 0000",
            purchase_price="12500000",
            raw={"source": "smoke-test"},
        )
        assert stored["owner_name"] == "Test Owner"
        assert stored["provider"] == "manual"
        assert stored["purchase_price"] == 12500000
        assert json.loads(stored["raw"]) == {"source": "smoke-test"}
        assert get(conn, gid) == stored
        assert gid in for_groups(conn)

        # partial update must not clobber unmentioned fields
        updated = set_manual(conn, gid, email="owner@example.com",
                             notes="DeedsWeb search 2026-08-04")
        assert updated["owner_name"] == "Test Owner"
        assert updated["phone"] == "+27 82 000 0000"
        assert updated["email"] == "owner@example.com"
        print("upsert + partial update OK")

        assert delete(conn, gid) is True
        assert get(conn, gid) is None
        assert delete(conn, gid) is False
        print("delete OK - DB left clean")
