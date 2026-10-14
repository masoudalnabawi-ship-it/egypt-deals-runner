import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/v16'))
from telegram_config import interactive_ready, token, review_chat
from professional_alert import review_keyboard

class ProfessionalUpgradeTests(unittest.TestCase):
    def test_keyboard_default_safe(self):
        self.assertNotIn('callback_data', review_keyboard({'asin':'B012345678'}))
    def test_v16_credentials_priority(self):
        with patch.dict(os.environ, {'V16_TELEGRAM_BOT_TOKEN':'new', 'V15_TELEGRAM_BOT_TOKEN':'old', 'V16_TELEGRAM_REVIEW_CHAT_ID':'123', 'V15_TELEGRAM_REVIEW_CHAT_ID':'456'}):
            self.assertEqual(token(), 'new')
            self.assertEqual(review_chat(), '123')
    def test_interactive_requires_all_gates(self):
        with tempfile.TemporaryDirectory() as d:
            env={'V16_INTERACTIVE_READY':'1','V16_PRIVATE_TELEGRAM_ENABLED':'1','V16_TELEGRAM_ADMIN_ID':'123','V16_TELEGRAM_REVIEW_CHAT_ID':'123','V16_DEDUP_BACKEND':'sqlite','V16_DEDUP_DB':str(Path(d)/'db.sqlite'),'V16_WORKER_URL':'https://v16.example.workers.dev','V16_REGISTRATION_SECRET':'test-only-secret'}
            with patch.dict(os.environ, env, clear=True):
                self.assertTrue(interactive_ready())
                os.environ['V16_INTERACTIVE_READY']='0'
                self.assertFalse(interactive_ready())
                os.environ['V16_INTERACTIVE_READY']='1'
                del os.environ['V16_REGISTRATION_SECRET']
                self.assertFalse(interactive_ready())
if __name__ == '__main__': unittest.main()
