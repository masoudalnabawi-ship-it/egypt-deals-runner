import unittest

from deals_v13.delivery.telegram import TelegramDelivery


class NoonScreenshotPriceGuardTests(unittest.TestCase):

    def test_percent_is_not_read_as_currency(self):
        text = (
            "خصم 6% شامل الضريبة "
            "390.75 ج.م. "
            "بدلاً من 419.15 ج.م."
        )

        values = TelegramDelivery._currency_values(text)

        self.assertIn(390.75, values)
        self.assertIn(419.15, values)
        self.assertNotIn(6.0, values)

    def test_english_egp_price(self):
        values = TelegramDelivery._currency_values(
            "EGP 12,750.00 was EGP 13,999.00"
        )

        self.assertIn(12750.0, values)
        self.assertIn(13999.0, values)


    def test_arabic_pound_word_price(self):
        values = TelegramDelivery._currency_values(
            "السعر 390.75 جنيه "
            "بدلاً من 419.15 جنيه"
        )

        self.assertIn(390.75, values)
        self.assertIn(419.15, values)

    def test_arabic_egyptian_pound_phrase(self):
        values = TelegramDelivery._currency_values(
            "390.75 جنيه مصري"
        )

        self.assertIn(390.75, values)

    def test_le_price(self):
        values = TelegramDelivery._currency_values(
            "L.E. 390.75"
        )

        self.assertIn(390.75, values)

    def test_percent_is_not_plain_price(self):
        values = (
            TelegramDelivery._plain_price_numbers(
                "خصم 6% السعر 390.75"
            )
        )

        self.assertNotIn(6.0, values)
        self.assertIn(390.75, values)


if __name__ == "__main__":
    unittest.main()
