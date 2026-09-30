from __future__ import annotations

from dataclasses import dataclass
import math
import statistics


@dataclass(frozen=True, slots=True)
class PriceProfile:
    samples: int = 0
    unique_prices: int = 0

    min_price: float | None = None
    max_price: float | None = None
    median_price: float | None = None
    mean_price: float | None = None
    reference_price: float | None = None

    drop_from_reference_pct: float = 0.0
    drop_from_median_pct: float = 0.0

    price_percentile: float = 100.0

    new_verified_low: bool = False
    near_historical_low: bool = False
    mature_history: bool = False
    strong_history_signal: bool = False


def _pct_drop(reference: float, current: float) -> float:
    if reference <= current or current <= 0:
        return 0.0

    value = ((reference - current) / reference) * 100.0

    return round(
        max(0.0, min(99.0, value)),
        2,
    )


def build_price_profile(
    history: list[float] | None,
    current: float,
) -> PriceProfile:
    try:
        current = float(current or 0)
    except Exception:
        current = 0.0

    clean = []

    for value in history or []:
        try:
            price = float(value)
        except Exception:
            continue

        if (
            price > 0
            and math.isfinite(price)
        ):
            clean.append(price)

    if current <= 0 or not clean:
        return PriceProfile(
            samples=len(clean),
            unique_prices=len(
                {round(x, 2) for x in clean}
            ),
        )

    # Keep recent trusted observations only.
    clean = clean[:60]

    samples = len(clean)

    unique_prices = len(
        {round(x, 2) for x in clean}
    )

    minimum = min(clean)
    maximum = max(clean)
    median = float(statistics.median(clean))
    mean = float(statistics.fmean(clean))

    # Robust reference:
    # median is resistant to one fake/inflated old price.
    reference = median if samples >= 3 else None

    drop_ref = (
        _pct_drop(reference, current)
        if reference
        else 0.0
    )

    drop_median = _pct_drop(
        median,
        current,
    )

    lower_or_equal = sum(
        1
        for price in clean
        if price <= current * 1.002
    )

    percentile = round(
        lower_or_equal / samples * 100.0,
        1,
    )

    new_low = (
        samples >= 2
        and current < minimum * 0.995
    )

    near_low = (
        samples >= 2
        and current <= minimum * 1.02
    )

    mature = (
        samples >= 5
        and unique_prices >= 2
    )

    # History can become an independent verification clue,
    # but only when there are several trusted observations
    # and the current price is materially below the robust baseline.
    strong_signal = bool(
        mature
        and (
            drop_ref >= 20.0
            or new_low
        )
        and percentile <= 25.0
    )

    return PriceProfile(
        samples=samples,
        unique_prices=unique_prices,
        min_price=round(minimum, 2),
        max_price=round(maximum, 2),
        median_price=round(median, 2),
        mean_price=round(mean, 2),
        reference_price=(
            round(reference, 2)
            if reference
            else None
        ),
        drop_from_reference_pct=drop_ref,
        drop_from_median_pct=drop_median,
        price_percentile=percentile,
        new_verified_low=new_low,
        near_historical_low=near_low,
        mature_history=mature,
        strong_history_signal=strong_signal,
    )
