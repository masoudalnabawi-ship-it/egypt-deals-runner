import unittest
from unittest.mock import Mock

from production_discovery import extract_cards


class ListingDOMExtractionTests(unittest.TestCase):

    def test_discount_from_savings_element(self):
        page = Mock()
        page.url = "https://www.amazon.eg/deals"

        def evaluate(script):
            self.assertIn("savingsPercentage", script)
            self.assertIn("3000", script)
            return [{
                "asin": "B0867X1QGP",
                "text": "منتج تجريبي -75\u200e%\u200e",
            }]

        page.locator.return_value.evaluate_all.side_effect = evaluate

        result = extract_cards(page)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["listing_discount_hint"], 75)

    def test_discount_after_first_900_characters(self):
        page = Mock()
        page.url = "https://www.amazon.eg/deals"

        page.locator.return_value.evaluate_all.return_value = [{
            "asin": "B0867X1QGP",
            "text": ("منتج " * 200) + "خصم 90%",
        }]

        result = extract_cards(page)

        self.assertEqual(result[0]["listing_discount_hint"], 90)


if __name__ == "__main__":
    unittest.main()
