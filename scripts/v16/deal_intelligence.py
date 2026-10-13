"""V16 experimental deal scoring. Does not send alerts or touch production."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class Deal:
    asin: str
    current_price: str
    displayed_discount_pct: str
    historical_low: str | None = None
    in_stock: bool | None = None


def evaluate(deal: Deal) -> dict:
    if not (len(deal.asin) == 10 and deal.asin.isalnum()):
        raise ValueError('invalid ASIN')
    try:
        price = Decimal(deal.current_price)
        discount = Decimal(deal.displayed_discount_pct)
        low = Decimal(deal.historical_low) if deal.historical_low is not None else None
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('invalid numeric input') from exc
    if not price.is_finite() or price <= 0 or not discount.is_finite() or not 0 <= discount < 100:
        raise ValueError('invalid price or discount')
    if low is not None and (not low.is_finite() or low <= 0):
        raise ValueError('invalid historical low')
    # A displayed 50-99% discount must be alerted privately immediately,
    # irrespective of the historical verification result.
    urgent_private = discount >= 50
    discount_points = min(25, int(discount * Decimal('0.25')))
    history_points = 0 if low is None else (30 if price < low else 15 if price == low else 0)
    stock_points = 15 if deal.in_stock is True else 0
    # Unknown history and stock are not treated as verified evidence.
    score = discount_points + history_points + stock_points
    return {
        'asin': deal.asin,
        'score': score,
        'score_max': 70,
        'urgent_private_alert': urgent_private,
        'historical_verification': 'unknown' if low is None else ('new_low' if price < low else 'equal_low' if price == low else 'above_low'),
        'stock_verification': 'unknown' if deal.in_stock is None else ('available' if deal.in_stock else 'unavailable'),
        'displayed_discount_pct': str(discount),
        'current_price': str(price),
    }
