import unittest

from deals_v13.discovery.noon import NoonDiscovery
from deals_v13.discovery.scheduler import Surface


class NoonLiveHtmlTests(unittest.TestCase):

    def test_canonical_product_link_fallback(self):
        html = """
        <html>
          <div class="random-generated-class-x91">
            <a href="/egypt-en/test-phone/N70012345V/p/">
              <img alt="Test Phone 256GB"
                   src="https://example.com/a.jpg">
            </a>

            <div class="some-price-container">
              EGP 12,499
            </div>

            <div class="some-price-old">
              EGP 14,999
            </div>
          </div>
        </html>
        """

        surface = Surface(
            "mobiles",
            "mobiles",
            "https://www.noon.com/egypt-en/",
            1.0,
        )

        deals = NoonDiscovery.parse_page(
            html,
            surface,
        )

        self.assertEqual(len(deals), 1)
        self.assertEqual(
            deals[0].external_id,
            "N70012345V",
        )
        self.assertEqual(
            deals[0].current_price,
            12499.0,
        )
        self.assertEqual(
            deals[0].old_price,
            14999.0,
        )


if __name__ == "__main__":
    unittest.main()
