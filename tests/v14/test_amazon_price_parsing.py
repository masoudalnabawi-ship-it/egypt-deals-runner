import unittest

from deals_v14.discovery.amazon import _p


class AmazonPriceParsingTests(unittest.TestCase):

    def test_price_formats(self):
        cases = {
            "EGP 1,299.50": 1299.50,
            "١٬٢٩٩٫٥٠ ج.م": 1299.50,
            "1.299,50": 1299.50,
            "1299": 1299.0,
            "1299.50": 1299.50,
            "غير متوفر": 0.0,
        }

        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(_p(raw), expected)


if __name__ == "__main__":
    unittest.main()
