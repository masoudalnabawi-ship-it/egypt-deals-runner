CREATE TABLE IF NOT EXISTS price_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asin TEXT NOT NULL,
    price TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(asin, observed_at, source)
);

CREATE INDEX IF NOT EXISTS idx_v15_price_history
ON price_observations(asin, observed_at);

CREATE TABLE IF NOT EXISTS delivery_state (
    asin TEXT NOT NULL,
    lane TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK(status IN (
            'pending',
            'claimed',
            'sending',
            'sent',
            'delivery_unknown'
        )),
    updated_at TEXT NOT NULL,
    telegram_message_id TEXT,
    PRIMARY KEY (asin, lane)
);

CREATE TABLE IF NOT EXISTS competitor_signals (
    asin TEXT NOT NULL,
    source TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    sightings INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (asin, source)
);
