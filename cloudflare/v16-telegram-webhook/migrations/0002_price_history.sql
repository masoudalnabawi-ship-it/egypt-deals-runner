-- V16 only: persistent observed product prices.
CREATE TABLE IF NOT EXISTS v16_price_history (
    asin TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK(price_cents > 0),
    observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (asin, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_v16_price_history_lookup
ON v16_price_history (asin, observed_at);
