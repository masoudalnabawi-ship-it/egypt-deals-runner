import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/v15"))

from flash_candidate import candidate, stage


class FlashTests(unittest.TestCase):

    def report(self, asin="B0ABC12345", price="2000", old="18749", discount=90):
        return {
            "asin": asin,
            "url": "https://www.amazon.eg/dp/" + asin,
            "captured_at": "2026-10-12T08:00:00Z",
            "observation": {
                "page_asin": asin,
                "current_price": price,
                "old_price": old,
                "savings_percent": discount,
                "title": "LG TV 50 inch",
            },
        }

    def test_super_ultra(self):
        c = candidate(self.report(discount=91))
        self.assertIsNotNone(c)
        self.assertEqual(c["category"], "SUPER_ULTRA")
        self.assertEqual(c["displayed_discount_pct"], "91")
        self.assertFalse(c["publication_allowed"])

    def test_without_old_price(self):
        c = candidate(self.report(old=None, discount=91))
        self.assertIsNotNone(c)
        self.assertEqual(c["category"], "SUPER_ULTRA")

    def test_without_current_price(self):
        c = candidate(self.report(price=None, old=None, discount=91))
        self.assertIsNotNone(c)
        self.assertIsNone(c["current_price"])

    def test_ultra(self):
        self.assertEqual(candidate(self.report(discount=40))["category"], "STRONG")

    def test_normal(self):
        self.assertEqual(candidate(self.report(discount=10))["category"], "NORMAL")

    def test_below_threshold(self):
        self.assertIsNone(candidate(self.report(discount=0)))

    def test_no_displayed_discount(self):
        self.assertIsNone(candidate(self.report(discount=0)))

    def test_book_block(self):
        self.assertIsNone(candidate(self.report(asin="0345520378")))

    def test_asin_mismatch(self):
        r = self.report()
        r["observation"]["page_asin"] = "B000000000"
        self.assertIsNone(candidate(r))

    def test_stage(self):
        with TemporaryDirectory() as d:
            p = stage(self.report(discount=91), d)
            self.assertTrue(p.is_file())
            self.assertIn("AMAZON_DISPLAYED_DISCOUNT", p.read_text())


if __name__ == "__main__":
    unittest.main()
