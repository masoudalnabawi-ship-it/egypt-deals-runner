import os
import unittest
from unittest.mock import patch

from deals_v13.config import Settings
from deals_v13.delivery.routed import RoutedTelegramDelivery


class SecondaryNoonBotTests(unittest.TestCase):

    def test_config_routes_noon_normal_and_ultra(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "primary-token",
            "AMAZON_REVIEW_GROUP_ID": "-100999",
            "REVIEW_CHAT_ID": "-100111",
            "NOON_REVIEW_BOT_TOKEN": "secondary-token",
            "NOON_REVIEW_BOT_CHAT_ID": "8816413399",
        }

        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env()

        self.assertEqual(
            settings.noon_normal_chat_id,
            "8816413399",
        )

        # Noon >=50% shares Amazon Ultra.
        self.assertEqual(
            settings.noon_ultra_chat_id,
            "-100999",
        )

    def test_delivery_split(self):
        router = object.__new__(RoutedTelegramDelivery)
        router.primary = "PRIMARY"
        router.secondary = "SECONDARY"

        self.assertEqual(
            router._delivery_for_row({
                "store": "noon",
                "lane": "normal",
            }),
            "SECONDARY",
        )

        self.assertEqual(
            router._delivery_for_row({
                "store": "noon",
                "lane": "ultra",
            }),
            "PRIMARY",
        )

        self.assertEqual(
            router._delivery_for_row({
                "store": "amazon",
                "lane": "normal",
            }),
            "PRIMARY",
        )

        self.assertEqual(
            router._delivery_for_row({
                "store": "amazon",
                "lane": "ultra",
            }),
            "PRIMARY",
        )


if __name__ == "__main__":
    unittest.main()
