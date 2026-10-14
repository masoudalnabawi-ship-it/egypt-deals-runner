import unittest
from unittest.mock import Mock

from production_discovery import extract_cards


class ListingDiscountUnicodeTests(unittest.TestCase):
    def test_discount_patterns(self):
        cases = [
            ("خصم 50%", 50),
            ("-75\u200e%\u200e", 75),
            ("وفر 90%", 90),
            ("-99\u200f%", 99),
            ("منتج بدون خصم", None),
        ]

        for index, (text, expected) in enumerate(cases):
            with self.subTest(text=text):
                page = Mock()
                page.url = "https://www.amazon.eg/deals"
                page.locator.return_value.evaluate_all.return_value = [{
                    "asin": f"B{index:09d}",
                    "text": text,
                }]

                result = extract_cards(page)

                self.assertEqual(len(result), 1)
                self.assertEqual(
                    result[0]["listing_discount_hint"],
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
