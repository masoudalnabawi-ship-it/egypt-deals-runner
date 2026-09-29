import unittest

from deals_v13.discovery.noon import NOON_SURFACES


class HotNoonPolicyTests(unittest.TestCase):

    def test_noon_uses_egypt_public_storefront(self):
        self.assertTrue(NOON_SURFACES)

        for surface in NOON_SURFACES[:3]:
            self.assertIn(
                "noon.com/egypt-en/",
                surface.url,
            )
            self.assertNotIn(
                "/_vs/nc/",
                surface.url,
            )

    def test_noon_requests_useful_batch(self):
        self.assertIn(
            "limit=50",
            NOON_SURFACES[0].url,
        )


if __name__ == "__main__":
    unittest.main()
