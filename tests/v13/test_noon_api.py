import json
import unittest

from deals_v13.discovery.noon import NoonDiscovery
from deals_v13.discovery.scheduler import Surface
from deals_v13.models import DealCandidate
from deals_v13.verification.verifier import StoreVerifier


class NoonApiTests(unittest.TestCase):
    def test_search_api_payload(self):
        payload = {
            "nbHits": 1,
            "hits": [{
                "sku": "N12345678A",
                "name": "Samsung Galaxy Test 256GB",
                "brand": "Samsung",
                "price": 20000,
                "sale_price": 15000,
                "image_url": "https://f.nooncdn.com/test.jpg",
                "url": "samsung-galaxy-test-256gb",
                "is_buyable": True,
                "product_rating": {"value": 4.7, "count": 55},
            }],
            "meta": {"title": "Egypt products"},
        }
        surface = Surface("mobiles", "mobiles", "https://example.invalid", 1.0)
        deals = NoonDiscovery.parse_page(json.dumps(payload), surface)
        self.assertEqual(len(deals), 1)
        d = deals[0]
        self.assertEqual(d.external_id, "N12345678A")
        self.assertEqual(d.current_price, 15000)
        self.assertEqual(d.old_price, 20000)
        self.assertIn("/egypt-en/", d.url)
        self.assertEqual(d.metadata["currency"], "EGP")

    def test_search_api_rejects_explicit_uae_market(self):
        payload = {
            "nbHits": 1,
            "hits": [{
                "sku": "N12345678A",
                "name": "Wrong Market Product",
                "price": 100,
                "sale_price": 80,
                "url": "wrong-market-product",
            }],
            "meta": {"title": "Shop in Dubai, UAE"},
        }
        surface = Surface("x", "x", "https://example.invalid", 1.0)
        self.assertEqual(NoonDiscovery.parse_page(json.dumps(payload), surface), [])

    def test_detail_api_payload(self):
        incoming = DealCandidate(
            store="noon",
            external_id="N12345678A",
            title="Samsung Galaxy Test 256GB",
            url="https://www.noon.com/egypt-en/test/N12345678A/p/",
            current_price=15000,
            old_price=20000,
            category="mobiles",
            source="mobiles",
        )
        payload = {
            "product": {
                "sku": "N12345678A",
                "product_title": "Samsung Galaxy Test 256GB",
                "brand": "Samsung",
                "image_urls": ["https://f.nooncdn.com/test.jpg"],
                "variants": [{
                    "sku": "N12345678A",
                    "offers": [{
                        "price": 20000,
                        "sale_price": 14900,
                        "store_name": "noon",
                        "is_buyable": True,
                        "stock": 8,
                        "offer_code": "offer1",
                    }],
                }],
            },
        }
        verifier = StoreVerifier(None)
        deal, meta = verifier._noon_api(incoming, json.dumps(payload), "direct")
        self.assertEqual(deal.current_price, 14900)
        self.assertEqual(deal.old_price, 20000)
        self.assertEqual(deal.metadata["currency"], "EGP")
        self.assertGreaterEqual(meta["verification_signals"], 2)
        self.assertIn("noon_catalog_api", meta["http_via"])


    def test_nested_price_object_does_not_use_discount_as_price(self):
        incoming = DealCandidate(
            store="noon",
            external_id="N51438100A",
            title="Sokany Turkish Coffee Maker 500 ml 600 W",
            url=(
                "https://www.noon.com/egypt-en/"
                "turkish-coffee-maker/N51438100A/p/"
            ),
            current_price=390.75,
            old_price=419.15,
            category="appliances",
            source="appliances",
        )

        payload = {
            "product": {
                "sku": "N51438100A",
                "product_title":
                    "Sokany Turkish Coffee Maker 500 ml 600 W",
                "variants": [{
                    "sku": "N51438100A",
                    "offers": [{
                        "price": {
                            "amount": 419.15,
                            "value": 419.15,
                        },
                        "sale_price": {
                            "discount": 6,
                            "value": 6,
                            "amount": 390.75,
                        },
                        "is_buyable": True,
                        "store_name": "noon",
                    }],
                }],
            },
        }

        verifier = StoreVerifier(None)

        deal, _meta = verifier._noon_api(
            incoming,
            json.dumps(payload),
            "noon_cffi",
        )

        self.assertAlmostEqual(
            deal.current_price,
            390.75,
            places=2,
        )
        self.assertAlmostEqual(
            deal.old_price,
            419.15,
            places=2,
        )
        self.assertNotEqual(
            deal.current_price,
            6.0,
        )

    def test_search_nested_price_object_uses_amount_not_percent(self):
        payload = {
            "nbHits": 1,
            "hits": [{
                "sku": "N51438100A",
                "name":
                    "Sokany Turkish Coffee Maker 500 ml 600 W",
                "price": {
                    "amount": 419.15,
                    "value": 419.15,
                },
                "sale_price": {
                    "discount": 6,
                    "value": 6,
                    "amount": 390.75,
                },
                "url": "turkish-coffee-maker",
                "is_buyable": True,
            }],
            "meta": {
                "title": "Egypt products"
            },
        }

        surface = Surface(
            "appliances",
            "appliances",
            "https://example.invalid",
            1.0,
        )

        deals = NoonDiscovery.parse_page(
            json.dumps(payload),
            surface,
        )

        self.assertEqual(
            len(deals),
            1,
        )
        self.assertAlmostEqual(
            deals[0].current_price,
            390.75,
            places=2,
        )
        self.assertAlmostEqual(
            deals[0].old_price,
            419.15,
            places=2,
        )


if __name__ == "__main__":
    unittest.main()
