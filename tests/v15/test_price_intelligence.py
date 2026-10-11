import unittest

from scripts.v15.price_intelligence import (
    VerifiedPrice,
    evaluate_price,
)


class TestPriceIntelligence(unittest.TestCase):

    def test_ultra_50(self):
        result = evaluate_price(
            VerifiedPrice("B012345678", 500, 1000, True, True)
        )
        self.assertEqual(result["route"], "ultra")
        self.assertEqual(result["discount"], "50.00")

    def test_normal_49(self):
        result = evaluate_price(
            VerifiedPrice("B012345678", 510, 1000, True, True)
        )
        self.assertEqual(result["route"], "normal")

    def test_unverified_blocked(self):
        result = evaluate_price(
            VerifiedPrice("B012345678", 100, 1000, False, True)
        )
        self.assertFalse(result["publish_allowed"])

    def test_untrusted_reference_blocked(self):
        result = evaluate_price(
            VerifiedPrice("B012345678", 100, 1000, True, False)
        )
        self.assertFalse(result["publish_allowed"])

    def test_invalid_price_blocked(self):
        result = evaluate_price(
            VerifiedPrice("B012345678", -10, 1000, True, True)
        )
        self.assertFalse(result["publish_allowed"])

    def test_no_discount_blocked(self):
        result = evaluate_price(
            VerifiedPrice("B012345678", 1000, 1000, True, True)
        )
        self.assertFalse(result["publish_allowed"])

    def test_no_rounding_into_ultra(self):
        result = evaluate_price(
            VerifiedPrice("B012345678", 500.01, 1000, True, True)
        )
        self.assertEqual(result["route"], "normal")


if __name__ == "__main__":
    unittest.main()
