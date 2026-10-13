"""Pure Flash Hunter alert policy, ready for future transport integration.

No HTTP, database, or Telegram calls. A caller must persist deduplication
and perform the actual send; in-memory state here is only a testable model.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class FlashOffer:
    asin: str
    title: str
    price_egp: str
    displayed_discount_pct: str
    url: str


def prepare_private_alert(offer: FlashOffer) -> dict | None:
    """Return an urgent alert for 50 <= advertised discount < 100.

    Historical price verification is deliberately NOT required. A clearly
    marked unverified advertised discount must not be presented as proven.
    """
    if not isinstance(offer.asin, str) or len(offer.asin) != 10 or not offer.asin.isalnum():
        raise ValueError('invalid ASIN')
    if not isinstance(offer.title, str) or not offer.title.strip():
        raise ValueError('missing title')
    if not isinstance(offer.url, str) or not offer.url.startswith('https://www.amazon.eg/'):
        raise ValueError('invalid Amazon Egypt URL')
    try:
        pct = Decimal(str(offer.displayed_discount_pct))
        price = Decimal(str(offer.price_egp))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('invalid numeric input') from exc
    if not pct.is_finite() or not price.is_finite() or price <= 0 or pct < 0 or pct >= 100:
        raise ValueError('invalid price or discount')
    if pct < 50:
        return None
    tier = 'FLASH' if pct >= 90 else 'SUPER_ULTRA' if pct >= 70 else 'ULTRA'
    message = (f'🚨 عرض عاجل | {tier}\n'
               f'{offer.title.strip()}\n'
               f'💰 السعر الحالي: {price} جنيه\n'
               f'🔥 الخصم المعلن: {pct}%\n'
               '⚠️ الخصم معلن ولم يُتحقق من السعر التاريخي بعد.\n'
               f'🔗 {offer.url}')
    return {'asin': offer.asin.upper(), 'tier': tier, 'private_only': True,
            'verified_historical_price': False, 'message': message,
            'dedupe_key': f'{offer.asin.upper()}:{price}:{pct}'}


class LocalDeduplicator:
    """Demonstration-only dedupe; NOT persistent or multi-worker safe."""
    def __init__(self):
        self._seen = set()

    def should_send(self, alert: dict) -> bool:
        key = alert['dedupe_key']
        if key in self._seen:
            return False
        self._seen.add(key)
        return True
