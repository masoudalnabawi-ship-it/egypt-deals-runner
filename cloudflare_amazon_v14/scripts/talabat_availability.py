"""Talabat storefront's reported availability, not physical quantity verification."""
import math


def reported_stock(item):
    """Return (quantity-or-True/False-or-None, source).

    True/False represents *only* inStock's storefront availability indicator,
    never a claimed number of units. Do not claim cart/delivery verification.
    Numeric stockAmount takes priority unless inStock is explicitly False.
    """
    if item.get('inStock') is False:
        return False, 'inStock_boolean'
    raw = item.get('stockAmount')
    if raw is not None and raw != '' and not isinstance(raw, bool):
        try:
            val = float(raw)
            if math.isfinite(val):
                return max(0.0, val), 'stockAmount'
        except (TypeError, ValueError, OverflowError):
            pass
    if item.get('inStock') is True:
        return True, 'inStock_boolean'
    return None, 'unknown'
