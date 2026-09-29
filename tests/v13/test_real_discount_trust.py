import tempfile
import unittest
from pathlib import Path

from deals_v13.infra.db import DealDatabase
from deals_v13.models import DealCandidate, DealDecision, Lane
from deals_v13.verification.verifier import StoreVerifier


class RealDiscountTrustTests(unittest.TestCase):

    def test_amazon_search_old_price_is_not_trusted(self):
        incoming = DealCandidate(
            store="amazon",
            external_id="B012345678",
            title="Test product",
            url="https://www.amazon.eg/dp/B012345678",
            current_price=4990,
            old_price=22000,
            category="electronics",
            source="test",
        )

        html = """
        <html>
          <span id="productTitle">Test product</span>
          <div id="corePrice_feature_div">
            <span class="a-price">
              <span class="a-offscreen">EGP 4,990.00</span>
            </span>
          </div>
        </html>
        """

        verified, _ = StoreVerifier(None)._amazon(
            incoming, html, "unit"
        )

        self.assertIsNone(verified.old_price)
        self.assertEqual(verified.discount_percent, 0.0)

    def test_discovery_price_does_not_enter_trusted_history(self):
        with tempfile.TemporaryDirectory() as td:
            db = DealDatabase(str(Path(td) / "v13.db"))

            deal = DealCandidate(
                store="amazon",
                external_id="B012345678",
                title="Test product",
                url="https://www.amazon.eg/dp/B012345678",
                current_price=500,
                old_price=5000,
                category="electronics",
                source="test",
            )

            pre = DealDecision(
                lane=Lane.ULTRA,
                score=100,
                confidence=.9,
                real_discount=90,
                effective_price=500,
                reasons=[],
            )

            db.upsert_candidate(deal, pre)

            self.assertEqual(
                db.recent_prices(deal.key),
                [],
            )

            verified = DealCandidate(
                store="amazon",
                external_id="B012345678",
                title="Test product",
                url="https://www.amazon.eg/dp/B012345678",
                current_price=500,
                old_price=None,
                category="electronics",
                source="test",
            )

            decision = DealDecision(
                lane=Lane.NORMAL,
                score=20,
                confidence=.8,
                real_discount=0,
                effective_price=500,
                reasons=[],
            )

            db.mark_verified(
                deal.key,
                verified,
                decision,
                {},
            )

            self.assertEqual(
                db.recent_prices(deal.key),
                [500.0],
            )


if __name__ == "__main__":
    unittest.main()
