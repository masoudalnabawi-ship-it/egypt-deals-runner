import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'v16'))
from flash_hunter import FlashOffer, LocalDeduplicator, prepare_private_alert


def offer(pct, price='100'):
    return FlashOffer('B000000001', 'Example product', price, str(pct), 'https://www.amazon.eg/dp/B000000001')


class FlashHunterTests(unittest.TestCase):
    def test_boundary_and_all_urgent_tiers(self):
        for pct, tier in [('50', 'ULTRA'), ('69.99', 'ULTRA'), ('70', 'SUPER_ULTRA'),
                          ('89.99', 'SUPER_ULTRA'), ('90', 'FLASH'), ('99.99', 'FLASH')]:
            alert = prepare_private_alert(offer(pct))
            self.assertEqual(alert['tier'], tier)
            self.assertTrue(alert['private_only'])
            self.assertFalse(alert['verified_historical_price'])
            self.assertIn('لم يُتحقق', alert['message'])

    def test_nonurgent(self):
        self.assertIsNone(prepare_private_alert(offer('49.99')))

    def test_bad_values(self):
        for pct, price in [('NaN', '100'), ('100', '100'), ('-1', '100'), ('50', '0'), ('50', 'Infinity')]:
            with self.assertRaises(ValueError):
                prepare_private_alert(offer(pct, price))

    def test_local_dedup_and_price_change(self):
        dedup = LocalDeduplicator()
        a = prepare_private_alert(offer('75'))
        self.assertTrue(dedup.should_send(a))
        self.assertFalse(dedup.should_send(a))
        self.assertTrue(dedup.should_send(prepare_private_alert(offer('75', '90'))))

    def test_no_history_required(self):
        self.assertIn('الخصم المعلن: 95%', prepare_private_alert(offer('95'))['message'])


if __name__ == '__main__':
    unittest.main()
