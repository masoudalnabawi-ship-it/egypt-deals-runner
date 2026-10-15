import unittest

from deals_v14.discovery.amazon import AmazonDiscovery
from deals_v14.discovery.scheduler import Surface


def card_html(prices):
    return f"""
    <div data-component-type="s-search-result"
         data-asin="B012345678">
        <h2><a><span>Test Product</span></a></h2>
        {prices}
    </div>
    """


class AmazonSearchPriceTests(unittest.TestCase):
    def setUp(self):
        self.surface = Surface(
            name="test_search",
            category="electronics",
            url="https://www.amazon.eg/s?k=test",
            priority=1.0,
        )

    def parse(self, prices):
        return AmazonDiscovery.parse_search(
            card_html(prices),
            self.surface,
        )

    def test_current_price_and_strikethrough(self):
        deals = self.parse("""
            <span class="a-price">
                <span class="a-offscreen">EGP 799.00</span>
            </span>
            <span class="a-text-price">
                <span class="a-offscreen">EGP 1,599.00</span>
            </span>
        """)
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0].current_price, 799.0)
        self.assertEqual(deals[0].old_price, 1599.0)

    def test_unit_price_must_not_override_product_price(self):
        deals = self.parse("""
            <div class="unit-price">
                <span class="a-price">
                    <span class="a-offscreen">EGP 25.00</span>
                </span>
            </div>
            <div class="product-price">
                <span class="a-price">
                    <span class="a-offscreen">EGP 250.00</span>
                </span>
            </div>
        """)
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0].current_price, 250.0)

    def test_no_current_price_is_rejected(self):
        deals = self.parse("""
            <span class="a-text-price">
                <span class="a-offscreen">EGP 1,599.00</span>
            </span>
        """)
        self.assertEqual(deals, [])


if __name__ == "__main__":
    unittest.main()
