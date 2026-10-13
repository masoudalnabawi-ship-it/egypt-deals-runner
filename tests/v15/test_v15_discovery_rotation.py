import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / 'scripts/v15/category_discovery.py'

class DiscoveryRotationTests(unittest.TestCase):
    def test_rotation_is_five_minute_slots(self):
        tree = ast.parse(SOURCE.read_text())
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        offsets = [n for n in ast.walk(main) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'offset' for t in n.targets)]
        self.assertEqual(len(offsets), 1)
        self.assertIn('// 300', ast.unparse(offsets[0].value))
    def test_metrics_distinguish_attempted_from_inserted(self):
        source=SOURCE.read_text()
        self.assertIn('V15_DISCOVERY_NEW',source)
        self.assertIn('V15_DISCOVERY_ATTEMPTED', source)
        self.assertIn('V15_DISCOVERY_NEW_COUNT', source)
        self.assertIn('not_measured', source)
        self.assertIn('INSERT OR IGNORE INTO product_monitoring', source)
        self.assertNotIn('SELECT COUNT(*) AS total FROM product_monitoring', source)
        self.assertIn('INSERT OR IGNORE INTO product_monitoring',source)
