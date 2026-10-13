import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'v16'))
from verified_alert_bridge import from_verified_report

class VerifiedAlertBridgeTests(unittest.TestCase):
    def test_urgent_without_history(self):
        result = from_verified_report({'asin':'B000000001','current_price_egp':'99',
            'displayed_discount_pct':'91','title':'Example','url':'https://www.amazon.eg/dp/B000000001'})
        self.assertTrue(result['score']['urgent_private_alert'])
        self.assertEqual(result['private_alert']['tier'],'FLASH')
        self.assertFalse(result['private_alert']['verified_historical_price'])
    def test_below_threshold(self):
        result = from_verified_report({'asin':'B000000001','price_egp':'99','displayed_discount_pct':'49.99'})
        self.assertIsNone(result['private_alert'])
    def test_missing_discount_fails_closed(self):
        with self.assertRaises(ValueError):
            from_verified_report({'asin':'B000000001','price_egp':'99'})
    def test_invalid_price_fails_closed(self):
        with self.assertRaises(ValueError):
            from_verified_report({'asin':'B000000001','price_egp':'NaN','displayed_discount_pct':'90'})
