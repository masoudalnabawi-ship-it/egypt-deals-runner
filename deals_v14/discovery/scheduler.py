from __future__ import annotations

from dataclasses import dataclass
import random

from ..source_brain import (
    source_learning_weight,
)


@dataclass(frozen=True, slots=True)
class Surface:
    name: str
    category: str
    url: str
    priority: float = 1.0


class AdaptiveSurfaceSelector:
    """
    V14 self-learning radar.

    Balances:
    - production quality
    - verification success
    - usefulness
    - reliability
    - speed
    - category diversity
    - guaranteed exploration
    """

    def __init__(
        self,
        surfaces: list[Surface],
        exploration_rate: float = 0.22,
    ):
        self.surfaces = list(surfaces)
        self.exploration_rate = (
            exploration_rate
        )
        self._cursor = 0

    def _weight(
        self,
        surface: Surface,
        health: dict[str, dict],
    ) -> float:
        return source_learning_weight(
            surface.priority,
            health.get(surface.name) or {},
        )

    def pick(
        self,
        n: int,
        health: dict[str, dict],
    ) -> list[Surface]:

        if not self.surfaces:
            return []

        n = min(
            max(1, n),
            len(self.surfaces),
        )

        # ----------------------------------------------------
        # Guaranteed exploration
        # ----------------------------------------------------
        explore_n = max(
            1,
            round(
                n
                * self.exploration_rate
            ),
        )

        explored = []

        for _ in range(explore_n):
            surface = self.surfaces[
                self._cursor
                % len(self.surfaces)
            ]

            explored.append(surface)

            self._cursor += 1

        remaining = [
            surface
            for surface in self.surfaces
            if surface not in explored
        ]

        chosen = list(explored)

        category_counts: dict[
            str,
            int,
        ] = {}

        for surface in chosen:
            category_counts[
                surface.category
            ] = (
                category_counts.get(
                    surface.category,
                    0,
                )
                + 1
            )

        # ----------------------------------------------------
        # Learned exploitation
        # ----------------------------------------------------
        while (
            remaining
            and len(chosen) < n
        ):
            weights = []

            for surface in remaining:
                learned = self._weight(
                    surface,
                    health,
                )

                # Prevent one productive category from
                # swallowing the whole radar.
                count = category_counts.get(
                    surface.category,
                    0,
                )

                if count >= 2:
                    diversity = 0.32

                elif count == 1:
                    diversity = 0.72

                else:
                    diversity = 1.0

                weights.append(
                    max(
                        0.01,
                        learned
                        * diversity,
                    )
                )

            selected = random.choices(
                remaining,
                weights=weights,
                k=1,
            )[0]

            chosen.append(selected)

            category_counts[
                selected.category
            ] = (
                category_counts.get(
                    selected.category,
                    0,
                )
                + 1
            )

            remaining.remove(selected)

        return chosen
