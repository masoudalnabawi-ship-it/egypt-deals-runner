import unittest

from deals_v13.verification.verifier import _coupon_percent


class CouponEligibilityTests(unittest.TestCase):

    def test_nbe_card_discount_is_ignored(self):
        self.assertEqual(
            _coupon_percent(
                "Get 10% discount with NBE Visa Signature credit card"
            ),
            0.0,
        )

    def test_arabic_bank_discount_is_ignored(self):
        self.assertEqual(
            _coupon_percent(
                "خصم 15% عند الدفع ببطاقة البنك الأهلي"
            ),
            0.0,
        )

    def test_installment_offer_is_ignored(self):
        self.assertEqual(
            _coupon_percent(
                "Save 20% with selected credit card installments"
            ),
            0.0,
        )

    def test_public_coupon_is_kept(self):
        self.assertEqual(
            _coupon_percent("Apply 10% coupon"),
            10.0,
        )


if __name__ == "__main__":
    unittest.main()
