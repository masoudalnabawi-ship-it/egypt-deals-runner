"""Persistent Amazon competitor discovery memory."""

import re
import sqlite3
import time
from pathlib import Path

ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")


class CompetitorMemory:
    def __init__(self, connection):
        self.db = connection

    def discover(self, asin, source, timestamp=None):
        asin = str(asin).strip().upper()
        source = str(source).strip()

        if not ASIN_PATTERN.fullmatch(asin):
            raise ValueError("Invalid Amazon ASIN")

        if not source:
            raise ValueError("Source is required")

        now = int(time.time()) if timestamp is None else int(timestamp)

        with self.db:
            self.db.execute(
                """
                INSERT INTO v15_amazon_candidates
                    (asin, first_seen_at, last_seen_at)
                VALUES (?, ?, ?)
                ON CONFLICT(asin) DO UPDATE SET
                    last_seen_at = MAX(last_seen_at, excluded.last_seen_at)
                """,
                (asin, now, now),
            )

            self.db.execute(
                """
                INSERT INTO v15_amazon_signals
                    (asin, source, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(asin, source) DO UPDATE SET
                    last_seen_at = MAX(
                        last_seen_at, excluded.last_seen_at
                    ),
                    sightings = sightings + 1
                """,
                (asin, source, now, now),
            )

    def source_count(self, asin):
        row = self.db.execute(
            """
            SELECT COUNT(*)
            FROM v15_amazon_signals
            WHERE asin = ?
            """,
            (asin,),
        ).fetchone()

        return row[0]


def create_local_memory(db_path, migration_path):
    connection = sqlite3.connect(str(db_path))
    connection.execute("PRAGMA foreign_keys = ON")

    connection.executescript(
        Path(migration_path).read_text(encoding="utf-8")
    )

    return CompetitorMemory(connection)
