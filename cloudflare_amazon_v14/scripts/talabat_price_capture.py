"""Extract storefront price observations separately from availability or discount claims.

This is a display-price archive, NOT proof of stock, cart total or market value.
"""
import math
import re

_TOKEN = re.compile(r'[A-Za-z0-9_-]{1,90}\Z')


def _number(value):
    """Parse usual storefront numeric values, without guessing currency conversion."""
    if isinstance(value, bool):
        return None
    if isinstance(value, dict):
        for key in ('value', 'amount', 'current', 'final', 'price'):
            if key in value:
                result = _number(value[key])
                if result is not None:
                    return result
        return None
    try:
        v = float(str(value).strip().replace(',', ''))
        return v if math.isfinite(v) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _first_number(item, keys):
    for key in keys:
        n = _number(item.get(key))
        if n is not None:
            return n
    return None


def _identity(item):
    for name in ('sku', 'SKU', 'productSku', 'itemSku', 'productCode'):
        value = item.get(name)
        if isinstance(value, (str, int)):
            s = str(value).strip()
            if _TOKEN.fullmatch(s):
                return s
    # Stable product ID fallback for items without SKU. Keep a distinct namespace.
    for name in ('productId', 'id'):
        value = item.get(name)
        if isinstance(value, (str, int)):
            s = str(value).strip()
            if _TOKEN.fullmatch(s) and len(s) <= 85:
                return 'pid_' + s
    return None


def capture_price_observation(item, branch_id, timestamp, stats=None):
    """Return snapshot or None. Never require stock>0 just to observe a visible price."""
    if stats is not None:
        stats['items_seen'] += 1
    if not isinstance(item, dict):
        if stats is not None:
            stats['invalid_item'] += 1
        return None
    sku = _identity(item)
    if not sku:
        if stats is not None:
            stats['missing_stable_id'] += 1
        return None
    if stats is not None:
        stats['with_identifier'] += 1

    price = _first_number(item, ('price', 'sellingPrice', 'salePrice', 'currentPrice', 'finalPrice'))
    if price is None or not (0 < price <= 1000000):
        if stats is not None:
            stats['missing_positive_price'] += 1
        return None

    stock = _first_number(item, ('stockAmount', 'availableStock', 'stockQuantity', 'quantityAvailable'))
    if stock is None:
        availability = 'unknown'
    elif stock > 0:
        availability = 'in_stock_reported'
    else:
        availability = 'out_of_stock_reported'
    if stats is not None:
        stats['recorded'] += 1
        stats[availability] += 1

    original = _first_number(item, ('originalPrice', 'listPrice', 'regularPrice'))
    original = round(original, 2) if original is not None and 0 < original < 1000000 else None
    return {
        'branch_id': str(branch_id), 'sku': sku,
        'title': str(item.get('title') or item.get('name') or '')[:200],
        'price': round(price, 2),
        'displayed_original_price': original,
        'observed_at': int(timestamp),
        'stock_status': availability,  # informational only; API stores displayed price
    }
