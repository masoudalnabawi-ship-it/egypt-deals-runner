import unittest

from bs4 import BeautifulSoup

from deals_v13.verification.verifier import (
    _coupon_percent,
    _amazon_coupon_percent,
)


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


    def test_unrelated_page_percentage_is_not_coupon(self):
        soup = BeautifulSoup(
            """
            <html>
              <div>خصم 90% على منتج آخر</div>
              <div>NBE Visa Signature 10%</div>
              <div id="productTitle">Current product</div>
            </html>
            """,
            "html.parser",
        )
        self.assertEqual(
            _amazon_coupon_percent(soup),
            0.0,
        )

    def test_explicit_amazon_coupon_is_kept(self):
        soup = BeautifulSoup(
            """
            <div id="couponFeature">
              Apply 10% coupon
            </div>
            """,
            "html.parser",
        )
        self.assertEqual(
            _amazon_coupon_percent(soup),
            10.0,
        )

    def test_bank_offer_inside_coupon_area_is_still_ignored(self):
        soup = BeautifulSoup(
            """
            <div id="couponFeature">
              Get 10% with NBE Visa Signature credit card coupon
            </div>
            """,
            "html.parser",
        )
        self.assertEqual(
            _amazon_coupon_percent(soup),
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
