"""Amazon V15 competitor discovery processor.

Discovery signals never authorize Telegram publication.
"""

from dataclasses import dataclass

from scripts.v15.competitor_intelligence import (
    SourcePerformance,
    source_reliability,
    discovery_priority,
)


@dataclass(frozen=True)
class CompetitorSignal:
    asin: str
    source: str
    age_minutes: float


def process_competitor_signal(
    signal,
    memory,
    performance,
    independent_sources=None,
):
    """Store a discovery and calculate verification priority."""

    memory.discover(signal.asin, signal.source)

    reliability = source_reliability(performance)

    count = memory.source_count(signal.asin)

    if independent_sources is not None:
        count = max(count, independent_sources)

    priority = discovery_priority(
        reliability=reliability,
        age_minutes=signal.age_minutes,
        independent_sources=count,
    )

    return {
        "asin": signal.asin.strip().upper(),
        "source": signal.source,
        "verification_priority": priority,
        "status": "pending_verification",
        "publish_allowed": False,
    }
