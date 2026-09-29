import unittest

from deals_v13.infra.http import _noon_storefront_url


class NoonBrowserFallbackTests(unittest.TestCase):
    def test_catalog_search_maps_to_egypt_storefront(self):
        src = (
            "https://www.noon.com/_vs/nc/mp-customer-catalog-api/"
            "api/v3/u/search?q=mobile+phones"
        )
        out = _noon_storefront_url(src)
        self.assertEqual(
            out,
            "https://www.noon.com/egypt-en/search/?q=mobile+phones",
        )

    def test_product_url_is_unchanged(self):
        src = "https://www.noon.com/egypt-en/sample/N12345678A/p/"
        self.assertEqual(_noon_storefront_url(src), src)


if __name__ == "__main__":
    unittest.main()
