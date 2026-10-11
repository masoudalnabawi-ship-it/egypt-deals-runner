"""Amazon V15 verified price decision engine."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from scripts.v15.routing import route_amazon_review


@dataclass(frozen=True)
class VerifiedPrice:
    asin: str
    current_price: object
    reference_price: object
    verified: bool
    reference_trusted: bool


def money(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid price")

    if not result.is_finite() or result <= 0:
        raise ValueError("Price must be positive")

    return result


def evaluate_price(data: VerifiedPrice):
    """Calculate discount only from trusted verified prices."""

    if data.verified is not True:
        return {
            "status": "unverified",
            "publish_allowed": False,
        }

    if data.reference_trusted is not True:
        return {
            "status": "untrusted_reference",
            "publish_allowed": False,
        }

    try:
        current = money(data.current_price)
        reference = money(data.reference_price)
    except ValueError:
        return {
            "status": "invalid_price",
            "publish_allowed": False,
        }

    if current >= reference:
        return {
            "status": "no_discount",
            "publish_allowed": False,
        }

    discount = (
        (reference - current) * Decimal("100") / reference
    )

    route = route_amazon_review(discount, True)

    return {
        "status": "verified",
        "asin": data.asin,
        "current_price": str(current),
        "reference_price": str(reference),
        "discount": str(
            discount.quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        ),
        "route": route,
        "publish_allowed": route in ("normal", "ultra"),
    }
