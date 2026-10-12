import json
import hashlib
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'v15'))
from scripts.v15.evidence_pipeline import evaluate_evidence
from scripts.v15.d1_price_observation import prepare_observation
from scripts.v15.product_intelligence import classify, first_listing_signal
from scripts.v15 import d1_monitoring_lease as d1
from unittest.mock import patch

class V15UpgradeTests(unittest.TestCase):
    def evidence(self, old_price=None, current_price='131'):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base=Path(temp.name)
        jpeg=b'\xff\xd8\xff\xe0example'
        (base/'proof.jpg').write_bytes(jpeg)
        obs={'page_asin':'B012345678','current_price':current_price,'old_price':old_price}
        report={'asin':'B012345678','observation':obs,'screenshot':'proof.jpg',
                'screenshot_sha256':hashlib.sha256(jpeg).hexdigest(),
                'captured_at':'2026-10-11T10:00:00+00:00'}
        p=base/'verification.json'
        p.write_text(json.dumps(report))
        return p

    def test_first_listing_without_old_price_is_observation_only(self):
        p=self.evidence()
        self.assertEqual(evaluate_evidence(p)['status'],'awaiting_reference_verification')
        self.assertEqual(prepare_observation(p)['price'],'131')
        self.assertFalse(prepare_observation(p)['discount_verified'])

    def test_invalid_current_price_rejected(self):
        p=self.evidence(current_price='NaN')
        self.assertEqual(evaluate_evidence(p)['status'],'rejected')
        with self.assertRaises(ValueError):prepare_observation(p)

    def test_screenshot_tampering_rejected(self):
        p=self.evidence()
        (p.parent/'proof.jpg').write_bytes(b'wrong')
        self.assertEqual(evaluate_evidence(p)['status'],'rejected')

    def test_no_fake_discount_from_bad_old_price(self):
        p=self.evidence(old_price='20')
        r=evaluate_evidence(p)
        self.assertEqual(r['status'],'awaiting_reference_verification')
        self.assertNotIn('displayed_discount',r)

    def test_product_family_separation(self):
        self.assertEqual(classify('Android smartphone 128GB')['family'],'android_phone')
        self.assertEqual(classify('Feature phone keypad')['family'],'feature_phone')
        self.assertFalse(classify('Treadmill replacement belt')['comparable'])
        self.assertFalse(classify('Washing machine motor only')['comparable'])
        self.assertFalse(classify('Smart TV monthly payment')['comparable'])
        self.assertFalse(classify('unknown item')['comparable'])

    def test_first_listing_is_not_auto_published(self):
        r=first_listing_signal('Electric treadmill',131,[10000,12000,14000])
        self.assertEqual(r['status'],'extreme_candidate')
        self.assertFalse(r['publish_allowed'])
        self.assertEqual(first_listing_signal('Treadmill oil',131,[10000,12000,14000])['status'],'insufficient_evidence')
        self.assertEqual(first_listing_signal('Electric treadmill',131,[12000])['status'],'insufficient_evidence')

    def test_d1_failure_backoff_uses_supported_sql(self):
        with patch.object(d1,'query',return_value=[{'asin':'B012345678','consecutive_errors':1,'next_check_at':'2026-10-12T10:00:00+00:00'}]) as q:
            d1.release_after_failure('B012345678','v15-owner')
        sql=q.call_args.args[0]
        self.assertNotIn('POWER(',sql.upper())
        self.assertIn('CASE',sql)
