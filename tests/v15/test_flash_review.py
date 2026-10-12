import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'v15'))
from flash_review import keyboard, preview, validate_custom_message, interactive_enabled
from unittest.mock import patch

C = {'asin':'B000000001','current_price':'2000'}
class ReviewTests(unittest.TestCase):
    def test_safe_default(self):
        self.assertEqual(len(keyboard(C)['inline_keyboard']), 1)
    def test_five_buttons(self):
        k=keyboard(C, interactive=True)['inline_keyboard']
        self.assertEqual(sum(map(len,k)),5)
        self.assertEqual(k[1][1]['callback_data'],'v15:edit:B000000001')
    def test_bad_asin(self):
        with self.assertRaises(ValueError): keyboard({'asin':'x'},interactive=True)
    def test_preview(self):
        p=preview(C,'عرض مخصص')
        self.assertIn('عرض مخصص',p)
        self.assertIn('غير مؤكد',p)
    def test_invalid_message(self):
        with self.assertRaises(ValueError): validate_custom_message(' ')
    def test_feature_gate(self):
        with patch.dict('os.environ', {'V15_SECURE_WEBHOOK_READY':'true','V15_INTERACTIVE_BUTTONS_ENABLED':'true'}):
            self.assertTrue(interactive_enabled())
        with patch.dict('os.environ', {'V15_INTERACTIVE_BUTTONS_ENABLED':'false'}):
            self.assertFalse(interactive_enabled())
