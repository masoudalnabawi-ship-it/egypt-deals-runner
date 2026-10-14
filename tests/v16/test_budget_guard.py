import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'v16'))
import budget_guard

class BudgetGuardTests(unittest.TestCase):
    def test_missing_persistent_db_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError): budget_guard.claim_run(0)
    def test_atomic_limits(self):
        with tempfile.TemporaryDirectory() as d:
            env={'V16_BUDGET_DB':str(Path(d)/'budget.db'),'V16_DAILY_RUN_LIMIT':'2','V16_MONTHLY_RUN_LIMIT':'3'}
            with patch.dict(os.environ,env):
                self.assertTrue(budget_guard.claim_run(1_760_000_000))
                self.assertTrue(budget_guard.claim_run(1_760_000_000))
                self.assertFalse(budget_guard.claim_run(1_760_000_000))
                self.assertTrue(budget_guard.claim_run(1_760_086_400))
                self.assertFalse(budget_guard.claim_run(1_760_086_400))
    def test_invalid_limit_fails(self):
        with patch.dict(os.environ,{'V16_MAX_PROBES_PER_RUN':'100'}):
            with self.assertRaises(ValueError): budget_guard.max_probes()
if __name__=='__main__': unittest.main()
