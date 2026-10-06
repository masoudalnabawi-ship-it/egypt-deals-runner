import tempfile
import time
import unittest

from deals_v14.infra.db import DealDatabase
from deals_v14.models import Lane


class VerificationPriorityTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = DealDatabase(
            f"{self.tmp.name}/priority_test.db"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _insert(
        self,
        *,
        deal_key,
        discount,
        score,
        source,
        discovered_offset=0,
    ):
        now = int(time.time())

        self.db._conn().execute(
            """
            INSERT INTO deals(
                deal_key,
                store,
                external_id,
                title,
                url,
                current_price,
                old_price,
                visible_discount,
                lane,
                score,
                confidence,
                state,
                discovered_at,
                updated_at,
                next_attempt_at,
                lease_until,
                source
            )
            VALUES(
                ?, 'amazon', ?, ?, ?,
                ?, 1000, ?, 'ultra',
                ?, 0.90, 'pending',
                ?, ?, 0, 0, ?
            )
            """,
            (
                deal_key,
                deal_key,
                f"Product {deal_key}",
                f"https://www.amazon.eg/dp/{deal_key}",
                1000 * (1 - discount / 100),
                discount,
                score,
                now + discovered_offset,
                now,
                source,
            ),
        )

    def test_75_then_70_then_65_regardless_of_score(self):
        # Give 65% the highest score deliberately.
        # Priority band must still beat raw score.
        self._insert(
            deal_key="TEST65AAA1",
            discount=65.0,
            score=99.9,
            source="65filter",
        )

        self._insert(
            deal_key="TEST70AAA1",
            discount=70.0,
            score=97.0,
            source="70filter",
        )

        self._insert(
            deal_key="TEST75AAA1",
            discount=75.0,
            score=90.0,
            source="75filter",
        )

        first = self.db.claim_for_verification(
            "amazon",
            Lane.ULTRA,
            "worker-test-1",
            180,
        )

        second = self.db.claim_for_verification(
            "amazon",
            Lane.ULTRA,
            "worker-test-2",
            180,
        )

        third = self.db.claim_for_verification(
            "amazon",
            Lane.ULTRA,
            "worker-test-3",
            180,
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNotNone(third)

        self.assertEqual(
            first["deal_key"],
            "TEST75AAA1",
        )

        self.assertEqual(
            second["deal_key"],
            "TEST70AAA1",
        )

        self.assertEqual(
            third["deal_key"],
            "TEST65AAA1",
        )


if __name__ == "__main__":
    unittest.main()
