import unittest

from deals_v13.models import DealCandidate
from deals_v13.verification.verifier import (
    StoreVerifier,
    VerificationRejected,
)


class NoonVerificationSafetyTests(unittest.TestCase):

    def _incoming(self, title):
        return DealCandidate(
            store="noon",
            external_id="N70158922V",
            title=title,
            url=(
                "https://www.noon.com/egypt-en/"
                "test/N70158922V/p/"
            ),
            current_price=20,
            old_price=None,
            category="mobiles",
            source="mobiles",
        )

    def test_placeholder_product_is_rejected(self):
        html = """
        <html>
          <div class="priceNow">EGP 20</div>
          <div class="priceWas">EGP 27,999</div>
        </html>
        """

        with self.assertRaises(VerificationRejected):
            StoreVerifier(None)._noon(
                self._incoming("placeholder"),
                html,
                "noon_cffi",
            )

    def test_one_signal_extreme_discount_is_rejected(self):
        html = """
        <html>
          <div class="priceNow">EGP 500</div>
          <div class="priceWas">EGP 5,000</div>
        </html>
        """

        incoming = self._incoming(
            "Real Smartphone 256GB"
        )
        incoming.current_price = 500

        with self.assertRaises(VerificationRejected):
            StoreVerifier(None)._noon(
                incoming,
                html,
                "noon_cffi",
            )

    def test_pagewide_coupon_is_not_used_by_noon(self):
        html = """
        <html>
          <div class="priceNow">EGP 8,799</div>
          <div class="priceWas">EGP 9,799</div>
          <div>20% bank card coupon</div>
        </html>
        """

        incoming = self._incoming(
            "Galaxy A07 Dual SIM 64GB"
        )
        incoming.current_price = 8799

        _verified, meta = StoreVerifier(None)._noon(
            incoming,
            html,
            "noon_cffi",
        )

        self.assertEqual(
            meta["coupon_percent"],
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
