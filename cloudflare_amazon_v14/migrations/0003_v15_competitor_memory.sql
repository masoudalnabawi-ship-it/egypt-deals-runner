-- V15 Amazon competitor memory.
-- Additive migration: existing V14 and Noon tables remain unchanged.

CREATE TABLE IF NOT EXISTS v15_amazon_candidates (
    asin TEXT PRIMARY KEY,
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    last_verified_at INTEGER,
    verification_status TEXT NOT NULL DEFAULT 'pending',
    CHECK (verification_status IN (
        'pending', 'verified', 'rejected', 'unavailable'
    ))
);

CREATE TABLE IF NOT EXISTS v15_amazon_signals (
    asin TEXT NOT NULL,
    source TEXT NOT NULL,
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    sightings INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (asin, source),
    FOREIGN KEY (asin)
        REFERENCES v15_amazon_candidates(asin)
);

CREATE INDEX IF NOT EXISTS idx_v15_candidates_pending
ON v15_amazon_candidates(
    verification_status, last_seen_at
);
