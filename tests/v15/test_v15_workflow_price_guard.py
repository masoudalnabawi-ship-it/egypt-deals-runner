import unittest
from pathlib import Path

class WorkflowPriceGuardTests(unittest.TestCase):
    def test_batch_keeps_price_validation_and_no_unavailable_save(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / '.github/workflows/v15-live-probe.yml').read_text()
        batch = (root / 'scripts/v15/batch_monitor.py').read_text()
        self.assertIn('python scripts/v15/batch_monitor.py', workflow)
        self.assertIn("if flags.get('price_unavailable') == 'true':", batch)
        self.assertIn('prepare_observation(verification)', batch)
