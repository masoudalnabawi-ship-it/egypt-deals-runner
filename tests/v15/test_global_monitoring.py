import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'v15'))
import d1_monitoring_lease as d1
import monitoring_cycle


class GlobalMonitoringTests(unittest.TestCase):
    def test_claims_due_product_with_atomic_update(self):
        seen = []
        def fake_query(sql):
            seen.append(sql)
            return [{'asin': 'B000000001', 'priority': 'HOT',
                     'consecutive_errors': 0, 'lease_owner': seen_owner(sql)}]
        def seen_owner(sql):
            return sql.split('SET lease_owner=')[1].split("'")[1]
        with patch.object(d1, 'query', side_effect=fake_query):
            row = d1.claim_next_due()
        self.assertEqual(row['asin'], 'B000000001')
        self.assertIn("CASE priority WHEN 'HOT' THEN 0", seen[0])
        self.assertIn("next_check_at ASC", seen[0])
        self.assertLess(
            seen[0].index("CASE priority WHEN 'HOT' THEN 0"),
            seen[0].index("next_check_at ASC")
        )
        self.assertIn("julianday(next_check_at)", seen[0])
        self.assertIn("(60.0 / 1440.0)", seen[0])
        self.assertIn('RETURNING asin, priority', seen[0])
        self.assertIn('lease_until <=', seen[0])

    def test_no_due_product(self):
        with patch.object(d1, 'query', return_value=[]):
            self.assertIsNone(d1.claim_next_due())

    def test_auto_claim_passes_asin_to_following_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / 'output')
            envfile = str(Path(tmp) / 'env')
            lease = {'asin': 'B000000001', 'priority': 'ACTIVE',
                     'lease_owner': 'v15-owner'}
            with patch.object(sys, 'argv', ['monitoring_cycle.py', 'claim']), \
                 patch.object(monitoring_cycle, 'claim_next_due', return_value=lease), \
                 patch.dict(os.environ, {'GITHUB_OUTPUT': output, 'GITHUB_ENV': envfile}, clear=True):
                monitoring_cycle.main()
            self.assertIn('asin=B000000001', Path(output).read_text())
            self.assertIn('V15_TEST_ASIN=B000000001', Path(envfile).read_text())

    def test_explicit_asin_still_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sys, 'argv', ['monitoring_cycle.py', 'claim', '--asin', 'B000000001']), \
                 patch.object(monitoring_cycle, 'claim', return_value=None) as claim, \
                 patch.dict(os.environ, {'GITHUB_OUTPUT': str(Path(tmp) / 'output')}, clear=True):
                monitoring_cycle.main()
            claim.assert_called_once_with('B000000001', lease_minutes=30)


if __name__ == '__main__':
    unittest.main()
