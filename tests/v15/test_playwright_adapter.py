import unittest

from scripts.v15.playwright_adapter import (
    VerificationResult,
    adapt_playwright_result,
)


ASIN = "B012345678"


def observation(**changes):
    result = {
        "page_asin": ASIN,
        "current_price": 400,
        "old_price": 1000,
        "reference_trusted": True,
        "coupon_percent": 0,
        "savings_percent": 60,
    }
    result.update(changes)
    return result


class TestPlaywrightAdapter(unittest.TestCase):

    def check(self, obs, verified=True):
        return adapt_playwright_result(
            VerificationResult(ASIN, obs, verified)
        )

    def test_verified_ultra(self):
        result = self.check(observation())
        self.assertTrue(result["approved"])
        self.assertEqual(result["route"], "ultra")

    def test_verified_normal(self):
        result = self.check(
            observation(current_price=700)
        )
        self.assertEqual(result["route"], "normal")

    def test_asin_mismatch_blocked(self):
        result = self.check(
            observation(page_asin="B999999999")
        )
        self.assertFalse(result["approved"])

    def test_unverified_page_blocked(self):
        result = self.check(observation(), False)
        self.assertFalse(result["approved"])

    def test_untrusted_reference_blocked(self):
        result = self.check(
            observation(reference_trusted=False)
        )
        self.assertFalse(result["approved"])

    def test_coupon_cannot_fake_discount(self):
        result = self.check(
            observation(
                current_price=1000,
                old_price=0,
                coupon_percent=60,
                savings_percent=60,
            )
        )
        self.assertFalse(result["approved"])

    def test_savings_badge_cannot_fake_discount(self):
        result = self.check(
            observation(
                current_price=1000,
                old_price=0,
                savings_percent=80,
            )
        )
        self.assertFalse(result["approved"])


if __name__ == "__main__":
    unittest.main()
