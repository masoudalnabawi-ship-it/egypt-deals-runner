import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'v16'))
from deal_intelligence import Deal, evaluate


class DealIntelligenceTests(unittest.TestCase):
    def test_flash_alert_does_not_require_history(self):
        for pct in ('50', '70', '90', '99'):
            result = evaluate(Deal('B000000001', '100', pct))
            self.assertTrue(result['urgent_private_alert'])
            self.assertEqual(result['historical_verification'], 'unknown')

    def test_below_50_not_urgent(self):
        self.assertFalse(evaluate(Deal('B000000001', '100', '49.99'))['urgent_private_alert'])

    def test_price_history(self):
        self.assertEqual(evaluate(Deal('B000000001', '100', '60', '120'))['historical_verification'], 'new_low')

    def test_invalid_values(self):
        for price, pct in [('NaN', '50'), ('0', '50'), ('100', '100'), ('100', '-1')]:
            with self.assertRaises(ValueError):
                evaluate(Deal('B000000001', price, pct))


if __name__ == '__main__':
    unittest.main()
