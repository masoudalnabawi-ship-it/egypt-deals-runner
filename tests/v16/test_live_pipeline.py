import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/v16'))
from live_pipeline import observation_from_report, run_pipeline

class TestPipeline(unittest.TestCase):
    def test_report_mapping(self):
        report = {'asin':'B000000001','observation':{'page_asin':'B000000001','title':'TV','current_price':'2000','savings_percent':'89'}}
        self.assertEqual(observation_from_report(report)['displayed_discount_pct'], '89')
    def test_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            observation_from_report({'asin':'B000000001','observation':{'page_asin':'B000000002'}})
    def test_bounded_pipeline(self):
        def fake_probe(asin):
            yield ({'asin':asin,'current_price':'2000','displayed_discount_pct':'89'}, '/tmp/image', 'hash')
        alert = Mock(return_value='DISABLED')
        result = run_pipeline(discover_fn=lambda **kwargs:[{'asin':'B000000001'}], probe_fn=fake_probe, alert_fn=alert)
        self.assertEqual(result['probed'], 1)
        self.assertEqual(result['alerts'][0]['status'], 'DISABLED')
        self.assertFalse(alert.call_args.kwargs['enabled'])
    def test_limit(self):
        with self.assertRaises(ValueError):
            run_pipeline(max_candidates=11)

if __name__ == '__main__': unittest.main()
