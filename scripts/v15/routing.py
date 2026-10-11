"""Amazon V15: verified discount routing."""

from decimal import Decimal, InvalidOperation


def route_amazon_review(discount, verified):
    if verified is not True:
        return "reject"

    try:
        value = Decimal(str(discount))
    except (InvalidOperation, ValueError, TypeError):
        return "reject"

    if not value.is_finite() or not 0 <= value <= 100:
        return "reject"

    return "ultra" if value >= 50 else "normal"
