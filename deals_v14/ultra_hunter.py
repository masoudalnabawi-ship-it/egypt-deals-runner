from __future__ import annotations

from dataclasses import dataclass

from .discovery.scheduler import Surface
from .models import (
    DealCandidate,
    DealDecision,
    Lane,
)


AMAZON_HOT_SOURCES = {
    "50off",
    "70off",
    "90off",
    "50filter",
    "70filter",
    "90filter",
    "electronics_50hot",
    "appliances_50hot",
    "beauty_50hot",
    "fashion_50hot",
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

    Final routing remains Strict50 inside V14Pipeline.
    """

    AMAZON_PRIMARY = (
        "90filter",
        "70filter",
        "50filter",
    )

    AMAZON_ROTATING = (
        "90off",
        "70off",
        "50off",
        "limited_time",
        "clearance",
        "electronics_50hot",
        "appliances_50hot",
        "beauty_50hot",
        "fashion_50hot",
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
    ) -> HunterPlan:
        store = str(store or "").lower()

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

            rotating = [
                index[name]
                for name in self.AMAZON_ROTATING
                if name in index
            ]

        elif store == "noon":
            # The previous engine could lean heavily toward Fashion.
            # V14 always hunts several strong non-fashion categories.
            for name in self.NOON_CORE:
                surface = index.get(name)

                if surface is not None:
                    selected.append(surface)

            core = set(self.NOON_CORE)

            rotating = [
                surface
                for surface in available
                if surface.name not in core
            ]

        else:
            return HunterPlan(
                store=store,
                surfaces=[],
            )

        cursor = self._cursor.get(store, 0)

        while (
            rotating
            and len(selected) < batch_size
        ):
            surface = rotating[
                cursor % len(rotating)
            ]

            selected.append(surface)
            cursor += 1

        self._cursor[store] = cursor

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
        Return True only when the candidate deserves the fast
        Ultra verification queue.

        This is NOT an Ultra acceptance decision.
        """

        discount = float(
            deal.discount_percent or 0
        )

        source = str(
            deal.source or ""
        ).lower()

        if deal.store == "amazon":
            # Amazon search cards often omit the list price.
            # Products coming from explicit 50/70/90 radars must
            # still get a fast live product-page verification.
            if source in AMAZON_HOT_SOURCES:
                decision.lane = Lane.ULTRA

                floor = 50.0

                if (
                    "70" in source
                    or "90" in source
                ):
                    floor = 70.0

                decision.score = max(
                    float(decision.score or 0),
                    100.0
                    if floor >= 70
                    else 95.0,
                )

                reason = (
                    "v14_ultra_hunter_amazon_"
                    f"{int(floor)}"
                )

                if reason not in decision.reasons:
                    decision.reasons.append(
                        reason
                    )

                return True

            if discount >= 50.0:
                decision.lane = Lane.ULTRA
                decision.score = max(
                    decision.score,
                    94.0,
                )

                if (
                    "v14_ultra_hunter_discount"
                    not in decision.reasons
                ):
                    decision.reasons.append(
                        "v14_ultra_hunter_discount"
                    )

                return True

            return False

        if deal.store == "noon":
            # Noon API/search prices are normally stronger than
            # generic cards. Start verifying slightly below 50
            # so rounding/variant changes cannot make us miss a
            # genuine live >=50% deal.
            probe_floor = min(
                49.9,
                max(
                    40.0,
                    float(noon_probe_floor),
                ),
            )

            if discount >= probe_floor:
                decision.lane = Lane.ULTRA

                decision.score = max(
                    decision.score,
                    96.0
                    if discount >= 50.0
                    else 91.0,
                )

                reason = (
                    "v14_ultra_hunter_noon_"
                    f"probe_{probe_floor:g}"
                )

                if reason not in decision.reasons:
                    decision.reasons.append(
                        reason
                    )

                return True

        return False
