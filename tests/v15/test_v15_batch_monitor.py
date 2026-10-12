import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/v15'))
import batch_monitor


class BatchTests(unittest.TestCase):
    def test_workflow_uses_batch(self):
        workflow = (ROOT / '.github/workflows/v15-live-probe.yml').read_text()
        self.assertIn('python scripts/v15/batch_monitor.py', workflow)
        self.assertNotIn('- name: Diagnose evidence (non-sensitive summary)', workflow)

    def test_unavailable_rescheduled_without_price(self):
        lease = dict(asin='B000000001', lease_owner='v15-owner', priority='STABLE')
        with patch.object(batch_monitor, 'claim_next_due', side_effect=[lease, None]), \
             patch.object(batch_monitor, 'process', return_value='unavailable'), \
             patch.object(batch_monitor, 'release_after_failure') as fail, \
             patch.object(batch_monitor, 'release_after_success') as success, \
             patch.dict(os.environ, {'V15_BATCH_SIZE': '5'}):
            batch_monitor.main()
        fail.assert_called_once_with('B000000001', 'v15-owner')
        success.assert_not_called()

    def test_one_failure_does_not_block_next(self):
        a = dict(asin='B000000001', lease_owner='v15-a', priority='STABLE')
        b = dict(asin='B000000002', lease_owner='v15-b', priority='HOT')
        with patch.object(batch_monitor, 'claim_next_due', side_effect=[a,b,None]), \
             patch.object(batch_monitor, 'process', side_effect=[RuntimeError('error'), 'saved']), \
             patch.object(batch_monitor, 'release_after_failure') as fail, \
             patch.object(batch_monitor, 'release_after_success') as success, \
             patch.dict(os.environ, {'V15_BATCH_SIZE': '5'}):
            batch_monitor.main()
        fail.assert_called_once_with('B000000001', 'v15-a')
        success.assert_called_once_with('B000000002', 'v15-b', 'HOT')

    def test_invalid_batch_size(self):
        with patch.dict(os.environ, {'V15_BATCH_SIZE': '50'}):
            with self.assertRaises(ValueError):
                batch_monitor.main()
