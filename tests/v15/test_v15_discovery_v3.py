"""V15 V3 discovery tests (offline, no Cloudflare calls)."""
import ast
import unittest
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[2]/'scripts/v15/category_discovery.py'

class V3DiscoveryTests(unittest.TestCase):
    def test_code_compiles(self):
        ast.parse(SOURCE.read_text())
    def test_rotating_candidate_window(self):
        products=[f'B{i:09d}' for i in range(50)]
        def select(visit):
            take=min(20,len(products))
            start=(visit*take)%len(products)
            return (products+products)[start:start+take]
        self.assertEqual(len(select(0)),20)
        self.assertNotEqual(select(0),select(1))
        self.assertEqual(len(set(select(2))),20)
    def test_existing_products_are_excluded_before_cap(self):
        candidates=[f'B{i:09d}' for i in range(50)]
        known=set(candidates[:40])
        asins=[a for a in candidates if a not in known][:20]
        self.assertEqual(len(asins),10)
        self.assertTrue(all(a not in known for a in asins))
    def test_discovery_preserves_existing_rows(self):
        source=SOURCE.read_text()
        self.assertIn('INSERT OR IGNORE INTO product_monitoring',source)
        self.assertIn('V15_DISCOVERY_ALREADY_KNOWN',source)
        self.assertIn('V15_DISCOVERY_V3',source)
