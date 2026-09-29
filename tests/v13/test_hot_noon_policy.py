import unittest

from deals_v13.discovery.noon import NOON_SURFACES


class HotNoonPolicyTests(unittest.TestCase):

    def test_noon_uses_current_catalog_api(self):
        self.assertTrue(NOON_SURFACES)
        self.assertIn(
            "/_vs/nc/mp-customer-catalog-api"
            "/api/v3/u/search/",
            NOON_SURFACES[0].url,
        )

    def test_noon_requests_large_egypt_batch(self):
        self.assertIn(
            "limit=100",
            NOON_SURFACES[0].url,
        )


if __name__ == "__main__":
    unittest.main()
