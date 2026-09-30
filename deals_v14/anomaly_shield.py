from __future__ import annotations

from dataclasses import dataclass

from .identity import compatibility, signature
from .models import DealCandidate
from .price_intelligence import PriceProfile


@dataclass(frozen=True, slots=True)
class ShieldResult:
    hard_block: bool
    required_signals: int
    risk_score: float
    reasons: tuple[str, ...]


def inspect_deal(
    incoming: DealCandidate,
    verified: DealCandidate,
    verification_meta: dict,
    price_profile: PriceProfile | None = None,
) -> ShieldResult:

    reasons: list[str] = []
    risk = 0.0
    required_signals = 2
    hard_block = False

    signals = int(
        verification_meta.get(
            "verification_signals"
        )
        or 0
    )

    current = float(
        verified.current_price or 0
    )

    old = float(
        verified.old_price or 0
    )

    live_discount = (
        ((old - current) / old) * 100.0
        if old > current > 0
        else 0.0
    )

    # ========================================================
    # 1) PRODUCT IDENTITY
    # ========================================================

    compatible, mismatch = compatibility(
        signature(incoming.title),
        signature(verified.title),
    )

    if not compatible:
        hard_block = True
        risk = 100.0

        reasons.extend(
            f"identity_{reason}"
            for reason in mismatch
        )

    # ========================================================
    # 2) MARKET / CURRENCY SAFETY
    # ========================================================

    metadata = dict(
        verified.metadata or {}
    )

    currency = str(
        metadata.get("currency")
        or ""
    ).upper().strip()

    if currency and currency not in {
        "EGP",
        "LE",
        "L.E",
        "L.E.",
    }:
        hard_block = True
        risk = 100.0

        reasons.append(
            "wrong_market_currency"
        )

    if metadata.get("in_stock") is False:
        hard_block = True
        risk = 100.0

        reasons.append(
            "product_not_buyable"
        )

    # ========================================================
    # 3) DISCOVERY vs LIVE PRICE IDENTITY
    # ========================================================

    discovery_price = float(
        incoming.current_price or 0
    )

    if (
        discovery_price > 0
        and current > 0
    ):
        gap = abs(
            current - discovery_price
        ) / max(
            discovery_price,
            current,
            1.0,
        )

        if (
            gap >= 0.55
            and live_discount >= 50.0
        ):
            risk += 18.0
            required_signals = max(
                required_signals,
                3,
            )

            reasons.append(
                "large_discovery_live_price_gap"
            )

    # ========================================================
    # 4) HISTORICAL REFERENCE PRICE INFLATION
    # ========================================================

    if (
        price_profile is not None
        and price_profile.mature_history
        and price_profile.reference_price
    ):
        reference = float(
            price_profile.reference_price
        )

        history_drop = float(
            price_profile
            .drop_from_reference_pct
            or 0
        )

        # Example:
        # trusted historical price ≈ 1000
        # seller claims old price = 3000
        # live price = 900
        #
        # Visible discount looks 70%, but true historical
        # movement is only ~10%.
        if (
            old > reference * 2.25
            and history_drop < 20.0
        ):
            hard_block = True
            risk = 100.0

            reasons.append(
                "inflated_reference_price"
            )

        elif (
            old > reference * 1.65
            and history_drop < 12.0
        ):
            risk += 30.0

            required_signals = max(
                required_signals,
                3,
            )

            reasons.append(
                "suspicious_old_price_vs_history"
            )

        # Huge live collapse compared with mature history
        # needs one more independent signal.
        if (
            current < reference * 0.18
            and not price_profile.strong_history_signal
        ):
            risk += 25.0

            required_signals = max(
                required_signals,
                3,
            )

            reasons.append(
                "extreme_current_vs_history"
            )

    # ========================================================
    # 5) EXTREME LIVE DISCOUNT
    # ========================================================

    amazon_savings = float(
        verification_meta.get(
            "amazon_savings_percent"
        )
        or 0
    )

    direct_amazon_confirmation = bool(
        verified.store == "amazon"
        and amazon_savings >= 70.0
        and abs(
            amazon_savings
            - live_discount
        ) <= 4.0
    )

    strong_history = bool(
        price_profile
        and price_profile
        .strong_history_signal
    )

    if live_discount >= 80.0:
        if not (
            direct_amazon_confirmation
            or strong_history
            or signals >= 3
        ):
            required_signals = max(
                required_signals,
                3,
            )

            risk += 25.0

            reasons.append(
                "extreme_discount_needs_extra_confirmation"
            )

    if live_discount >= 95.0:
        required_signals = max(
            required_signals,
            3,
        )

        risk += 15.0

        reasons.append(
            "ultra_extreme_ratio"
        )

    # ========================================================
    # FINAL
    # ========================================================

    risk = round(
        min(100.0, max(0.0, risk)),
        2,
    )

    return ShieldResult(
        hard_block=hard_block,
        required_signals=required_signals,
        risk_score=risk,
        reasons=tuple(
            dict.fromkeys(reasons)
        ),
    )
