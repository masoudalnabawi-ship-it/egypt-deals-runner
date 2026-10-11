import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.v15.product_leasing import (
    claim_product,
    release_product,
)


class ProductLeasingTests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        schema = Path(
            "cloudflare_amazon_v15/migrations/"
            "0002_product_monitoring.sql"
        ).read_text()
        self.db.executescript(schema)

        self.now = datetime(
            2026, 10, 11, 12, 0,
            tzinfo=timezone.utc,
        )

        self.db.execute(
            """
            INSERT INTO product_monitoring
            (asin, next_check_at, updated_at)
            VALUES (?, ?, ?)
            """,
            (
                "B0DK4Z4GPJ",
                self.now.isoformat(),
                self.now.isoformat(),
            ),
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_first_worker_claims(self):
        self.assertTrue(
            claim_product(
                self.db, "B0DK4Z4GPJ", "worker-a", self.now
            )
        )

    def test_second_worker_blocked(self):
        self.assertTrue(
            claim_product(
                self.db, "B0DK4Z4GPJ", "worker-a", self.now
            )
        )
        self.assertFalse(
            claim_product(
                self.db, "B0DK4Z4GPJ", "worker-b", self.now
            )
        )

    def test_expired_lease_recovered(self):
        self.assertTrue(
            claim_product(
                self.db, "B0DK4Z4GPJ",
                "worker-a", self.now, lease_minutes=1
            )
        )
        self.assertTrue(
            claim_product(
                self.db, "B0DK4Z4GPJ",
                "worker-b",
                self.now + timedelta(minutes=2)
            )
        )

    def test_release_requires_owner(self):
        claim_product(
            self.db, "B0DK4Z4GPJ", "worker-a", self.now
        )

        self.assertFalse(
            release_product(
                self.db,
                "B0DK4Z4GPJ",
                "worker-b",
                self.now,
                self.now + timedelta(minutes=3),
            )
        )

    def test_release_reschedules(self):
        claim_product(
            self.db, "B0DK4Z4GPJ", "worker-a", self.now
        )

        self.assertTrue(
            release_product(
                self.db,
                "B0DK4Z4GPJ",
                "worker-a",
                self.now,
                self.now + timedelta(minutes=3),
            )
        )

        row = self.db.execute(
            """
            SELECT lease_owner, next_check_at
            FROM product_monitoring
            WHERE asin = ?
            """,
            ("B0DK4Z4GPJ",),
        ).fetchone()

        self.assertIsNone(row[0])
        self.assertEqual(
            row[1],
            (self.now + timedelta(minutes=3)).isoformat(),
        )


if __name__ == "__main__":
    unittest.main()
