import unittest

from deals_v14.source_brain import (
    evaluate_source,
)


class SourceBrainTests(unittest.TestCase):

    def test_verified_productive_source_beats_noise(self):
        strong = evaluate_source(
            1.0,
            {
                "scans": 10,
                "candidates": 80,
                "verified": 30,
                "sent": 15,
                "errors": 0,
                "consecutive_errors": 0,
                "last_latency_ms": 800,
                "last_success_at": 1000,
            },
            now=1100,
        )

        noisy = evaluate_source(
            1.0,
            {
                "scans": 10,
                "candidates": 120,
                "verified": 1,
                "sent": 0,
                "errors": 0,
                "consecutive_errors": 0,
                "last_latency_ms": 800,
                "last_success_at": 1000,
            },
            now=1100,
        )

        self.assertGreater(
            strong.weight,
            noisy.weight,
        )

    def test_repeated_errors_receive_penalty(self):
        healthy = evaluate_source(
            1.0,
            {
                "scans": 10,
                "candidates": 50,
                "verified": 15,
                "sent": 5,
                "errors": 0,
                "consecutive_errors": 0,
                "last_latency_ms": 900,
            },
            now=1000,
        )

        broken = evaluate_source(
            1.0,
            {
                "scans": 10,
                "candidates": 50,
                "verified": 15,
                "sent": 5,
                "errors": 5,
                "consecutive_errors": 3,
                "last_latency_ms": 900,
            },
            now=1000,
        )

        self.assertGreater(
            healthy.weight,
            broken.weight,
        )

    def test_slow_source_is_penalized_not_killed(self):
        slow = evaluate_source(
            1.0,
            {
                "scans": 10,
                "candidates": 40,
                "verified": 10,
                "sent": 4,
                "errors": 0,
                "last_latency_ms": 9000,
            },
            now=1000,
        )

        self.assertGreater(
            slow.weight,
            0,
        )

        self.assertLess(
            slow.latency_factor,
            1.0,
        )

    def test_new_source_gets_exploration_boost(self):
        new = evaluate_source(
            1.0,
            {},
            now=1000,
        )

        self.assertGreater(
            new.exploration_boost,
            1.0,
        )

        self.assertGreater(
            new.weight,
            0.05,
        )


if __name__ == "__main__":
    unittest.main()
