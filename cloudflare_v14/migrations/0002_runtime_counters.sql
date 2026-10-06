CREATE TABLE IF NOT EXISTS runtime_counters (
  key TEXT PRIMARY KEY,
  value INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_runtime_counters_updated
ON runtime_counters(updated_at DESC);
