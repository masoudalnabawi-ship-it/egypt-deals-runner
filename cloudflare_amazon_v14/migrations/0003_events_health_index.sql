-- V14: Improve source-health event lookups.
-- Non-destructive: preserves existing data and indexes.

CREATE INDEX IF NOT EXISTS idx_events_event_ts_deal
ON events(event, ts, deal_key);
