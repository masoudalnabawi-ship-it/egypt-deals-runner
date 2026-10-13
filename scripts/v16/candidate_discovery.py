"""Pure, bounded candidate ranking for a future Amazon Egypt discovery pipeline.

No HTTP requests, scraping, D1 calls or Telegram sends are performed here.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable


@dataclass(frozen=True)
class Candidate:
    asin: str
    displayed_discount_pct: str
    category: str
    source: str
    last_checked_minutes_ago: int | None = None


def _discount(value: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('invalid discount') from exc
    if not result.is_finite() or result < 0 or result >= 100:
        raise ValueError('discount must be between 0 and less than 100')
    return result


def prioritize(candidates: Iterable[Candidate], *, limit: int = 100,
               per_category: int = 20) -> list[Candidate]:
    """Return at most `limit` deduplicated, priority-ranked candidates.

    All input candidates are already discovered elsewhere.  This function
    neither discovers new listings nor verifies advertised discounts.
    """
    if not 1 <= limit <= 1000 or not 1 <= per_category <= limit:
        raise ValueError('invalid limits')
    by_asin: dict[str, tuple[Candidate, Decimal]] = {}
    for item in candidates:
        if not isinstance(item.asin, str) or len(item.asin) != 10 or not item.asin.isalnum():
            continue
        try:
            discount = _discount(item.displayed_discount_pct)
        except ValueError:
            continue
        if discount < 5 or not item.category or not item.source:
            continue
        if item.last_checked_minutes_ago is not None and item.last_checked_minutes_ago < 0:
            continue
        previous = by_asin.get(item.asin)
        if previous is None or discount > previous[1]:
            by_asin[item.asin] = (item, discount)

    def sort_key(pair: tuple[Candidate, Decimal]):
        item, discount = pair
        # The urgent tier is always considered first, without price history.
        urgent = discount >= 50
        age = item.last_checked_minutes_ago
        return (-int(urgent), -discount, -(age if age is not None else 0), item.asin)

    ordered = sorted(by_asin.values(), key=sort_key)
    selected: list[Candidate] = []
    category_counts: dict[str, int] = {}
    for item, _ in ordered:
        if category_counts.get(item.category, 0) >= per_category:
            continue
        selected.append(item)
        category_counts[item.category] = category_counts.get(item.category, 0) + 1
        if len(selected) >= limit:
            break
    return selected
