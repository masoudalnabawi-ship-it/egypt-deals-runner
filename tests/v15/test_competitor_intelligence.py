import unittest

from scripts.v15.competitor_intelligence import (
    SourcePerformance,
    source_reliability,
    discovery_priority,
)


class TestCompetitorIntelligence(unittest.TestCase):

    def test_new_source_is_neutral(self):
        score = source_reliability(SourcePerformance(0, 0, 0))
        self.assertEqual(score, 0.5)

    def test_good_source_beats_bad_source(self):
        good = source_reliability(SourcePerformance(100, 80, 20))
        bad = source_reliability(SourcePerformance(100, 20, 80))
        self.assertGreater(good, bad)

    def test_fresh_candidate_has_priority(self):
        fresh = discovery_priority(0.8, 5, 2)
        old = discovery_priority(0.8, 180, 2)
        self.assertGreater(fresh, old)

    def test_multiple_sources_increase_priority(self):
        one = discovery_priority(0.8, 10, 1)
        three = discovery_priority(0.8, 10, 3)
        self.assertGreater(three, one)

    def test_invalid_counters_rejected(self):
        with self.assertRaises(ValueError):
            source_reliability(SourcePerformance(5, 6, 0))


if __name__ == "__main__":
    unittest.main()
