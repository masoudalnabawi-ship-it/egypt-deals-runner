import unittest
from unittest.mock import MagicMock, patch

import production_discovery as discovery


class Discovery503RetryTests(unittest.TestCase):

    def test_http_503_recovers_on_second_attempt(self):
        page = MagicMock()
        page.goto.side_effect = [
            MagicMock(status=503),
            MagicMock(status=200),
        ]
        page.title.return_value = "Amazon Egypt"
        page.evaluate.return_value = {
            "title": "Amazon Egypt",
            "asin_nodes": 1,
            "search_cards": 1,
            "product_links": 1,
            "body_length": 500,
        }
        page.url = discovery.SOURCES[0]

        context = MagicMock()
        context.new_page.return_value = page

        browser = MagicMock()
        browser.new_context.return_value = context

        playwright = MagicMock()
        playwright.chromium.launch.return_value = browser

        manager = MagicMock()
        manager.__enter__.return_value = playwright

        candidate = {
            "asin": "B0867X1QGP",
            "url": "https://www.amazon.eg/dp/B0867X1QGP",
            "listing_discount_hint": 80,
            "source": discovery.SOURCES[0],
        }

        with patch.object(discovery.time, "sleep") as sleep, \
             patch.object(
                 discovery,
                 "extract_cards",
                 return_value=[candidate],
             ):
            result = discovery.discover(
                max_pages=1,
                pages=[discovery.SOURCES[0]],
                browser_factory=lambda: manager,
            )

        self.assertEqual(page.goto.call_count, 2)
        sleep.assert_called_once_with(2)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main()
