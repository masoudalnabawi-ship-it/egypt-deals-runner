import sqlite3
import unittest
from pathlib import Path

from scripts.v15.competitor_memory import CompetitorMemory

MIGRATION = Path(
    "cloudflare_amazon_v14/migrations/"
    "0003_v15_competitor_memory.sql"
)


class TestCompetitorMemory(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(MIGRATION.read_text())
        self.memory = CompetitorMemory(self.db)

    def tearDown(self):
        self.db.close()

    def test_single_product_multiple_sources(self):
        asin = "B012345678"

        self.memory.discover(asin, "channel_a", 100)
        self.memory.discover(asin, "channel_b", 110)

        self.assertEqual(self.memory.source_count(asin), 2)

        count = self.db.execute(
            "SELECT COUNT(*) FROM v15_amazon_candidates"
        ).fetchone()[0]

        self.assertEqual(count, 1)

    def test_repeated_source_does_not_duplicate(self):
        asin = "B012345678"

        self.memory.discover(asin, "channel_a", 100)
        self.memory.discover(asin, "channel_a", 120)

        self.assertEqual(self.memory.source_count(asin), 1)

        sightings = self.db.execute(
            """
            SELECT sightings FROM v15_amazon_signals
            WHERE asin=? AND source=?
            """,
            (asin, "channel_a"),
        ).fetchone()[0]

        self.assertEqual(sightings, 2)

    def test_invalid_asin(self):
        with self.assertRaises(ValueError):
            self.memory.discover("INVALID", "channel_a")

    def test_missing_source(self):
        with self.assertRaises(ValueError):
            self.memory.discover("B012345678", "")


if __name__ == "__main__":
    unittest.main()
