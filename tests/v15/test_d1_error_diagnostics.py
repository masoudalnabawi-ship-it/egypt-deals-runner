import os
import unittest
from unittest.mock import patch, MagicMock
from scripts.v15 import d1_monitoring_lease as d1


class D1DiagnosticsTests(unittest.TestCase):
    @patch("scripts.v15.d1_monitoring_lease.subprocess.run")
    def test_stdout_error_is_preserved(self, run):
        run.return_value = MagicMock(
            returncode=1,
            stderr="",
            stdout="Cloudflare D1 API error 503"
        )
        with patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "secret-token"}):
            with self.assertRaisesRegex(RuntimeError, "503"):
                d1.query("SELECT 1")

    @patch("scripts.v15.d1_monitoring_lease.subprocess.run")
    def test_secret_is_redacted(self, run):
        run.return_value = MagicMock(
            returncode=1,
            stderr="secret-token rejected",
            stdout=""
        )
        with patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "secret-token"}):
            with self.assertRaises(RuntimeError) as error:
                d1.query("SELECT 1")
        self.assertNotIn("secret-token", str(error.exception))
        self.assertIn("[REDACTED]", str(error.exception))


if __name__ == "__main__":
    unittest.main()
