from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass(frozen=True, slots=True)
class SourceBrainScore:
    weight: float
    candidate_yield: float
    verification_quality: float
    publish_quality: float
    reliability: float
    latency_factor: float
    exploration_boost: float
    freshness_boost: float


def evaluate_source(
    base_priority: float,
    health: dict | None,
    *,
    now: int | None = None,
) -> SourceBrainScore:
    """
    Learn source quality from real production results.

    Strong sources:
    - consistently discover candidates
    - candidates survive verification
    - verified deals reach review delivery
    - low error rate
    - acceptable latency

    Important:
    New/under-tested sources still receive exploration boost,
    so the system cannot permanently lock itself into old sources.
    """

    h = health or {}

    now = int(
        now
        if now is not None
        else time.time()
    )

    scans = max(
        0,
        int(h.get("scans") or 0),
    )

    candidates = max(
        0,
        int(h.get("candidates") or 0),
    )

    verified = max(
        0,
        int(h.get("verified") or 0),
    )

    sent = max(
        0,
        int(h.get("sent") or 0),
    )

    errors = max(
        0,
        int(h.get("errors") or 0),
    )

    consecutive_errors = max(
        0,
        int(
            h.get("consecutive_errors")
            or 0
        ),
    )

    latency_ms = max(
        0,
        int(
            h.get("last_latency_ms")
            or 0
        ),
    )

    last_success = max(
        0,
        int(
            h.get("last_success_at")
            or 0
        ),
    )

    # --------------------------------------------------------
    # 1) Candidate yield
    #
    # ~12 useful candidates per scan is considered strong.
    # Capped so a huge search page cannot dominate the brain.
    # --------------------------------------------------------
    if scans > 0:
        candidates_per_scan = (
            candidates / scans
        )
    else:
        candidates_per_scan = 0.0

    candidate_yield = min(
        1.0,
        candidates_per_scan / 12.0,
    )

    # --------------------------------------------------------
    # 2) Verification quality
    #
    # Bayesian smoothing protects against tiny samples.
    # --------------------------------------------------------
    verification_quality = min(
        1.0,
        (verified + 1.0)
        / (candidates + 8.0),
    )

    # --------------------------------------------------------
    # 3) Publish/review quality
    #
    # A source producing verified but never useful deals
    # should not dominate forever.
    # --------------------------------------------------------
    publish_quality = min(
        1.0,
        (sent + 0.5)
        / (verified + 3.0),
    )

    # --------------------------------------------------------
    # 4) Reliability
    # --------------------------------------------------------
    if scans > 0:
        error_rate = min(
            1.0,
            errors / scans,
        )
    else:
        error_rate = 0.0

    reliability = max(
        0.15,
        1.0 - error_rate * 0.80,
    )

    # Repeated consecutive failures get stronger penalty.
    reliability *= (
        1.0
        / (
            1.0
            + consecutive_errors * 0.75
        )
    )

    reliability = max(
        0.08,
        min(1.0, reliability),
    )

    # --------------------------------------------------------
    # 5) Latency
    #
    # First ~1 second gets no penalty.
    # Slow sources remain usable, just less preferred.
    # --------------------------------------------------------
    if latency_ms <= 1000:
        latency_factor = 1.0
    else:
        latency_factor = max(
            0.55,
            1.0
            / (
                1.0
                + (
                    latency_ms - 1000
                )
                / 5000.0
            ),
        )

    # --------------------------------------------------------
    # 6) Exploration
    #
    # Under-tested sources receive a limited boost.
    # --------------------------------------------------------
    exploration_boost = (
        1.0
        + max(
            0,
            5 - scans,
        )
        * 0.04
    )

    # --------------------------------------------------------
    # 7) Freshness
    #
    # Successful sources not checked successfully for a while
    # receive a small second chance.
    # --------------------------------------------------------
    if last_success <= 0:
        freshness_boost = 1.05
    else:
        age = max(
            0,
            now - last_success,
        )

        freshness_boost = (
            1.0
            + min(
                0.15,
                age
                / 21600.0
                * 0.15,
            )
        )

    # --------------------------------------------------------
    # Combined learning score
    #
    # Verification and usefulness matter more than raw volume.
    # --------------------------------------------------------
    quality = (
        0.55
        + candidate_yield * 0.90
        + verification_quality * 1.50
        + publish_quality * 1.00
    )

    weight = (
        max(
            0.05,
            float(base_priority or 1.0),
        )
        * quality
        * reliability
        * latency_factor
        * exploration_boost
        * freshness_boost
    )

    weight = round(
        max(0.05, weight),
        5,
    )

    return SourceBrainScore(
        weight=weight,
        candidate_yield=round(
            candidate_yield,
            4,
        ),
        verification_quality=round(
            verification_quality,
            4,
        ),
        publish_quality=round(
            publish_quality,
            4,
        ),
        reliability=round(
            reliability,
            4,
        ),
        latency_factor=round(
            latency_factor,
            4,
        ),
        exploration_boost=round(
            exploration_boost,
            4,
        ),
        freshness_boost=round(
            freshness_boost,
            4,
        ),
    )


def source_learning_weight(
    base_priority: float,
    health: dict | None,
) -> float:
    return evaluate_source(
        base_priority,
        health,
    ).weight
