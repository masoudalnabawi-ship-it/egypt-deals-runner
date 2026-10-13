import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'v16'))
from safe_runner import run

R = {'asin': 'B000000001', 'title': 'Item', 'price_egp': '199', 'displayed_discount_pct': '91'}

class RunnerTests(unittest.TestCase):
    def test_dry_run_never_sends(self):
        called = []
        self.assertEqual(run(R, transport=lambda *a, **k: called.append(1))['status'], 'DRY_RUN')
        self.assertEqual(called, [])
    def test_below_threshold_never_sends(self):
        called = []
        self.assertEqual(run(dict(R, displayed_discount_pct='49'), send=True,
                             transport=lambda *a, **k: called.append(1))['status'], 'BELOW_THRESHOLD')
        self.assertEqual(called, [])
    def test_explicit_send(self):
        called = []
        def fake(report, *, enabled):
            called.append((report, enabled))
            return 'SENT'
        self.assertEqual(run(R, send=True, transport=fake)['status'], 'SENT')
        self.assertEqual(len(called), 1)
        self.assertTrue(called[0][1])
    def test_rejects_missing_price(self):
        with self.assertRaises(ValueError):
            run({'asin': 'B000000001', 'displayed_discount_pct': '91'})
