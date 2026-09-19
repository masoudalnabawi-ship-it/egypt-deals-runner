from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / ".runtime_state" / "v12.db"


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(
        DB_PATH,
        timeout=20,
    )

    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=15000")

    return con


def init_db():
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS queue_items (
                fingerprint TEXT PRIMARY KEY,
                store TEXT NOT NULL,
                payload TEXT NOT NULL,

                status TEXT NOT NULL DEFAULT 'pending',

                priority INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,

                next_attempt_at INTEGER NOT NULL DEFAULT 0,

                last_error TEXT NOT NULL DEFAULT '',

                discovered_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,

                review_message_id INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_v12_queue_status
            ON queue_items(status, next_attempt_at, priority);

            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                fingerprint TEXT NOT NULL,
                store TEXT NOT NULL,

                current_price REAL NOT NULL,
                old_price REAL,

                seen_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_v12_price_history
            ON price_history(fingerprint, seen_at);
            """
        )

        con.commit()
