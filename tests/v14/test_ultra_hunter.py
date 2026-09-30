import unittest

from deals_v14.discovery.scheduler import Surface
from deals_v14.models import (
    DealCandidate,
    DealDecision,
    Lane,
)
from deals_v14.ultra_hunter import (
    UltraHunterPlanner,
)


def surface(name, category="global"):
    return Surface(
        name=name,
        category=category,
        url=f"https://example.com/{name}",
        priority=1.0,
    )


def normal_decision():
    return DealDecision(
        lane=Lane.NORMAL,
        score=10.0,
        confidence=0.2,
        real_discount=0.0,
        effective_price=100.0,
        reasons=[],
    )


class UltraHunterTests(unittest.TestCase):

    def test_amazon_filters_are_always_selected(self):
        planner = UltraHunterPlanner()

        available = [
            surface("mobiles"),
            surface("50filter"),
            surface("70filter"),
            surface("90filter"),
            surface("limited_time"),
            surface("clearance"),
        ]

        plan = planner.pick_surfaces(
            "amazon",
            available,
            5,
        )

        names = {
            item.name
            for item in plan.surfaces
        }

        self.assertIn(
            "50filter",
            names,
        )
        self.assertIn(
            "70filter",
            names,
        )
        self.assertIn(
            "90filter",
            names,
        )

    def test_noon_core_prevents_fashion_only_hunter(self):
        planner = UltraHunterPlanner()

        available = [
            surface("mobiles", "mobiles"),
            surface("laptops", "computers"),
            surface("appliances", "appliances"),
            surface("men_fashion", "fashion"),
            surface("women_fashion", "fashion"),
            surface("beauty", "beauty"),
        ]

        plan = planner.pick_surfaces(
            "noon",
            available,
            5,
        )

        names = {
            item.name
            for item in plan.surfaces
        }

        self.assertIn(
            "mobiles",
            names,
        )
        self.assertIn(
            "laptops",
            names,
        )
        self.assertIn(
            "appliances",
            names,
        )

    def test_amazon_filter_without_old_price_gets_fast_verification(self):
        planner = UltraHunterPlanner()

        deal = DealCandidate(
            store="amazon",
            external_id="B012345678",
            title="Test Amazon Product",
            url="https://www.amazon.eg/dp/B012345678",
            current_price=500.0,
            old_price=None,
            source="50filter",
        )

        decision = normal_decision()

        accepted = planner.prioritize(
            deal,
            decision,
        )

        self.assertTrue(accepted)

        self.assertEqual(
            decision.lane,
            Lane.ULTRA,
        )

        self.assertGreaterEqual(
            decision.score,
            95.0,
        )

    def test_noon_46_percent_gets_probe_but_not_final_approval(self):
        planner = UltraHunterPlanner()

        deal = DealCandidate(
            store="noon",
            external_id="N12345678A",
            title="Test Noon Product",
            url="https://www.noon.com/egypt-en/x/N12345678A/p/",
            current_price=540.0,
            old_price=1000.0,
            source="mobiles",
        )

        decision = normal_decision()

        accepted = planner.prioritize(
            deal,
            decision,
            noon_probe_floor=45.0,
        )

        self.assertTrue(accepted)

        self.assertEqual(
            decision.lane,
            Lane.ULTRA,
        )

        self.assertLess(
            deal.discount_percent,
            50.0,
        )

    def test_ordinary_low_discount_is_not_hunter_candidate(self):
        planner = UltraHunterPlanner()

        deal = DealCandidate(
            store="amazon",
            external_id="B012345679",
            title="Ordinary Product",
            url="https://www.amazon.eg/dp/B012345679",
            current_price=800.0,
            old_price=1000.0,
            source="mobiles",
        )

        decision = normal_decision()

        accepted = planner.prioritize(
            deal,
            decision,
        )

        self.assertFalse(accepted)

        self.assertEqual(
            decision.lane,
            Lane.NORMAL,
        )


if __name__ == "__main__":
    unittest.main()
