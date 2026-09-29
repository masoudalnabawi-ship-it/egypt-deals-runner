import json
import unittest

from deals_v13.delivery.telegram import TelegramDelivery


class DummySettings:
    telegram_token = "test-token"
    noon_ultra_chat_id = "1"
    noon_normal_chat_id = "1"
    ultra_chat_id = "1"
    normal_chat_id = "1"


class TelegramFormatTests(unittest.TestCase):
    def test_caption_uses_real_newlines_and_clean_labels(self):
        sender = TelegramDelivery(DummySettings())
        row = {
            "store": "amazon",
            "lane": "ultra",
            "title": "Test Product",
            "current_price": 100,
            "old_price": 200,
            "real_discount": 50,
            "confidence": .8,
            "score": 77,
            "effective_price": 90,
            "external_id": "B012345678",
            "category": "electronics",
            "metadata_json": json.dumps({
                "decision_reasons": [
                    "product_page_verified",
                    "multi_signal_price",
                    "coupon_10",
                ]
            }),
        }
        caption = sender._caption(row)
        self.assertIn("\n", caption)
        self.assertNotIn("\\\\n", caption)
        self.assertIn("السعر الآن", caption)
        self.assertIn("الخصم الحقيقي", caption)
        self.assertNotIn("تم التحقق من صفحة المنتج", caption)
        self.assertLessEqual(len(caption), 1024)


if __name__ == "__main__":
    unittest.main()
