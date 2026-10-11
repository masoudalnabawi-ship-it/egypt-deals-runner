import unittest

from scripts.v15.routing import route_amazon_review


class TestRouting(unittest.TestCase):

    def test_normal(self):
        for value in (0, 10, 49, 49.99):
            self.assertEqual(route_amazon_review(value, True), "normal")

    def test_ultra(self):
        for value in (50, 51, 65, 88, 99, 100):
            self.assertEqual(route_amazon_review(value, True), "ultra")

    def test_unverified(self):
        self.assertEqual(route_amazon_review(99, False), "reject")

    def test_invalid(self):
        for value in (-1, 101, None, "invalid", "NaN"):
            self.assertEqual(route_amazon_review(value, True), "reject")


if __name__ == "__main__":
    unittest.main()
