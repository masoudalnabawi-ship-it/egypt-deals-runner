CREATE TABLE IF NOT EXISTS deals (
    deal_key TEXT PRIMARY KEY,
    store TEXT NOT NULL,
    external_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    image_url TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'unknown',
    source TEXT NOT NULL DEFAULT '',
    current_price REAL NOT NULL,
    old_price REAL,
    effective_price REAL,
    visible_discount REAL NOT NULL DEFAULT 0,
    real_discount REAL NOT NULL DEFAULT 0,
    lane TEXT NOT NULL DEFAULT 'normal',
    score REAL NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'pending',
    discovered_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    verified_at INTEGER,
    sent_at INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_until INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_deals_state_lane_due
ON deals(state, lane, next_attempt_at, score DESC, discovered_at ASC);
CREATE INDEX IF NOT EXISTS idx_deals_store_updated
ON deals(store, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_deals_category_updated
ON deals(category, updated_at DESC);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_key TEXT NOT NULL,
    store TEXT NOT NULL,
    price REAL NOT NULL,
    old_price REAL,
    observed_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_history_key_time
ON price_history(deal_key, observed_at DESC);

CREATE TABLE IF NOT EXISTS source_health (
    store TEXT NOT NULL,
    source TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'unknown',
    scans INTEGER NOT NULL DEFAULT 0,
    fetched INTEGER NOT NULL DEFAULT 0,
    candidates INTEGER NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0,
    sent INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    consecutive_errors INTEGER NOT NULL DEFAULT 0,
    last_attempt_at INTEGER NOT NULL DEFAULT 0,
    last_success_at INTEGER NOT NULL DEFAULT 0,
    last_latency_ms INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(store, source)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    event TEXT NOT NULL,
    store TEXT NOT NULL DEFAULT '',
    deal_key TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_deal_event ON events(deal_key, event);
