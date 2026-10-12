import unittest


class UltraDiscountRankingTests(unittest.TestCase):
    def test_highest_displayed_discount_first(self):
        discounts = {
            "B000000090": 90.0,
            "B000000080": 80.0,
            "B000000070": 70.0,
            "B000000060": 60.0,
            "B000000050": 50.0,
        }
        candidates = list(reversed(discounts))

        ranked = sorted(
            candidates,
            key=lambda asin: (-discounts.get(asin, 0.0), asin)
        )

        self.assertEqual(ranked, list(discounts))

    def test_unknown_discount_goes_last(self):
        discounts = {"B000000090": 90.0}
        candidates = ["B000000001", "B000000090"]

        ranked = sorted(
            candidates,
            key=lambda asin: (-discounts.get(asin, 0.0), asin)
        )

        self.assertEqual(ranked[0], "B000000090")


if __name__ == "__main__":
    unittest.main()
