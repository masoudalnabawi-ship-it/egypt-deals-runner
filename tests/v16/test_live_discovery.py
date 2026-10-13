import importlib.util
import pathlib
import unittest
from unittest.mock import Mock

P = pathlib.Path(__file__).resolve().parents[2] / 'scripts/v16/live_discovery.py'
spec = importlib.util.spec_from_file_location('v16_live_discovery', P)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class DiscoveryTests(unittest.TestCase):
    def test_valid_listing(self):
        page = Mock()
        page.url = 'https://www.amazon.eg/deals'
        page.locator.return_value.evaluate_all.return_value = [
            {'asin': 'B012345678', 'text': 'خصم 89%'},
            {'asin': 'B012345678', 'text': 'خصم 89%'},
            {'asin': 'BAD', 'text': '-95%'},
        ]
        rows = mod.extract_cards(page)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['listing_discount_hint'], 89)

    def test_unknown_discount_is_unverified(self):
        page = Mock()
        page.url = 'https://www.amazon.eg/deals'
        page.locator.return_value.evaluate_all.return_value = [{'asin': 'B012345678', 'text': 'Great TV'}]
        self.assertIsNone(mod.extract_cards(page)[0]['listing_discount_hint'])

    def test_bounds(self):
        with self.assertRaises(ValueError):
            mod.discover(max_pages=100)
        with self.assertRaises(ValueError):
            mod.discover(pages=['https://example.org/'])


if __name__ == '__main__':
    unittest.main()
