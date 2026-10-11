"""Amazon V15 competitor source intelligence.

Competitor data is discovery evidence only.
Amazon verification remains mandatory.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourcePerformance:
    discovered: int
    verified: int
    rejected: int


def source_reliability(stats: SourcePerformance) -> float:
    """Smoothed reliability score from 0.0 to 1.0."""
    if min(stats.discovered, stats.verified, stats.rejected) < 0:
        raise ValueError("Negative counters are invalid")

    if stats.verified + stats.rejected > stats.discovered:
        raise ValueError("Outcomes exceed discoveries")

    # Bayesian smoothing prevents new sources from scoring 100%.
    return (stats.verified + 2) / (
        stats.verified + stats.rejected + 4
    )


def discovery_priority(
    reliability: float,
    age_minutes: float,
    independent_sources: int,
) -> float:
    """Rank candidates for verification, not publication."""
    if not 0 <= reliability <= 1:
        raise ValueError("Invalid reliability")
    if age_minutes < 0 or independent_sources < 1:
        raise ValueError("Invalid candidate data")

    freshness = 1 / (1 + age_minutes / 60)
    corroboration = min(independent_sources, 5) / 5

    return round(
        100 * (
            0.55 * reliability
            + 0.30 * freshness
            + 0.15 * corroboration
        ),
        2,
    )
