import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'v16'))
from candidate_discovery import Candidate, prioritize


def c(asin, pct, category='electronics', age=None):
    return Candidate(asin, str(pct), category, 'sample', age)


class CandidateDiscoveryTests(unittest.TestCase):
    def test_urgent_before_normal(self):
        ranked = prioritize([c('B000000001', 20), c('B000000002', 99), c('B000000003', 50)])
        self.assertEqual([x.asin for x in ranked], ['B000000002', 'B000000003', 'B000000001'])

    def test_dedupe_highest_displayed_discount(self):
        ranked = prioritize([c('B000000001', 10), c('B000000001', 65)])
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].displayed_discount_pct, '65')

    def test_category_fairness_and_limit(self):
        ranked = prioritize([c('B000000001', 99), c('B000000002', 90), c('B000000003', 80, 'home')], limit=2, per_category=1)
        self.assertEqual([x.asin for x in ranked], ['B000000001', 'B000000003'])

    def test_invalid_and_under_five_ignored(self):
        ranked = prioritize([c('BAD', 90), c('B000000001', 'NaN'), c('B000000002', 4), c('B000000003', 5)])
        self.assertEqual([x.asin for x in ranked], ['B000000003'])

    def test_stale_first_when_discount_equal(self):
        ranked = prioritize([c('B000000001', 60, age=2), c('B000000002', 60, age=100)])
        self.assertEqual(ranked[0].asin, 'B000000002')

    def test_invalid_limits(self):
        with self.assertRaises(ValueError):
            prioritize([], limit=0)
        with self.assertRaises(ValueError):
            prioritize([], limit=2, per_category=3)


if __name__ == '__main__':
    unittest.main()
