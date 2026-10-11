import sqlite3
import unittest
from pathlib import Path

from scripts.v15.competitor_memory import CompetitorMemory
from scripts.v15.competitor_intelligence import SourcePerformance
from scripts.v15.competitor_processor import (
    CompetitorSignal,
    process_competitor_signal,
)

MIGRATION = Path(
    "cloudflare_amazon_v14/migrations/"
    "0003_v15_competitor_memory.sql"
)


class TestCompetitorProcessor(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(MIGRATION.read_text())
        self.memory = CompetitorMemory(self.db)

    def tearDown(self):
        self.db.close()

    def test_discovery_never_publishes(self):
        result = process_competitor_signal(
            CompetitorSignal("B012345678", "channel_a", 5),
            self.memory,
            SourcePerformance(100, 80, 20),
        )

        self.assertFalse(result["publish_allowed"])
        self.assertEqual(
            result["status"], "pending_verification"
        )

    def test_multiple_sources_increase_priority(self):
        stats = SourcePerformance(100, 80, 20)

        first = process_competitor_signal(
            CompetitorSignal("B012345678", "channel_a", 5),
            self.memory,
            stats,
        )

        second = process_competitor_signal(
            CompetitorSignal("B012345678", "channel_b", 5),
            self.memory,
            stats,
        )

        self.assertGreater(
            second["verification_priority"],
            first["verification_priority"],
        )

    def test_invalid_asin_rejected(self):
        with self.assertRaises(ValueError):
            process_competitor_signal(
                CompetitorSignal("INVALID", "channel_a", 5),
                self.memory,
                SourcePerformance(0, 0, 0),
            )


if __name__ == "__main__":
    unittest.main()
