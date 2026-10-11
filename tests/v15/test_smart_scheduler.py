import unittest
from datetime import datetime, timedelta, timezone

from scripts.v15.smart_scheduler import (
    ProductState,
    next_check_at,
    due_products,
)


class SmartSchedulerTests(unittest.TestCase):

    def setUp(self):
        self.now = datetime(
            2026, 10, 11, 12, 0,
            tzinfo=timezone.utc,
        )

    def test_hot_interval(self):
        state = ProductState(
            asin="B0DK4Z4GPJ",
            priority="HOT",
            last_checked_at=self.now,
        )
        self.assertEqual(
            next_check_at(state, self.now),
            self.now + timedelta(minutes=3),
        )

    def test_stable_interval(self):
        state = ProductState(
            asin="B0DK4Z4GPJ",
            priority="STABLE",
            last_checked_at=self.now,
        )
        self.assertEqual(
            next_check_at(state, self.now),
            self.now + timedelta(minutes=30),
        )

    def test_error_backoff(self):
        state = ProductState(
            asin="B0DK4Z4GPJ",
            priority="HOT",
            last_checked_at=self.now,
            consecutive_errors=3,
        )
        self.assertEqual(
            next_check_at(state, self.now),
            self.now + timedelta(minutes=24),
        )

    def test_new_product_due_immediately(self):
        state = ProductState(asin="B0DK4Z4GPJ")
        self.assertEqual(
            next_check_at(state, self.now),
            self.now,
        )

    def test_not_due(self):
        state = ProductState(
            asin="B0DK4Z4GPJ",
            priority="HOT",
            last_checked_at=self.now,
        )
        self.assertEqual(
            due_products([state], self.now),
            [],
        )

    def test_due_limit(self):
        states = [
            ProductState(asin=f"B00000000{i}")
            for i in range(5)
        ]
        self.assertEqual(
            len(due_products(states, self.now, limit=2)),
            2,
        )

    def test_invalid_priority(self):
        state = ProductState(
            asin="B0DK4Z4GPJ",
            priority="UNKNOWN",
        )
        with self.assertRaises(ValueError):
            next_check_at(state, self.now)


if __name__ == "__main__":
    unittest.main()
