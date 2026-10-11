CREATE TABLE IF NOT EXISTS product_monitoring (
    asin TEXT PRIMARY KEY,
    priority TEXT NOT NULL DEFAULT 'STABLE'
        CHECK(priority IN ('HOT', 'ACTIVE', 'STABLE', 'LOW')),
    last_checked_at TEXT,
    next_check_at TEXT NOT NULL,
    consecutive_errors INTEGER NOT NULL DEFAULT 0
        CHECK(consecutive_errors >= 0),
    lease_owner TEXT,
    lease_until TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_v15_monitoring_due
ON product_monitoring(next_check_at, priority);

CREATE INDEX IF NOT EXISTS idx_v15_monitoring_lease
ON product_monitoring(lease_until);
