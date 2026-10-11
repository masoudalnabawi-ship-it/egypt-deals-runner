import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path("scripts/v15/price_history.py")
SPEC = importlib.util.spec_from_file_location("v15_history", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PriceHistoryTests(unittest.TestCase):

    def test_valid_price(self):
        self.assertEqual(str(MODULE.valid_price("2309")), "2309")

    def test_zero_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.valid_price(0)

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.valid_price(-5)

    def test_nan_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.valid_price("NaN")

    def test_infinity_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.valid_price("Infinity")

    def test_database_schema(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.sqlite"

            with sqlite3.connect(database) as connection:
                connection.executescript(MODULE.SCHEMA)

                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }

            self.assertIn("price_observations", tables)


if __name__ == "__main__":
    unittest.main()
