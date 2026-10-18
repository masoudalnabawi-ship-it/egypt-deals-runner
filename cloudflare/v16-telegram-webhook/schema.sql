CREATE TABLE IF NOT EXISTS v16_reviews (
 message_id INTEGER PRIMARY KEY,
 asin TEXT NOT NULL,
 chat_id TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending',
 prompt_id INTEGER,
 custom_text TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS v16_review_prompt ON v16_reviews(prompt_id) WHERE prompt_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS v16_updates (update_id INTEGER PRIMARY KEY);

-- Atomic single-row run admission; monthly and daily caps checked together.
CREATE TABLE IF NOT EXISTS v16_run_budget (
  id INTEGER PRIMARY KEY CHECK(id=1), day_key TEXT NOT NULL, month_key TEXT NOT NULL,
  daily_used INTEGER NOT NULL DEFAULT 0, monthly_used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS v16_deal_dedup (
  asin TEXT PRIMARY KEY, price_cents INTEGER NOT NULL, status TEXT NOT NULL, owner TEXT NOT NULL DEFAULT '',
  updated_at INTEGER NOT NULL DEFAULT 0
);

-- Speed up V16 hourly/daily deal-cap queries.
CREATE INDEX IF NOT EXISTS v16_deal_dedup_updated_at_idx
ON v16_deal_dedup(updated_at);

-- V16 only: persistent observed product prices.
CREATE TABLE IF NOT EXISTS v16_price_history (
    asin TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK(price_cents > 0),
    observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (asin, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_v16_price_history_lookup
ON v16_price_history (asin, observed_at);
