"""SQLite storage for scraped listings, price history, and prospect scores.

Listings are keyed by `listing_key` ("<source>:<source_id>") because the same
physical property legitimately appears once per portal, and portals reuse each
other's id ranges. Grouping those rows back into one property is dedupe.py's
job.

Rentals share the table, tagged `listing_type = 'rent'` and keyed
"<source>:rent:<source_id>". They are a separate book, not a variant of the
same one: a home advertised for sale AND to rent is two records on purpose
(that pairing is itself a prospecting signal — a seller hedging with a
tenant), so nothing in here ever merges the two.
"""

import sqlite3
from contextlib import contextmanager

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    -- '<source>:<source_id>' for sales, '<source>:rent:<source_id>' for
    -- rentals. The namespace matters: the same physical home advertised both
    -- for sale and to rent is two separate records (deliberately — see
    -- listing_type), and nothing guarantees a portal won't reuse an id
    -- between its two books.
    listing_key     TEXT PRIMARY KEY,
    source          TEXT NOT NULL,      -- 'property24' | 'seeff' | ...
    source_id       TEXT NOT NULL,      -- the portal's own listing reference
    -- 'sale' (the default, and everything crawled before rentals existed) or
    -- 'rent'. Every for-sale view — scoring, reports, CMA comps, the
    -- sold-proxy lifecycle, dedupe — filters on 'sale'; rentals are never
    -- scored and never become comps.
    listing_type    TEXT NOT NULL DEFAULT 'sale',
    url             TEXT NOT NULL,
    suburb_slug     TEXT NOT NULL,
    suburb          TEXT,
    title           TEXT,
    -- Sales: the asking price. Rentals: the rent AS ADVERTISED, for the
    -- period in rent_period — Atlantic Seaboard holiday lets are quoted per
    -- day, so this is NOT always a monthly figure. Use
    -- sources.base.monthly_equivalent() before comparing two rentals.
    price_zar       INTEGER,
    property_type   TEXT,
    bedrooms        REAL,
    bathrooms       REAL,
    garages         REAL,
    parking         REAL,
    floor_size_m2   REAL,
    erf_size_m2     REAL,
    price_per_m2    REAL,
    levies          INTEGER,
    rates           INTEGER,
    pool            TEXT,
    listing_date    TEXT,
    agency          TEXT,
    agent_name      TEXT,
    description     TEXT,
    photo_count     INTEGER,
    photo_url       TEXT,               -- hero image; '-' = page has none
    street_address  TEXT,               -- normalised for matching: '10 woodford ave'
    -- The address exactly as the portal printed it ("18 Casos Road, Calypso
    -- Beach, Langebaan"). street_address above is lowercased, abbreviated and
    -- reduced to the street segment so the same house matches across portals,
    -- which makes it the wrong thing to show a human or to hand to a deeds
    -- search. Both are kept: one to match on, one to read.
    street_address_raw TEXT,
    latitude        REAL,
    longitude       REAL,
    mandate_text    TEXT,               -- regex hint from the description
    -- Hard mandate ground truth where a portal publishes it (Pam Golding):
    -- 'sole' | 'not_sole' | NULL. This is the difference between inferring
    -- exclusivity from prose and simply knowing it.
    mandate_explicit TEXT,
    price_reduced   INTEGER,
    under_offer     INTEGER,
    -- new/off-plan development: a developer launch, not a mandate to win
    is_development  INTEGER,
    -- rentals only: 'month' | 'week' | 'day', the period price_zar is quoted
    -- for. NULL on sales.
    rent_period     TEXT,
    available_from  TEXT,               -- rentals: occupation date as printed
    furnished       TEXT,               -- rentals: 'Yes' | 'No' | as printed
    deposit         INTEGER,            -- rentals: deposit in ZAR where stated
    first_seen      TEXT DEFAULT (datetime('now')),
    last_seen       TEXT DEFAULT (datetime('now')),
    -- bumped only when a score-relevant field actually differs, unlike
    -- last_seen which every sighting refreshes. NULL = unchanged since
    -- insert; readers fall back to first_seen.
    content_changed TEXT,
    raw_overview    TEXT
);

CREATE INDEX IF NOT EXISTS idx_listings_suburb ON listings(suburb_slug);
CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source);
CREATE INDEX IF NOT EXISTS idx_listings_seen   ON listings(last_seen);
-- idx_listings_type is created in connect() rather than here, after the
-- listing_type column has been added: this script also runs against a
-- pre-rentals database, where CREATE TABLE IF NOT EXISTS is a no-op and an
-- index over a column that does not exist yet is a hard error.

-- One row per observed price CHANGE (plus the first sighting), so the table
-- is a chronology. The old schema keyed on (listing_key, price_zar), which
-- made it a SET of distinct prices: R20m -> R18m -> R20m -> R18m looked like
-- a single cut, and re-cuts to a previous price vanished entirely.
CREATE TABLE IF NOT EXISTS price_history (
    listing_key     TEXT,
    price_zar       INTEGER,
    observed_at     TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (listing_key, observed_at)
);

CREATE TABLE IF NOT EXISTS property_groups (
    group_id        INTEGER,
    listing_key     TEXT PRIMARY KEY,
    agency_count    INTEGER,   -- distinct agencies marketing this property
    source_count    INTEGER,   -- distinct portals carrying it
    match_evidence  TEXT       -- why these listings were merged
);

CREATE INDEX IF NOT EXISTS idx_groups_gid ON property_groups(group_id);

-- Oblivion's manual prospecting tracker (imported from OBLVN.PROSPECTING.xlsx).
-- prospected=1 means the team already worked this property; the engine must
-- not surface it again. Keyed by Property24 listing number (what the sheet
-- holds); joined to listings via source='property24'.
CREATE TABLE IF NOT EXISTS tracker (
    listing_number  TEXT PRIMARY KEY,
    url             TEXT,
    title           TEXT,
    suburb_slug     TEXT,
    prospected      INTEGER DEFAULT 0,
    sheet           TEXT,
    imported_at     TEXT DEFAULT (datetime('now'))
);

-- Public-cadastre resolution: which land parcel (erf) each listing is, i.e.
-- the search key for the licensed deeds tool (CMA/Lightstone). One row per
-- listing; every listing in a property group carries the same resolution.
-- status: ok | check | confirmed | candidates | no_match | no_coverage | no_data
CREATE TABLE IF NOT EXISTS erf_lookup (
    listing_key      TEXT PRIMARY KEY,
    group_id         TEXT,
    status           TEXT,
    method           TEXT,   -- address | point | size | ai_confirmed
    erf_number       TEXT,
    portion          TEXT,
    sg26_code        TEXT,   -- 26-char Surveyor-General code
    official_address TEXT,   -- as the City of Cape Town records it
    official_suburb  TEXT,
    parcel_area_m2   REAL,
    latitude         REAL,   -- parcel centroid
    longitude        REAL,
    note             TEXT,
    candidates       TEXT,   -- JSON candidate parcels when unresolved
    ai_status        TEXT,   -- running | done | error
    ai_best          TEXT,   -- JSON verdict from the vision model
    ai_at            TEXT,
    looked_up_at     TEXT DEFAULT (datetime('now'))
);

-- Team chat: the agents talking to each OTHER, not to Agent Z. One row per
-- message, oldest first by id, which is also the client's polling cursor
-- ("everything after 417").
--
-- There are no accounts on this dashboard — one shared password for the whole
-- team — so `sender` is simply the display name the person typed into the
-- widget and their browser remembers. It is a courtesy label, not an identity
-- claim, and nothing anywhere trusts it.
CREATE TABLE IF NOT EXISTS team_chat (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sender     TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL       -- ISO-8601 UTC: '2026-09-22T09:14:07Z'
);

CREATE TABLE IF NOT EXISTS scores (
    listing_key             TEXT PRIMARY KEY,
    scored_by               TEXT,   -- 'ai:<model>' or 'heuristic'
    mandate_verdict         TEXT,   -- open|probably_open|unknown|probably_sole|sole
    sellable                INTEGER,-- 1 = Oblivion can pitch for this mandate
    prospect_score          INTEGER,
    luxury_fit              INTEGER,
    open_mandate_confidence INTEGER,
    marketing_weakness      INTEGER,
    tier                    TEXT,   -- 'hot' | 'warm' | 'cold'
    reasoning               TEXT,
    pitch_angle             TEXT,
    red_flags               TEXT,
    mandate_expiry_note     TEXT,   -- when a sole mandate likely comes up
    scored_at               TEXT DEFAULT (datetime('now'))
);
"""

INSERT_COLUMNS = (
    "listing_key", "source", "source_id", "listing_type", "url",
    "suburb_slug", "suburb",
    "title", "price_zar", "property_type", "bedrooms", "bathrooms", "garages",
    "parking", "floor_size_m2", "erf_size_m2", "price_per_m2", "levies",
    "rates", "pool", "listing_date", "agency", "agent_name", "description",
    "photo_count", "photo_url", "street_address", "street_address_raw",
    "latitude", "longitude",
    "mandate_text", "mandate_explicit", "price_reduced", "under_offer",
    "is_development", "rent_period", "available_from", "furnished", "deposit",
    "raw_overview",
)

# Columns refreshed every time a listing is seen again.
_UPDATE_COLUMNS = (
    "url", "title", "price_zar", "property_type", "bedrooms", "bathrooms",
    "garages", "parking", "floor_size_m2", "erf_size_m2", "price_per_m2",
    "levies", "rates", "pool", "listing_date", "agency", "agent_name",
    "description", "photo_count", "photo_url", "street_address",
    "street_address_raw", "latitude",
    "longitude", "mandate_text", "mandate_explicit", "price_reduced",
    "under_offer", "is_development", "rent_period", "available_from",
    "furnished", "deposit", "raw_overview",
)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return set()


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring a pre-multi-source database up to the current schema.

    The original schema keyed listings by Property24's `listing_number`. Those
    rows are preserved and re-keyed as `property24:<listing_number>`.
    """
    cols = _columns(conn, "listings")
    if not cols or "source" in cols:
        return  # fresh database, or already migrated

    conn.execute("ALTER TABLE listings RENAME TO listings_v1")
    conn.execute("ALTER TABLE property_groups RENAME TO property_groups_v1")
    conn.execute("ALTER TABLE scores RENAME TO scores_v1")
    try:
        conn.execute("ALTER TABLE price_history RENAME TO price_history_v1")
    except sqlite3.OperationalError:
        pass
    conn.executescript(SCHEMA)

    old = _columns(conn, "listings_v1")
    carried = [c for c in INSERT_COLUMNS
               if c in old and c not in ("listing_key", "source", "source_id")]
    conn.execute(f"""
        INSERT INTO listings (listing_key, source, source_id, first_seen,
                              last_seen, {', '.join(carried)})
        SELECT 'property24:' || listing_number, 'property24', listing_number,
               first_seen, last_seen, {', '.join(carried)}
        FROM listings_v1
    """)
    if "price_history_v1" in {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}:
        conn.execute("""
            INSERT OR IGNORE INTO price_history (listing_key, price_zar, observed_at)
            SELECT 'property24:' || listing_number, price_zar, observed_at
            FROM price_history_v1
        """)
    old_scores = _columns(conn, "scores_v1")
    score_cols = [c for c in ("scored_by", "mandate_verdict", "prospect_score",
                              "luxury_fit", "open_mandate_confidence",
                              "marketing_weakness", "tier", "reasoning",
                              "pitch_angle", "red_flags", "scored_at")
                  if c in old_scores]
    conn.execute(f"""
        INSERT OR IGNORE INTO scores (listing_key, {', '.join(score_cols)})
        SELECT 'property24:' || listing_number, {', '.join(score_cols)}
        FROM scores_v1
    """)
    for t in ("listings_v1", "property_groups_v1", "scores_v1", "price_history_v1"):
        conn.execute(f"DROP TABLE IF EXISTS {t}")


def _migrate_price_history(conn: sqlite3.Connection) -> None:
    """Re-key price_history from a set of prices to a chronology.

    The old PRIMARY KEY (listing_key, price_zar) silently dropped any price
    that returned to a previously-seen value. Existing rows are carried over
    unchanged (they were genuine observations); only the key changes, so
    from here on every price CHANGE records a row.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table'"
        " AND name='price_history'").fetchone()
    if not row or "PRIMARY KEY (listing_key, observed_at)" in (row[0] or ""):
        return  # fresh schema, or already migrated
    conn.execute("ALTER TABLE price_history RENAME TO price_history_setpk")
    conn.execute("""
        CREATE TABLE price_history (
            listing_key TEXT,
            price_zar   INTEGER,
            observed_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (listing_key, observed_at)
        )""")
    conn.execute("""
        INSERT OR IGNORE INTO price_history (listing_key, price_zar, observed_at)
        SELECT listing_key, price_zar, observed_at FROM price_history_setpk
        ORDER BY observed_at ASC""")
    conn.execute("DROP TABLE price_history_setpk")


@contextmanager
def connect(db_path: str = config.DB_PATH):
    # check_same_thread=False: pipeline.py crawls the portals on one thread per
    # source and funnels every read and write through a single lock, so the
    # connection is shared but never used concurrently.
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    _migrate(conn)
    _migrate_price_history(conn)
    conn.executescript(SCHEMA)
    # forward-compatible column adds
    listing_cols = _columns(conn, "listings")
    for col, decl in (("is_development", "INTEGER"), ("photo_url", "TEXT"),
                      ("street_address_raw", "TEXT"),
                      # rentals (see SCHEMA). listing_type carries a DEFAULT so
                      # every pre-rentals row becomes 'sale' the moment the
                      # column appears — a NULL here would fall out of every
                      # `listing_type = 'sale'` filter and silently empty the
                      # dashboard, the report and the CMA comps feed.
                      ("listing_type", "TEXT NOT NULL DEFAULT 'sale'"),
                      ("rent_period", "TEXT"),
                      ("available_from", "TEXT"),
                      ("furnished", "TEXT"),
                      ("deposit", "INTEGER")):
        if col not in listing_cols:
            try:
                conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass
    # Belt and braces: an older ALTER (or a hand-written row) can leave a NULL
    # behind, and NULL is not 'sale' to a WHERE clause.
    try:
        conn.execute("UPDATE listings SET listing_type = 'sale'"
                     " WHERE listing_type IS NULL OR listing_type = ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_type"
                     " ON listings(listing_type)")
    except sqlite3.OperationalError:
        pass
    if "content_changed" not in listing_cols:
        try:
            conn.execute(
                "ALTER TABLE listings ADD COLUMN content_changed TEXT")
            # Backfill with first_seen, not last_seen: last_seen is fresh on
            # every live listing, which would mark the whole database stale
            # and trigger one giant paid re-score for no new information.
            conn.execute("UPDATE listings SET content_changed = first_seen")
        except sqlite3.OperationalError:
            pass
    existing = _columns(conn, "scores")
    for col, decl in (("sellable", "INTEGER"),
                      ("mandate_expiry_note", "TEXT"),
                      ("mandate_verdict", "TEXT")):
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE scores ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# The fields whose change makes a listing worth re-judging. A sweep that
# merely sees the listing again (last_seen) is not a reason to spend a
# paid scoring call on it.
_CONTENT_COLUMNS = (
    "price_zar", "title", "description", "mandate_text", "mandate_explicit",
    "price_reduced", "under_offer", "agency", "listing_date",
)


def upsert_listing(conn: sqlite3.Connection, listing: dict) -> None:
    row = {c: listing.get(c) for c in INSERT_COLUMNS}
    placeholders = ", ".join(f":{c}" for c in INSERT_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in _UPDATE_COLUMNS)
    changed = " OR ".join(f"{c} IS NOT excluded.{c}"
                          for c in _CONTENT_COLUMNS)
    conn.execute(
        f"""INSERT INTO listings ({', '.join(INSERT_COLUMNS)})
            VALUES ({placeholders})
            ON CONFLICT(listing_key) DO UPDATE SET
                {updates},
                content_changed = CASE WHEN {changed}
                                       THEN datetime('now')
                                       ELSE content_changed END,
                last_seen = datetime('now')""",
        row,
    )
    if row.get("price_zar"):
        # Record first sighting and every CHANGE — including a return to an
        # earlier price, which the old set-keyed table swallowed. OR IGNORE
        # tolerates two observations of the same listing in one second
        # (e.g. a re-eval racing a crawl).
        last = conn.execute(
            "SELECT price_zar FROM price_history WHERE listing_key = ?"
            " ORDER BY observed_at DESC, rowid DESC LIMIT 1",
            (row["listing_key"],)).fetchone()
        if last is None or last[0] != row["price_zar"]:
            conn.execute(
                "INSERT OR IGNORE INTO price_history (listing_key, price_zar)"
                " VALUES (?, ?)",
                (row["listing_key"], row["price_zar"]),
            )


def recently_seen(conn: sqlite3.Connection, source: str, hours: int = 20,
                  listing_type: str = "sale") -> set[str]:
    """source_ids for this portal scraped within the window (skip re-fetching).

    Scoped to one book: a portal's sale and rent ids live in the same column,
    and a shared set would let a recently-crawled sale listing suppress the
    rental crawl of the same id (Property24 numbers them from one sequence, so
    a collision is not hypothetical).
    """
    return {
        r["source_id"] for r in conn.execute(
            "SELECT source_id FROM listings WHERE source = ?"
            " AND listing_type = ? AND last_seen > datetime('now', ?)",
            (source, listing_type, f"-{hours} hours"),
        )
    }
