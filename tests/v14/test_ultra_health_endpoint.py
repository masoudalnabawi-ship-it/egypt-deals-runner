"""Safety checks for authenticated, read-only Ultra telemetry."""
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
class UltraHealthEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'cloudflare_amazon_v14/src/index.ts').read_text()
    def test_endpoint_is_get_only_and_authenticated(self):
        s = self.source
        a = s.index("url.pathname === '/admin/ultra-health'")
        b = s.index("url.pathname === '/admin/bootstrap'", a)
        block = s[a:b]
        self.assertIn("request.method === 'GET'", s[a-38:a])
        self.assertIn('adminAllowed(request, env)', block)
        self.assertIn('unauthorized', block)
    def test_diagnostics_are_read_only(self):
        s = self.source
        a = s.index("url.pathname === '/admin/ultra-health'")
        b = s.index("url.pathname === '/admin/bootstrap'", a)
        block = s[a:b]
        self.assertEqual(block.count('.prepare('), 2)
        self.assertNotIn('.run(', block)
        self.assertNotIn('scanAmazonSurface', block)
        self.assertIn("store='amazon'", block)
    def test_no_schedule_or_ultra_threshold_changes(self):
        s = (ROOT / 'cloudflare_amazon_v14/wrangler.jsonc').read_text()
        self.assertIn('*/15 * * * *', s)
        self.assertIn('"V14_ULTRA_HOT_DISCOUNT": "75"', s)
if __name__ == '__main__': unittest.main()
