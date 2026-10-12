import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "v15"))
import d1_monitoring_lease as lease


class UltraPriorityOrderTests(unittest.TestCase):
    def test_real_sql_priority_and_starvation(self):
        now = datetime.now(timezone.utc)
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE product_monitoring (
                asin TEXT PRIMARY KEY,
                priority TEXT,
                next_check_at TEXT,
                lease_owner TEXT,
                lease_until TEXT,
                updated_at TEXT,
                consecutive_errors INTEGER DEFAULT 0
            )
        """)

        def stamp(dt):
            return dt.isoformat(timespec="seconds")

        rows = [
            ("OLDSTABLE1", "STABLE", stamp(now - timedelta(minutes=90))),
            ("NEWHOT0001", "HOT", stamp(now - timedelta(minutes=2))),
            ("NEWSTABLE1", "STABLE", stamp(now - timedelta(minutes=2))),
        ]
        conn.executemany(
            "INSERT INTO product_monitoring "
            "(asin,priority,next_check_at) VALUES (?,?,?)",
            rows
        )

        def query(sql):
            cursor = conn.execute(sql)
            return [
                dict(zip([c[0] for c in cursor.description], row))
                for row in cursor.fetchall()
            ]

        with patch.object(lease, "query", side_effect=query):
            first = lease.claim_next_due()
            second = lease.claim_next_due()
            third = lease.claim_next_due()

        self.assertEqual(
            [first["asin"], second["asin"], third["asin"]],
            ["OLDSTABLE1", "NEWHOT0001", "NEWSTABLE1"]
        )
        conn.close()


if __name__ == "__main__":
    unittest.main()
