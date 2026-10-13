import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/v16'))
from screenshot_flash import candidate_from_observation, send_flash

OFFER = {'asin':'B012345678','current_price':'2000','displayed_discount_pct':'89.3','title':'LG TV'}

class ScreenshotFlashTests(unittest.TestCase):
    def test_urgent_no_history(self):
        self.assertEqual(candidate_from_observation(OFFER)['category'], 'SUPER_ULTRA')
    def test_99_percent(self):
        self.assertEqual(candidate_from_observation(dict(OFFER, displayed_discount_pct='99'))['category'], 'FLASH')
    def test_49_percent(self):
        self.assertEqual(candidate_from_observation(dict(OFFER, displayed_discount_pct='49.9'))['category'], 'GOOD')
    def test_invalid(self):
        with self.assertRaises(ValueError):
            candidate_from_observation(dict(OFFER, current_price='NaN'))
    def test_disabled(self):
        self.assertEqual(send_flash(OFFER), 'DISABLED')
    def test_fallback_when_screenshot_missing(self):
        calls=[]
        with patch.dict(os.environ, {'V16_PRIVATE_TELEGRAM_ENABLED':'1','V15_TELEGRAM_BOT_TOKEN':'test','V15_TELEGRAM_REVIEW_CHAT_ID':'123'}):
            result=send_flash(OFFER,screenshot_path='/nonexistent.jpg',screenshot_sha256='a',enabled=True,
                sender=lambda c:True,initialize=lambda:None,
                send_once=lambda c,s: calls.append('text') or 'SENT',
                send_screenshot_once=lambda c,s: calls.append('image') or 'SCREENSHOT_SENT')
        self.assertEqual((result,calls),('SENT',['text']))
    def test_authentic_screenshot(self):
        calls=[]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'real.jpg';p.write_bytes(b'real page screenshot fixture')
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            with patch.dict(os.environ, {'V16_PRIVATE_TELEGRAM_ENABLED':'1','V15_TELEGRAM_BOT_TOKEN':'test','V15_TELEGRAM_REVIEW_CHAT_ID':'123'}):
                result=send_flash(OFFER,screenshot_path=p,screenshot_sha256=digest,enabled=True,
                    sender=lambda c:True,initialize=lambda:None,
                    send_once=lambda c,s: calls.append('text') or 'SENT',
                    send_screenshot_once=lambda c,s: calls.append('image') or 'SCREENSHOT_SENT')
        self.assertEqual((result,calls),('SCREENSHOT_SENT',['image']))
if __name__=='__main__':unittest.main()
