CREATE TABLE IF NOT EXISTS v15_review_events (
 event_id TEXT PRIMARY KEY, asin TEXT NOT NULL, action TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v15_review_drafts (
 asin TEXT PRIMARY KEY, status TEXT NOT NULL, message TEXT,
 edit_prompt_message_id INTEGER, preview_message_id INTEGER,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS v15_review_messages (
 chat_id TEXT NOT NULL, message_id INTEGER NOT NULL, asin TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(chat_id,message_id)
);
