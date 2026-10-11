import unittest

from scripts.v15.price_intelligence import VerifiedPrice
from scripts.v15.review_gate import ScreenshotEvidence, review_decision


ASIN = "B012345678"
NOW = 2000


def evidence(**changes):
    data = {
        "asin": ASIN,
        "captured_at": 1950,
        "verified_at": 1900,
        "source": "amazon_egypt_playwright",
        "image_reference": "screenshots/B012345678.png",
    }
    data.update(changes)
    return ScreenshotEvidence(**data)


class TestReviewGate(unittest.TestCase):

    def test_ultra_with_evidence(self):
        result = review_decision(
            VerifiedPrice(ASIN, 400, 1000, True, True),
            evidence(),
            NOW,
        )
        self.assertTrue(result["approved"])
        self.assertEqual(result["route"], "ultra")

    def test_normal_with_evidence(self):
        result = review_decision(
            VerifiedPrice(ASIN, 700, 1000, True, True),
            evidence(),
            NOW,
        )
        self.assertEqual(result["route"], "normal")

    def test_missing_screenshot_blocked(self):
        result = review_decision(
            VerifiedPrice(ASIN, 400, 1000, True, True),
            None,
            NOW,
        )
        self.assertFalse(result["approved"])

    def test_wrong_product_blocked(self):
        result = review_decision(
            VerifiedPrice(ASIN, 400, 1000, True, True),
            evidence(asin="B999999999"),
            NOW,
        )
        self.assertFalse(result["approved"])

    def test_stale_screenshot_blocked(self):
        result = review_decision(
            VerifiedPrice(ASIN, 400, 1000, True, True),
            evidence(captured_at=100, verified_at=90),
            NOW,
        )
        self.assertFalse(result["approved"])

    def test_unverified_price_blocked(self):
        result = review_decision(
            VerifiedPrice(ASIN, 400, 1000, False, True),
            evidence(),
            NOW,
        )
        self.assertFalse(result["approved"])

    def test_competitor_image_blocked(self):
        result = review_decision(
            VerifiedPrice(ASIN, 400, 1000, True, True),
            evidence(source="competitor_telegram"),
            NOW,
        )
        self.assertFalse(result["approved"])


if __name__ == "__main__":
    unittest.main()
