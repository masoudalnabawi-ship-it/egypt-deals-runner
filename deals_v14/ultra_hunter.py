from __future__ import annotations

from dataclasses import dataclass

from .discovery.scheduler import Surface
from .models import (
    DealCandidate,
    DealDecision,
    Lane,
)
from .source_brain import source_learning_weight


AMAZON_HOT_SOURCES = {
    "65off",
    "70off",
    "75off",
    "90off",
    "65filter",
    "70filter",
    "75filter",
    "90filter",
    "electronics_65hot",
    "appliances_65hot",
    "beauty_65hot",
    "fashion_65hot",
}


@dataclass(slots=True)
class HunterPlan:
    store: str
    surfaces: list[Surface]


class UltraHunterPlanner:
    """
    Fast candidate radar only.

    IMPORTANT:
    UltraHunter never approves a deal for Telegram.
    It only gives likely high-discount products priority in the
    live verification queue.

    Final routing requires verified Amazon discount >=65% inside V14Pipeline.
    """

    # Stable deal surfaces only.
    # Amazon percentage-filter URLs currently return no parseable
    # products, so they must not consume fixed Hunter capacity.
    # Highest-value Amazon discovery surfaces.
    # These run every Ultra Hunter cycle:
    # 1) Goldbox / Today's Deals
    # 2) Coupon-focused search
    # 3) Limited-time deals
    # 4) Clearance
    AMAZON_PRIMARY = (
        "goldbox",
        "limited_time",
        "clearance",
    )

    AMAZON_ROTATING = (
        "90off",
        "75off",
        "70off",
        "65off",
        "electronics_65hot",
        "appliances_65hot",
        "beauty_65hot",
        "fashion_65hot",
    )

    # Force non-fashion diversity.
    NOON_CORE = (
        "mobiles",
        "laptops",
        "appliances",
    )

    def __init__(self):
        self._cursor = {
            "amazon": 0,
            "noon": 0,
        }

    @staticmethod
    def _by_name(
        surfaces: list[Surface],
    ) -> dict[str, Surface]:
        return {
            surface.name: surface
            for surface in surfaces
        }

    @staticmethod
    def _unique(
        surfaces: list[Surface],
    ) -> list[Surface]:
        out = []
        seen = set()

        for surface in surfaces:
            if surface.name in seen:
                continue

            seen.add(surface.name)
            out.append(surface)

        return out

    def pick_surfaces(
        self,
        store: str,
        available: list[Surface],
        batch_size: int,
        health: dict[str, dict] | None = None,
    ) -> HunterPlan:
        store = str(store or "").lower()

        # Noon never enters the Ultra Hunter.
        if store == "noon":
            return HunterPlan(
                store=store,
                surfaces=[],
            )

        index = self._by_name(available)

        batch_size = max(
            3,
            int(batch_size or 3),
        )

        selected: list[Surface] = []

        if store == "amazon":
            # Dedicated percentage filters always run.
            for name in self.AMAZON_PRIMARY:
                surface = index.get(name)

                if surface is not None:
                    selected.append(surface)

            rotating_names = list(
                self.AMAZON_ROTATING
            )

            # Automatically include every Amazon category-specific
            # 65% radar. New categories added later require no Hunter edit.
            for surface in available:
                if (
                    surface.name.endswith("_65hot")
                    and surface.name
                    not in rotating_names
                ):
                    rotating_names.append(
                        surface.name
                    )

            rotating = [
                index[name]
                for name in rotating_names
                if name in index
            ]

        elif store == "noon":
            # Noon is completely separated from Ultra.
            # It remains on the normal Noon discovery path.
            return HunterPlan(
                store=store,
                surfaces=[],
            )

        else:
            return HunterPlan(
                store=store,
                surfaces=[],
            )

        # ==================================================
        # SMART LEARNING ROTATION
        #
        # 1) Guaranteed exploration:
        #    always rotate through a fresh category so the
        #    engine never becomes blind to quiet departments.
        #
        # 2) Learned exploitation:
        #    remaining slots prefer sources that historically
        #    produced useful, verified and reliable candidates.
        #
        # 3) Category diversity:
        #    one productive department cannot swallow the
        #    entire Amazon Ultra radar.
        # ==================================================
        health = health or {}

        cursor = self._cursor.get(store, 0)

        chosen_names = {
            surface.name
            for surface in selected
        }

        # Guaranteed exploration:
        # rotate through 3 fresh category radars per cycle.
        # This improves department coverage without increasing
        # the average Amazon request rate.
        exploration_slots = min(
            3,
            max(
                0,
                batch_size - len(selected),
            ),
        )

        explored = 0
        attempts = 0

        while (
            rotating
            and explored < exploration_slots
            and len(selected) < batch_size
            and attempts < len(rotating)
        ):
            explore = rotating[
                cursor % len(rotating)
            ]

            cursor += 1
            attempts += 1

            if explore.name in chosen_names:
                continue

            selected.append(explore)
            chosen_names.add(explore.name)
            explored += 1

        self._cursor[store] = cursor

        category_counts: dict[str, int] = {}

        for surface in selected:
            # Do not let the fixed global percentage filters
            # distort category diversity scoring.
            if surface.category == "global":
                continue

            category_counts[surface.category] = (
                category_counts.get(
                    surface.category,
                    0,
                )
                + 1
            )

        remaining = [
            surface
            for surface in rotating
            if surface.name not in chosen_names
        ]

        while (
            remaining
            and len(selected) < batch_size
        ):
            def smart_weight(
                surface: Surface,
            ) -> float:
                learned = source_learning_weight(
                    surface.priority,
                    health.get(
                        surface.name
                    ) or {},
                )

                count = category_counts.get(
                    surface.category,
                    0,
                )

                # Prefer category diversity while still
                # allowing excellent departments to win.
                if count >= 2:
                    diversity = 0.35
                elif count == 1:
                    diversity = 0.70
                else:
                    diversity = 1.0

                # Category-specific 65% radars get a small
                # focused boost over generic keyword pages.
                ultra_focus = (
                    1.12
                    if surface.name.endswith(
                        "_65hot"
                    )
                    else 1.0
                )

                return (
                    learned
                    * diversity
                    * ultra_focus
                )

            best = max(
                remaining,
                key=smart_weight,
            )

            selected.append(best)
            chosen_names.add(best.name)

            if best.category != "global":
                category_counts[
                    best.category
                ] = (
                    category_counts.get(
                        best.category,
                        0,
                    )
                    + 1
                )

            remaining.remove(best)

        return HunterPlan(
            store=store,
            surfaces=self._unique(selected),
        )

    @staticmethod
    def prioritize(
        deal: DealCandidate,
        decision: DealDecision,
        *,
        noon_probe_floor: float = 45.0,
    ) -> bool:
        """
        Evidence-driven Amazon Ultra fast verification.

        Source names are hints only.
        They never prove a 65% discount.

        - Noon -> never Ultra Hunter.
        - visible >=75% -> Ultra MAX.
        - visible 70-74.99% -> strong Ultra.
        - visible 65-69.99% -> Ultra.
        - promo/flash without proven 65% -> fast NORMAL probe.
        """

        store = str(deal.store or "").strip().lower()

        if store == "noon":
            decision.lane = Lane.NORMAL

            if "noon_normal_only" not in decision.reasons:
                decision.reasons.append(
                    "noon_normal_only"
                )

            return False

        if store != "amazon":
            return False

        discount = float(
            deal.discount_percent or 0
        )

        if discount >= 75.0:
            decision.lane = Lane.ULTRA
            decision.score = max(
                float(decision.score or 0),
                100.0,
            )

            if "amazon_ultra_max_75" not in decision.reasons:
                decision.reasons.append(
                    "amazon_ultra_max_75"
                )

            return True

        if discount >= 70.0:
            decision.lane = Lane.ULTRA
            decision.score = max(
                float(decision.score or 0),
                97.0,
            )

            if "amazon_ultra_70" not in decision.reasons:
                decision.reasons.append(
                    "amazon_ultra_70"
                )

            return True

        if discount >= 65.0:
            decision.lane = Lane.ULTRA
            decision.score = max(
                float(decision.score or 0),
                96.0,
            )

            if "amazon_ultra_65" not in decision.reasons:
                decision.reasons.append(
                    "amazon_ultra_65"
                )

            return True

        metadata = dict(
            deal.metadata or {}
        )

        promo = bool(
            metadata.get("promo_hint")
            or metadata.get("flash_hint")
        )

        # Real promotional evidence deserves quick verification,
        # but it is NOT Ultra until the live page proves >=65%.
        if promo:
            decision.lane = Lane.NORMAL
            decision.score = max(
                float(decision.score or 0),
                88.0,
            )

            if (
                "amazon_promo_fast_probe"
                not in decision.reasons
            ):
                decision.reasons.append(
                    "amazon_promo_fast_probe"
                )

            return True

        decision.lane = Lane.NORMAL
        return False
