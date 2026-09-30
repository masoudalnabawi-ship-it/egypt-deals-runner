from __future__ import annotations

from dataclasses import dataclass
import random
import time


@dataclass(frozen=True, slots=True)
class Surface:
    name: str
    category: str
    url: str
    priority: float = 1.0


class AdaptiveSurfaceSelector:
    """Balances exploitation with forced exploration and category diversity."""

    def __init__(self, surfaces: list[Surface], exploration_rate: float = 0.22):
        self.surfaces = list(surfaces)
        self.exploration_rate = exploration_rate
        self._cursor = 0

    def _weight(self, s: Surface, health: dict[str, dict]) -> float:
        h = health.get(s.name) or {}
        scans = max(0, int(h.get("scans") or 0))
        candidates = max(0, int(h.get("candidates") or 0))
        verified = max(0, int(h.get("verified") or 0))
        sent = max(0, int(h.get("sent") or 0))
        errors = max(0, int(h.get("consecutive_errors") or 0))
        last_success = int(h.get("last_success_at") or 0)

        yield_rate = (candidates + 1.5) / (scans + 3.0)
        quality_rate = (verified + sent * 1.5 + 1.0) / (candidates + 5.0)
        freshness = min(2.0, max(0.5, (time.time() - last_success) / 900.0)) if last_success else 2.0
        error_penalty = 1.0 / (1.0 + errors * 0.65)
        return max(0.05, s.priority * (0.50 + yield_rate) * (0.75 + quality_rate) * freshness * error_penalty)

    def pick(self, n: int, health: dict[str, dict]) -> list[Surface]:
        if not self.surfaces:
            return []
        n = min(max(1, n), len(self.surfaces))

        # Guaranteed exploration: round-robin items cannot starve forever.
        explore_n = max(1, round(n * self.exploration_rate))
        explored = []
        for _ in range(explore_n):
            explored.append(self.surfaces[self._cursor % len(self.surfaces)])
            self._cursor += 1

        remaining = [s for s in self.surfaces if s not in explored]
        chosen = list(explored)
        category_counts: dict[str, int] = {}
        for s in chosen:
            category_counts[s.category] = category_counts.get(s.category, 0) + 1

        while remaining and len(chosen) < n:
            weights = []
            for s in remaining:
                diversity = 0.35 if category_counts.get(s.category, 0) >= 2 else 1.0
                weights.append(self._weight(s, health) * diversity)
            selected = random.choices(remaining, weights=weights, k=1)[0]
            chosen.append(selected)
            category_counts[selected.category] = category_counts.get(selected.category, 0) + 1
            remaining.remove(selected)

        return chosen
