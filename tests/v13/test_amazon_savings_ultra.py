import unittest

from deals_v13.models import DealCandidate
from deals_v13.verification.verifier import StoreVerifier


class AmazonSavingsUltraTests(unittest.TestCase):

    def test_product_savings_percent_recovers_old_price(self):
        incoming = DealCandidate(
            store="amazon",
            external_id="B012345678",
            title="Test Product",
            url="https://www.amazon.eg/dp/B012345678",
            current_price=500.0,
            source="50filter",
        )

        html = """
        <html><body>
          <div id="corePrice_feature_div">
            <span class="priceToPay">
              <span class="a-offscreen">
                EGP 500.00
              </span>
            </span>
            <span class="savingsPercentage">
              -50%
            </span>
          </div>
          <span id="productTitle">
            Test Product
          </span>
        </body></html>
        """

        verified, meta = StoreVerifier(
            None
        )._amazon(
            incoming,
            html,
            "unit",
        )

        self.assertAlmostEqual(
            verified.current_price,
            500.0,
            places=2,
        )

        self.assertAlmostEqual(
            verified.old_price,
            1000.0,
            places=2,
        )

        self.assertEqual(
            meta["amazon_savings_percent"],
            50.0,
        )

        self.assertGreaterEqual(
            meta["verification_signals"],
            2,
        )


if __name__ == "__main__":
    unittest.main()
