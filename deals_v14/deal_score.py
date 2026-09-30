from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from .price_intelligence import PriceProfile


@dataclass(frozen=True, slots=True)
class DealScoreBreakdown:
    discount_strength: float
    evidence_quality: float
    historical_rarity: float
    market_advantage: float
    absolute_value: float
    urgency: float
    anomaly_quality: float
    coupon_value: float
    penalties: float
    total: float

    def to_dict(self):
        return asdict(self)


def smart_deal_score(
    *,
    real_discount: float,
    confidence: float,
    verification_signals: int,
    effective_price: float,
    old_price: float,
    market_advantage_pct: float,
    price_profile: PriceProfile | None,
    flash: bool,
    coupon_percent: float,
    anomaly: bool,
    accessory_like: bool,
    impossible_ratio: bool,
) -> DealScoreBreakdown:

    discount = min(
        30.0,
        max(0.0, real_discount) * 0.50,
    )

    evidence = min(
        20.0,
        max(0.0, confidence) * 14.0
        + min(
            6.0,
            max(0, verification_signals) * 3.0,
        ),
    )

    history = 0.0

    if price_profile is not None:
        history += min(
            10.0,
            max(
                0.0,
                price_profile.drop_from_reference_pct,
            ) * 0.18,
        )

        if price_profile.new_verified_low:
            history += 3.0

        if price_profile.strong_history_signal:
            history += 2.0

    history = min(15.0, history)

    market = min(
        10.0,
        max(0.0, market_advantage_pct) * 0.22,
    )

    saving = (
        max(0.0, old_price - effective_price)
        if old_price > effective_price > 0
        else 0.0
    )

    value = min(
        10.0,
        math.log10(saving + 1.0) * 2.5
        if saving > 0
        else 0.0,
    )

    urgency = 5.0 if flash else 0.0

    anomaly_score = (
        5.0
        if anomaly and confidence >= 0.85
        else 0.0
    )

    coupon = min(
        5.0,
        max(0.0, coupon_percent) * 0.10,
    )

    penalties = 0.0

    if accessory_like and anomaly:
        penalties += 8.0

    if (
        impossible_ratio
        and verification_signals < 2
        and not (
            price_profile
            and price_profile.strong_history_signal
        )
    ):
        penalties += 12.0

    total = (
        discount
        + evidence
        + history
        + market
        + value
        + urgency
        + anomaly_score
        + coupon
        - penalties
    )

    total = round(
        max(0.0, min(100.0, total)),
        2,
    )

    return DealScoreBreakdown(
        discount_strength=round(discount, 2),
        evidence_quality=round(evidence, 2),
        historical_rarity=round(history, 2),
        market_advantage=round(market, 2),
        absolute_value=round(value, 2),
        urgency=round(urgency, 2),
        anomaly_quality=round(anomaly_score, 2),
        coupon_value=round(coupon, 2),
        penalties=round(penalties, 2),
        total=total,
    )
