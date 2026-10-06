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

    def test_amazon_reliable_promo_surfaces_are_always_selected(self):
        planner = UltraHunterPlanner()

        available = [
            surface("mobiles"),
            surface("50filter"),
            surface("65filter"),
            surface("70filter"),
            surface("75filter"),
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

        self.assertIn("limited_time", names)
        self.assertIn("clearance", names)

        # Broken percentage-filter URLs are no longer mandatory.
        self.assertNotIn("65filter", UltraHunterPlanner.AMAZON_PRIMARY)
        self.assertNotIn("70filter", UltraHunterPlanner.AMAZON_PRIMARY)
        self.assertNotIn("75filter", UltraHunterPlanner.AMAZON_PRIMARY)
        self.assertNotIn("90filter", UltraHunterPlanner.AMAZON_PRIMARY)

    def test_noon_has_no_ultra_hunter_surfaces(self):
        planner = UltraHunterPlanner()

        available = [
            surface("mobiles", "mobiles"),
            surface("laptops", "computers"),
            surface("appliances", "appliances"),
            surface("beauty", "beauty"),
        ]

        plan = planner.pick_surfaces(
            "noon",
            available,
            5,
        )

        self.assertEqual(
            plan.surfaces,
            [],
        )

    def test_amazon_65_filter_without_discount_evidence_is_not_ultra(self):
        planner = UltraHunterPlanner()

        deal = DealCandidate(
            store="amazon",
            external_id="B065FILTER1",
            title="Amazon 65 Filter Product",
            url="https://www.amazon.eg/dp/B065FILTER1",
            current_price=500.0,
            old_price=None,
            source="65filter",
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

    def test_noon_never_enters_ultra_even_with_90_percent(self):
        planner = UltraHunterPlanner()

        deal = DealCandidate(
            store="noon",
            external_id="N90TEST001",
            title="Noon Huge Discount",
            url="https://www.noon.com/egypt-en/x/N90TEST001/p/",
            current_price=100.0,
            old_price=1000.0,
            source="mobiles",
        )

        decision = normal_decision()

        accepted = planner.prioritize(
            deal,
            decision,
            noon_probe_floor=45.0,
        )

        self.assertFalse(accepted)
        self.assertEqual(
            decision.lane,
            Lane.NORMAL,
        )
        self.assertIn(
            "noon_normal_only",
            decision.reasons,
        )

    def test_amazon_64_percent_is_not_ultra(self):
        planner = UltraHunterPlanner()

        deal = DealCandidate(
            store="amazon",
            external_id="B064TEST01",
            title="Amazon 64 Percent",
            url="https://www.amazon.eg/dp/B064TEST01",
            current_price=360.0,
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

    def test_amazon_exactly_65_percent_enters_ultra(self):
        planner = UltraHunterPlanner()

        deal = DealCandidate(
            store="amazon",
            external_id="B065TEST01",
            title="Amazon Exactly 65 Percent",
            url="https://www.amazon.eg/dp/B065TEST01",
            current_price=350.0,
            old_price=1000.0,
            source="mobiles",
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
            96.0,
        )

    def test_amazon_75_percent_gets_max_priority(self):
        planner = UltraHunterPlanner()

        deal = DealCandidate(
            store="amazon",
            external_id="B075TEST01",
            title="Amazon 75 Percent",
            url="https://www.amazon.eg/dp/B075TEST01",
            current_price=250.0,
            old_price=1000.0,
            source="mobiles",
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
        self.assertEqual(
            decision.score,
            100.0,
        )

    def test_ordinary_low_discount_is_not_hunter_candidate(self):
        planner = UltraHunterPlanner()

        deal = DealCandidate(
            store="amazon",
            external_id="B020TEST01",
            title="Ordinary Product",
            url="https://www.amazon.eg/dp/B020TEST01",
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
