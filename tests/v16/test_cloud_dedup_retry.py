import unittest
from unittest.mock import patch

import cloud_dedup


class CloudDedupRetryTests(unittest.TestCase):
    def setUp(self):
        self.candidate = {
            "asin": "B0867X1QGP",
            "current_price": 899,
        }

    def check_case(self, responses, expected_error=False):
        responses = iter(responses)
        sends = []
        finishes = []

        def fake_request(path, payload):
            if path == "/dedup/claim":
                return {"allowed": True}
            if path == "/dedup/finish":
                finishes.append(payload)
                result = next(responses)
                if isinstance(result, Exception):
                    raise result
                return result
            raise AssertionError(path)

        def fake_sender(candidate):
            sends.append(candidate["asin"])
            return True

        with patch.object(cloud_dedup, "request", fake_request), \
             patch("time.sleep", return_value=None):
            if expected_error:
                with self.assertRaisesRegex(
                    RuntimeError,
                    "V16_D1_FINALIZATION_UNCONFIRMED"
                ):
                    cloud_dedup.send_once(
                        self.candidate, fake_sender
                    )
            else:
                self.assertEqual(
                    cloud_dedup.send_once(
                        self.candidate, fake_sender
                    ),
                    "SENT"
                )

        self.assertEqual(len(sends), 1)
        return len(finishes)

    def test_temporary_failure(self):
        self.assertEqual(self.check_case([
            ConnectionError("temporary"),
            {"ok": True},
        ]), 2)

    def test_persistent_failure(self):
        self.assertEqual(self.check_case([
            ConnectionError("first"),
            ConnectionError("second"),
            ConnectionError("third"),
        ], expected_error=True), 3)

    def test_unconfirmed_response(self):
        self.assertEqual(self.check_case([
            {"ok": False},
            {"ok": False},
            {"ok": False},
        ], expected_error=True), 3)


if __name__ == "__main__":
    unittest.main()
