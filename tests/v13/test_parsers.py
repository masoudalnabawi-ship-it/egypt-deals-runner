import unittest

from deals_v13.discovery.amazon import AmazonDiscovery
from deals_v13.discovery.noon import NoonDiscovery
from deals_v13.discovery.scheduler import Surface


class ParserTests(unittest.TestCase):
    def test_amazon_search_card(self):
        html = """
        <div data-component-type="s-search-result" data-asin="B0ABC12345">
          <h2><a href="/dp/B0ABC12345"><span>Test Phone 256GB</span></a></h2>
          <span class="a-price"><span class="a-offscreen">4,999.00</span></span>
          <span class="a-text-price"><span class="a-offscreen">9,999.00</span></span>
          <img class="s-image" src="https://img.test/x.jpg">
          <span>Limited time deal</span>
        </div>
        """
        out = AmazonDiscovery.parse_search(html, Surface("test", "mobiles", "x"))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].external_id, "B0ABC12345")
        self.assertGreater(out[0].discount_percent, 49)

    def test_noon_json(self):
        html = """
        <script type="application/json">
        {"product":{"sku":"N123456789","name":"Test Laptop X500",
        "salePrice":15000,"oldPrice":30000,
        "url":"/egypt-en/test-laptop/N123456789/p/"}}
        </script>
        """
        out = NoonDiscovery.parse_page(html, Surface("test", "computers", "x"))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].external_id, "N123456789")
        self.assertEqual(out[0].discount_percent, 50.0)


if __name__ == "__main__":
    unittest.main()
