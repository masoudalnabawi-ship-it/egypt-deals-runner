import tempfile
import unittest
from pathlib import Path

from deals_v13.infra.db import DealDatabase
from deals_v13.models import (
    DealCandidate,
    DealDecision,
    Lane,
)
from deals_v13.verification.verifier import StoreVerifier
from deals_v13.workers.pipeline import V13Pipeline


class FakeIntel:
    def evaluate(self, *args, **kwargs):
        deal = args[0]
        return DealDecision(
            lane=Lane.NORMAL,
            score=10.0,
            confidence=0.20,
            real_discount=deal.discount_percent,
            effective_price=deal.current_price,
            reasons=[],
        )


class AmazonUltraRecoveryTests(unittest.TestCase):

    def pipeline(self):
        pipeline = object.__new__(V13Pipeline)
        pipeline.intel = FakeIntel()
        return pipeline

    def candidate(
        self,
        source="50filter",
        old_price=None,
    ):
        return DealCandidate(
            store="amazon",
            external_id="B012345678",
            title="Amazon Test Product",
            url=(
                "https://www.amazon.eg/"
                "dp/B012345678"
            ),
            current_price=500.0,
            old_price=old_price,
            category="test",
            source=source,
        )

    def test_hot_filter_enters_ultra_verification_without_search_old_price(self):
        decision = self.pipeline()._preliminary(
            self.candidate("50filter")
        )

        self.assertEqual(
            decision.lane,
            Lane.ULTRA,
        )

        self.assertIn(
            "amazon_hot_radar_priority_50",
            decision.reasons,
        )

    def test_normal_surface_is_not_forced_ultra(self):
        decision = self.pipeline()._preliminary(
            self.candidate("mobiles")
        )

        self.assertEqual(
            decision.lane,
            Lane.NORMAL,
        )

    def test_live_current_and_strike_price_are_two_signals(self):
        html = """
        <html>
          <body>
            <div id="corePrice_feature_div">
              <span class="a-price">
                <span class="a-offscreen">
                  EGP 500.00
                </span>
              </span>

              <span class="basisPrice">
                <span class="a-offscreen">
                  EGP 1,000.00
                </span>
              </span>
            </div>

            <span id="productTitle">
              Amazon Test Product
            </span>
          </body>
        </html>
        """

        verifier = StoreVerifier(None)

        verified, meta = verifier._amazon(
            self.candidate("50filter"),
            html,
            "unit-test",
        )

        self.assertEqual(
            verified.current_price,
            500.0,
        )

        self.assertEqual(
            verified.old_price,
            1000.0,
        )

        self.assertGreaterEqual(
            meta["verification_signals"],
            2,
        )

    def test_hot_lane_is_not_downgraded_by_later_normal_search(self):
        with tempfile.TemporaryDirectory() as td:
            db = DealDatabase(
                str(Path(td) / "v13.db")
            )

            hot = self.candidate(
                "50filter"
            )

            hot_decision = DealDecision(
                lane=Lane.ULTRA,
                score=94.0,
                confidence=0.2,
                real_discount=0.0,
                effective_price=500.0,
                reasons=["hot"],
            )

            db.upsert_candidate(
                hot,
                hot_decision,
            )

            normal = self.candidate(
                "mobiles"
            )

            normal_decision = DealDecision(
                lane=Lane.NORMAL,
                score=10.0,
                confidence=0.2,
                real_discount=0.0,
                effective_price=500.0,
                reasons=[],
            )

            db.upsert_candidate(
                normal,
                normal_decision,
            )

            row = db.claim_for_verification(
                "amazon",
                Lane.ULTRA,
                "test-worker",
                60,
            )

            self.assertIsNotNone(row)
            self.assertEqual(
                row["lane"],
                Lane.ULTRA.value,
            )


if __name__ == "__main__":
    unittest.main()
