import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "v16"))
from live_pipeline import run_pipeline

class TextFirstTests(unittest.TestCase):
    def test_send_text_before_photo(self):
        calls = []
        def probe(asin):
            yield ({"asin": asin, "title": "test", "current_price": "100",
                    "displayed_discount_pct": "90"}, "/tmp/unused", "digest")
        def alert(obs, **kwargs):
            calls.append("photo" if kwargs.get("screenshot_path") else "text")
            return "SENT"
        result = run_pipeline(send=True, max_candidates=1,
            discover_fn=lambda **kw: [{"asin": "B000000001"}],
            probe_fn=probe, alert_fn=alert)
        self.assertEqual(calls, ["text", "photo"])
        self.assertEqual(result["probed"], 1)
    def test_dry_run_never_sends_photo(self):
        calls = []
        def probe(asin):
            yield ({"asin": asin}, "/tmp/unused", "digest")
        def alert(obs, **kwargs):
            calls.append(kwargs)
            return "DISABLED"
        run_pipeline(send=False, max_candidates=1,
            discover_fn=lambda **kw: [{"asin": "B000000001"}],
            probe_fn=probe, alert_fn=alert)
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0]["enabled"])

if __name__ == "__main__": unittest.main()
