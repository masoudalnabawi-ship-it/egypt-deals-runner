"""V15: private review for significant observed price drops only."""
from decimal import Decimal
from flash_dedup import initialize, send_once
from flash_private_alert import send


def review(report, previous_price):
    obs = report.get("observation") or {}
    asin = report.get("asin", "")

    if obs.get("page_asin") != asin:
        return "INVALID_PAGE"

    current = Decimal(str(obs["current_price"]))
    previous = Decimal(str(previous_price))

    if not all(x.is_finite() and x > 0 for x in (current, previous)):
        return "INVALID_PRICE"

    if current * 100 > previous * 90:
        return "NO_SIGNIFICANT_DROP"

    candidate = {
        "asin": asin,
        "current_price": str(current),
        "title": obs.get("title") or "منتج على أمازون مصر",
        "review_type": "PRICE_ONLY",
        "publication_allowed": False,
    }

    initialize()
    return send_once(candidate, send)
