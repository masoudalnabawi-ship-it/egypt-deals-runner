import os
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from deals_v14.config import Settings
from deals_v14.intelligence import IntelligenceEngine
from deals_v14.models import DealCandidate, Lane
from deals_v14.verification.verifier import (
    _amazon_coupon_percent,
)


class AmazonCouponUltraTests(unittest.TestCase):

    def _settings(self):
        env = {
            "V14_ULTRA_MIN_DISCOUNT": "65",
            "V14_ULTRA_HOT_DISCOUNT": "75",
            "V14_MIN_CONFIDENCE_ULTRA": "0.76",
            "V14_MIN_CONFIDENCE_NORMAL": "0.62",
            "V14_NORMAL_MIN_DISCOUNT": "10",
        }

        with patch.dict(os.environ, env, clear=False):
            return Settings.from_env()

    def test_explicit_product_coupon_is_detected(self):
        html = """
        <html>
          <body>
            <div id="couponText">
              Apply 25% coupon
            </div>
          </body>
        </html>
        """

        soup = BeautifulSoup(html, "html.parser")

        coupon = _amazon_coupon_percent(soup)

        self.assertEqual(coupon, 25.0)

    def test_bank_card_discount_is_not_coupon(self):
        html = """
        <html>
          <body>
            <div id="couponText">
              25% coupon with CIB credit card installments
            </div>
          </body>
        </html>
        """

        soup = BeautifulSoup(html, "html.parser")

        coupon = _amazon_coupon_percent(soup)

        self.assertEqual(coupon, 0.0)

    def test_55_percent_plus_25_coupon_becomes_verified_ultra(self):
        settings = self._settings()
        engine = IntelligenceEngine(settings)

        deal = DealCandidate(
            store="amazon",
            external_id="B0COUPON65",
            title="Amazon Coupon Test Product",
            url="https://www.amazon.eg/dp/B0COUPON65",
            current_price=450.0,
            old_price=1000.0,
            source="coupon_test",
        )

        # Visible discount:
        # 1000 -> 450 = 55%
        #
        # Explicit coupon:
        # 450 * 0.75 = 337.50
        #
        # Effective discount:
        # (1000 - 337.50) / 1000 = 66.25%
        decision = engine.evaluate(
            deal,
            verified=True,
            coupon_percent=25.0,
            verification_signals=2,
            history=[],
        )

        self.assertAlmostEqual(
            decision.effective_price,
            337.50,
            places=2,
        )

        self.assertAlmostEqual(
            decision.real_discount,
            66.25,
            places=2,
        )

        self.assertGreaterEqual(
            decision.confidence,
            settings.min_confidence_ultra,
        )

        self.assertEqual(
            decision.lane,
            Lane.ULTRA,
        )

        acceptable, reason = engine.acceptable(decision)

        self.assertTrue(
            acceptable,
            msg=reason,
        )


if __name__ == "__main__":
    unittest.main()
