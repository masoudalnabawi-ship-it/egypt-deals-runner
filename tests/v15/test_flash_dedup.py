import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/v15'))
import flash_dedup as d

class FlashDedupTests(unittest.TestCase):
    def test_cents(self):
        self.assertEqual(d.cents('2000.00'), 200000)
        with self.assertRaises(ValueError): d.cents('NaN')
    def test_claim_first(self):
        with patch.object(d, 'query', return_value=[{'owner': 'wrong'}]):
            with self.assertRaises(RuntimeError): d.claim({'asin':'B012345678','current_price':'2000'})
    def test_duplicate_skipped(self):
        sender = lambda c: self.fail('should not send')
        with patch.object(d, 'claim', return_value=None):
            self.assertEqual(d.send_once({}, sender), 'SKIPPED_DUPLICATE')
    def test_sent(self):
        with patch.object(d, 'claim', return_value='lease'), patch.object(d, 'finish') as finish:
            self.assertEqual(d.send_once({'asin':'B012345678'}, lambda c: True), 'SENT')
            finish.assert_called_once_with('B012345678', 'lease', True)
    def test_failed(self):
        with patch.object(d, 'claim', return_value='lease'), patch.object(d, 'finish') as finish:
            self.assertEqual(d.send_once({'asin':'B012345678'}, lambda c: False), 'SEND_FAILED_RETRY_LATER')
            finish.assert_called_once_with('B012345678', 'lease', False)
    def test_sql_rules(self):
        queries=[]
        with patch.object(d, 'query', side_effect=lambda sql: queries.append(sql) or []):
            self.assertIsNone(d.claim({'asin':'B012345678','current_price':'2000'}))
        self.assertIn('excluded.price_cents*10', queries[0])
        self.assertIn("-10 minutes", queries[0])
        self.assertIn("state='sent'", queries[0])

if __name__ == '__main__': unittest.main()
