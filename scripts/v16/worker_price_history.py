"""V16 persistent price history through its authenticated Worker."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from cloud_dedup import request


def cents(price):
    try:
        value = Decimal(str(price))
        if not value.is_finite() or value <= 0:
            raise ValueError("INVALID_PRICE")
        return int(
            (value * 100).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("INVALID_PRICE") from exc


def record_price(asin, price):
    result = request("/prices/record", {
        "asin": asin,
        "price_cents": cents(price),
    })
    if result.get("ok") is not True:
        raise RuntimeError("V16_PRICE_RECORD_FAILED")
    return True


def historical_discount(asin, current_price, min_age_days=7):
    if min_age_days != 7:
        raise ValueError("UNSUPPORTED_HISTORY_WINDOW")

    result = request("/prices/history", {
        "asin": asin,
        "price_cents": cents(current_price),
    })

    if result.get("verified") is False:
        return None

    if result.get("verified") is not True or result.get("asin") != asin:
        raise RuntimeError("INVALID_PRICE_HISTORY_RESPONSE")

    previous = result.get("previous_price_cents")
    if type(previous) is not int or previous <= cents(current_price):
        raise RuntimeError("INVALID_HISTORICAL_PRICE")

    discount = (
        Decimal(previous - cents(current_price))
        * 100 / Decimal(previous)
    )

    if discount < 70:
        return None

    return {
        "asin": asin,
        "status": "verified",
        "source_type": "independent_price_history",
        "source_reference": "v16_worker_d1_history",
        "observed_at": "historical_observation_7_days_or_older",
        "historical_price": str(Decimal(previous) / 100),
        "verified_discount_pct": str(discount),
    }
