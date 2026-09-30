import unittest

from deals_v14.price_intelligence import (
    build_price_profile,
)


class PriceIntelligenceTests(unittest.TestCase):

    def test_robust_reference_ignores_one_inflated_price(self):
        profile = build_price_profile(
            [
                1000,
                1000,
                1000,
                1000,
                3000,
            ],
            700,
        )

        self.assertEqual(
            profile.reference_price,
            1000.0,
        )

        self.assertEqual(
            profile.drop_from_reference_pct,
            30.0,
        )

        self.assertTrue(
            profile.new_verified_low
        )

    def test_stable_history_marks_new_low(self):
        profile = build_price_profile(
            [
                1200,
                1190,
                1210,
                1200,
                1180,
                1200,
            ],
            900,
        )

        self.assertTrue(
            profile.mature_history
        )

        self.assertTrue(
            profile.new_verified_low
        )

        self.assertTrue(
            profile.strong_history_signal
        )

        self.assertLessEqual(
            profile.price_percentile,
            25.0,
        )

    def test_small_history_is_not_strong_signal(self):
        profile = build_price_profile(
            [1000, 950],
            500,
        )

        self.assertFalse(
            profile.mature_history
        )

        self.assertFalse(
            profile.strong_history_signal
        )

    def test_price_increase_is_not_a_discount(self):
        profile = build_price_profile(
            [
                800,
                850,
                900,
                820,
                830,
            ],
            1000,
        )

        self.assertEqual(
            profile.drop_from_reference_pct,
            0.0,
        )

        self.assertFalse(
            profile.new_verified_low
        )


if __name__ == "__main__":
    unittest.main()
