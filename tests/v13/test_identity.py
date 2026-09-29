import unittest

from deals_v13.identity import signature, compatibility
from deals_v13.intelligence import title_similarity


class IdentityTests(unittest.TestCase):
    def test_same_phone_variant_matches(self):
        a = signature('Samsung Galaxy A55 5G 8GB RAM 256GB')
        b = signature('Samsung A55 5G Dual SIM 256 GB 8GB RAM')
        ok, reasons = compatibility(a, b)
        self.assertTrue(ok)
        self.assertGreater(title_similarity('Samsung Galaxy A55 5G 8GB RAM 256GB', 'Samsung A55 5G Dual SIM 256 GB 8GB RAM'), 0.70)

    def test_capacity_mismatch_rejected(self):
        a = signature('Samsung Galaxy S24 128GB')
        b = signature('Samsung Galaxy S24 256GB')
        ok, reasons = compatibility(a, b)
        self.assertFalse(ok)
        self.assertIn('capacity_mismatch', reasons)

    def test_model_mismatch_rejected(self):
        a = signature('LG TV 55NANO80')
        b = signature('LG TV 55UR7800')
        ok, reasons = compatibility(a, b)
        self.assertFalse(ok)
        self.assertIn('model_mismatch', reasons)

    def test_pack_mismatch_rejected(self):
        a = signature('Coffee capsules pack of 10')
        b = signature('Coffee capsules pack of 30')
        ok, reasons = compatibility(a, b)
        self.assertFalse(ok)


if __name__ == '__main__':
    unittest.main()
