import unittest

from deals_v14.anomaly_shield import (
    inspect_deal,
)
from deals_v14.models import (
    DealCandidate,
)
from deals_v14.price_intelligence import (
    build_price_profile,
)


def deal(
    *,
    store="amazon",
    title="Samsung Galaxy A55 256GB",
    current=1000,
    old=None,
):
    return DealCandidate(
        store=store,
        external_id="B012345678",
        title=title,
        url="https://example.com/product",
        current_price=current,
        old_price=old,
        metadata={
            "currency": "EGP",
            "in_stock": True,
        },
    )


class AnomalyShieldTests(unittest.TestCase):

    def test_model_mismatch_is_blocked(self):
        incoming = deal(
            title="Samsung Galaxy A55 256GB",
        )

        verified = deal(
            title="Samsung Galaxy S24 256GB",
        )

        result = inspect_deal(
            incoming,
            verified,
            {
                "verification_signals": 3,
            },
        )

        self.assertTrue(
            result.hard_block
        )

    def test_wrong_currency_is_blocked(self):
        incoming = deal()

        verified = deal()

        verified.metadata["currency"] = "AED"

        result = inspect_deal(
            incoming,
            verified,
            {
                "verification_signals": 3,
            },
        )

        self.assertTrue(
            result.hard_block
        )

    def test_inflated_old_price_vs_history_is_blocked(self):
        profile = build_price_profile(
            [
                1000,
                1020,
                980,
                1000,
                990,
                1010,
            ],
            900,
        )

        incoming = deal(
            current=900,
        )

        verified = deal(
            current=900,
            old=3000,
        )

        result = inspect_deal(
            incoming,
            verified,
            {
                "verification_signals": 2,
            },
            profile,
        )

        self.assertTrue(
            result.hard_block
        )

        self.assertIn(
            "inflated_reference_price",
            result.reasons,
        )

    def test_extreme_discount_requires_extra_confirmation(self):
        incoming = deal(
            current=100,
        )

        verified = deal(
            current=100,
            old=1000,
        )

        result = inspect_deal(
            incoming,
            verified,
            {
                "verification_signals": 2,
                "amazon_savings_percent": 0,
            },
        )

        self.assertFalse(
            result.hard_block
        )

        self.assertEqual(
            result.required_signals,
            3,
        )

    def test_direct_amazon_savings_can_confirm_80_percent(self):
        incoming = deal(
            current=200,
        )

        verified = deal(
            current=200,
            old=1000,
        )

        result = inspect_deal(
            incoming,
            verified,
            {
                "verification_signals": 2,
                "amazon_savings_percent": 80,
            },
        )

        self.assertFalse(
            result.hard_block
        )

        self.assertEqual(
            result.required_signals,
            2,
        )


if __name__ == "__main__":
    unittest.main()
