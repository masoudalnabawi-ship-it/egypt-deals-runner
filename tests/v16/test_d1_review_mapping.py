import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import professional_sender


class FakeResponse(io.BytesIO):
    def __init__(self, data):
        super().__init__(json.dumps(data).encode())


class D1ReviewMappingTests(unittest.TestCase):
    discount = 90
    def test_d1_registration_without_local_sqlite(self):
        events = []

        def fake_open(request, timeout=None):
            url = request.full_url

            if url.endswith("/sendPhoto"):
                events.append("SEND_PHOTO")
                return FakeResponse({
                    "ok": True,
                    "result": {"message_id": 12345},
                })

            if url.endswith("/register"):
                events.append("REGISTER_D1")
                return FakeResponse({"ok": True})

            if url.endswith("/editMessageReplyMarkup"):
                events.append("ACTIVATE_BUTTONS")
                payload = json.loads(request.data)
                buttons = [
                    button
                    for row in payload["reply_markup"]["inline_keyboard"]
                    for button in row
                ]
                self.assertEqual(len(buttons), 5)
                return FakeResponse({"ok": True})

            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "test.jpg"
            image.write_bytes(b"\xff\xd8V16_TEST\xff\xd9")

            candidate = {
                "asin": "B0867X1QGP",
                "title": "منتج تجريبي",
                "current_price": 899,
                "displayed_discount_pct": self.discount,
                "screenshot_path": str(image),
                "screenshot_sha256": hashlib.sha256(
                    image.read_bytes()
                ).hexdigest(),
            }

            with patch.dict("os.environ", {
                "V16_DEDUP_BACKEND": "d1",
                "V16_WORKER_URL": "https://example.test",
                "V16_REGISTRATION_SECRET": "FAKE_SECRET",
            }), patch.object(
                professional_sender.urllib.request,
                "urlopen",
                fake_open
            ), patch.object(
                professional_sender,
                "interactive_ready",
                return_value=True
            ), patch(
                "review_store.save_review_message_id",
                side_effect=AssertionError(
                    "SQLite must not be used in D1 mode"
                )
            ):
                result = professional_sender.send(
                    candidate,
                    token="FAKE_TOKEN",
                    chat_id="123456",
                    opener=fake_open,
                )

        self.assertTrue(result)
        self.assertEqual(events, [
            "SEND_PHOTO",
            "REGISTER_D1",
            "ACTIVATE_BUTTONS",
        ])




class D1DiscountBoundary70Tests(D1ReviewMappingTests):
    discount = 70


class D1DiscountBoundary100Tests(D1ReviewMappingTests):
    discount = 100

if __name__ == "__main__":
    unittest.main()
