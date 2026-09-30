import unittest

from deals_v14.identity import (
    compatibility,
    signature,
)


class IdentityGuardTests(unittest.TestCase):

    def test_storage_is_not_product_model(self):
        sig = signature(
            "Samsung Galaxy A55 256GB"
        )

        self.assertIn(
            "A55",
            sig.models,
        )

        self.assertNotIn(
            "256GB",
            sig.models,
        )

    def test_different_models_same_storage_are_incompatible(self):
        a = signature(
            "Samsung Galaxy A55 256GB"
        )

        b = signature(
            "Samsung Galaxy S24 256GB"
        )

        ok, reasons = compatibility(
            a,
            b,
        )

        self.assertFalse(ok)

        self.assertIn(
            "model_mismatch",
            reasons,
        )


if __name__ == "__main__":
    unittest.main()
