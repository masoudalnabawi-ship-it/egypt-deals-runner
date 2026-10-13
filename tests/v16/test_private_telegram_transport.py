import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'v16'))
from private_telegram_transport import candidate_from_report, send_verified_private

REPORT = {'asin': 'B000000001', 'title': 'Test item', 'price_egp': '199', 'displayed_discount_pct': '91'}

class TransportTests(unittest.TestCase):
    def test_urgent_candidate(self):
        self.assertEqual(candidate_from_report(REPORT)['category'], 'FLASH')
    def test_below_threshold(self):
        self.assertIsNone(candidate_from_report(dict(REPORT, displayed_discount_pct='49')))
    def test_disabled_never_calls_sender(self):
        calls = []
        self.assertEqual(send_verified_private(REPORT, sender=lambda x: calls.append(x)), 'DISABLED')
        self.assertFalse(calls)
    def test_missing_configuration_fails_closed(self):
        with patch.dict(os.environ, {'V16_PRIVATE_TELEGRAM_ENABLED': '1'}, clear=True):
            self.assertEqual(send_verified_private(REPORT, enabled=True), 'MISSING_TELEGRAM_CONFIGURATION')
    def test_opt_in_uses_dedup(self):
        seen = []
        def dedup(candidate, sender):
            seen.append(candidate)
            return 'SENT' if sender(candidate) else 'FAILED'
        with patch.dict(os.environ, {'V16_PRIVATE_TELEGRAM_ENABLED': '1',
                'V15_TELEGRAM_BOT_TOKEN': 'test', 'V15_TELEGRAM_REVIEW_CHAT_ID': '123'}, clear=True):
            result = send_verified_private(REPORT, enabled=True, sender=lambda x: True, dedup=dedup)
        self.assertEqual(result, 'SENT')
        self.assertEqual(len(seen), 1)
    def test_bad_discount_rejected(self):
        with self.assertRaises(ValueError):
            candidate_from_report(dict(REPORT, displayed_discount_pct='NaN'))
