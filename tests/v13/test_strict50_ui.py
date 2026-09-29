import json
import unittest

from deals_v13.delivery.telegram import TelegramDelivery


class DummySettings:
    telegram_token = "x"
    normal_chat_id = "normal"
    ultra_chat_id = "ultra"
    noon_normal_chat_id = "noon-normal"
    noon_ultra_chat_id = "noon-ultra"


class Strict50UiTests(unittest.TestCase):
    def setUp(self):
        self.t = TelegramDelivery(DummySettings())

    def test_caption_removes_review_noise(self):
        row = {
            "store": "amazon",
            "lane": "ultra",
            "title": "Product",
            "current_price": 100,
            "old_price": 200,
            "effective_price": 90,
            "real_discount": 50,
            "score": 90,
            "confidence": .9,
            "external_id": "B012345678",
            "category": "electronics",
            "metadata_json": json.dumps({"decision_reasons": ["product_page_verified"]}),
        }
        c = self.t._caption(row)
        self.assertNotIn("التحقق:", c)
        self.assertNotIn("وقت المراجعة", c)
        self.assertNotIn("المرفق لقطة", c)

    def test_ultra_has_publish_buttons(self):
        row = {
            "lane": "ultra",
            "url": "https://www.amazon.eg/dp/B012345678",
            "deal_key": "abc",
        }
        kb = self.t._keyboard(row)
        flat = str(kb)
        self.assertIn("نشر عاجل", flat)
        self.assertIn("نشر عادي", flat)
        self.assertIn("رفض", flat)
        self.assertIn("فتح المنتج", flat)

    def test_strict_chat_mapping(self):
        self.assertEqual(self.t._chat_id("amazon", "normal"), "normal")
        self.assertEqual(self.t._chat_id("amazon", "ultra"), "ultra")
        self.assertEqual(self.t._chat_id("noon", "normal"), "noon-normal")
        self.assertEqual(self.t._chat_id("noon", "ultra"), "noon-ultra")


if __name__ == "__main__":
    unittest.main()
