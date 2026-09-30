import unittest

from deals_v14.deal_score import smart_deal_score
from deals_v14.price_intelligence import (
    build_price_profile,
)


class SmartDealScoreTests(unittest.TestCase):

    def test_strong_verified_deal_beats_weak_one(self):
        strong = smart_deal_score(
            real_discount=60,
            confidence=0.90,
            verification_signals=2,
            effective_price=400,
            old_price=1000,
            market_advantage_pct=20,
            price_profile=build_price_profile(
                [950, 1000, 980, 1000, 970],
                400,
            ),
            flash=False,
            coupon_percent=0,
            anomaly=False,
            accessory_like=False,
            impossible_ratio=False,
        )

        weak = smart_deal_score(
            real_discount=60,
            confidence=0.40,
            verification_signals=1,
            effective_price=400,
            old_price=1000,
            market_advantage_pct=0,
            price_profile=None,
            flash=False,
            coupon_percent=0,
            anomaly=False,
            accessory_like=False,
            impossible_ratio=False,
        )

        self.assertGreater(
            strong.total,
            weak.total,
        )

    def test_history_boost_is_capped(self):
        score = smart_deal_score(
            real_discount=50,
            confidence=0.80,
            verification_signals=2,
            effective_price=500,
            old_price=1000,
            market_advantage_pct=0,
            price_profile=build_price_profile(
                [2000, 2000, 2000, 1900, 2100],
                500,
            ),
            flash=False,
            coupon_percent=0,
            anomaly=False,
            accessory_like=False,
            impossible_ratio=False,
        )

        self.assertLessEqual(
            score.historical_rarity,
            15.0,
        )

    def test_extreme_unverified_ratio_gets_penalty(self):
        score = smart_deal_score(
            real_discount=95,
            confidence=0.40,
            verification_signals=1,
            effective_price=50,
            old_price=1000,
            market_advantage_pct=0,
            price_profile=None,
            flash=False,
            coupon_percent=0,
            anomaly=True,
            accessory_like=False,
            impossible_ratio=True,
        )

        self.assertGreater(
            score.penalties,
            0,
        )

    def test_total_never_exceeds_100(self):
        score = smart_deal_score(
            real_discount=90,
            confidence=1.0,
            verification_signals=5,
            effective_price=100,
            old_price=5000,
            market_advantage_pct=90,
            price_profile=build_price_profile(
                [5000, 4800, 5200, 5000, 5100],
                100,
            ),
            flash=True,
            coupon_percent=50,
            anomaly=True,
            accessory_like=False,
            impossible_ratio=False,
        )

        self.assertLessEqual(
            score.total,
            100.0,
        )


if __name__ == "__main__":
    unittest.main()
