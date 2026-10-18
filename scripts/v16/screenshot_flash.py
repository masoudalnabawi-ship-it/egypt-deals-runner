"""V16: private advertised-discount alert with authentic screenshot when ready.

Caller supplies a real Amazon observation; this module does not discover deals.
No historical-price checks. No screenshot fabrication. Telegram requires opt-in.
"""
import hashlib
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

V15 = Path(__file__).resolve().parents[1] / 'v15'
if str(V15) not in sys.path:
    sys.path.insert(0, str(V15))


# Exclude only clearly identifiable book products; do not exclude notebooks,
# bookcases, stationery or unrelated products containing "book" in their names.
BOOK_PRODUCTS = re.compile(
    r'(?i)(?:\b(?:novels?|ebooks?|e-books?|kindle\s+books?|audiobooks?|'
    r'paperback|hardcover|book\s+covers?|book\s+jackets?)\b|'
    r'\bbook\b(?!\s*(?:shelf|case|stand|light))|'
    r'كتب|رواي(?:ة|ات)|كتاب(?:\s|$)|غلاف\s+(?:كتاب|كتب)|أغلفة\s+(?:الكتب|كتب))'
)


def excluded_book_product(title):
    return bool(BOOK_PRODUCTS.search(str(title or '')))



def verified_real_discount(observation):
    """Reject discounts without independent historical price evidence."""
    from decimal import Decimal, InvalidOperation

    evidence = observation.get("price_verification")

    if not isinstance(evidence, dict):
        return None

    if (
        evidence.get("status") != "verified"
        or evidence.get("source_type") != "independent_price_history"
        or evidence.get("asin") != observation.get("asin")
        or not evidence.get("source_reference")
        or not evidence.get("observed_at")
    ):
        return None

    try:
        current = Decimal(str(observation["current_price"]))
        previous = Decimal(str(evidence["historical_price"]))
    except (InvalidOperation, ValueError, TypeError, KeyError):
        return None

    if not current.is_finite() or not previous.is_finite():
        return None

    if current <= 0 or previous <= current:
        return None

    discount = (previous - current) * 100 / previous
    return discount if discount >= 70 else None


def excluded_printed_material(title):
    import re

    return bool(re.search(
        r"(?i)\b(?:books?|ebooks?|paperbacks?|hardcovers?|"
        r"magazines?|textbooks?|workbooks?|exam papers?|"
        r"study guides?|revision guides?|book covers?|"
        r"printed worksheets?)\b|"
        r"كتب|كتاب|مجلات?|روايات|ملازم|ملزمة|"
        r"أوراق امتحانات|بنك أسئلة|غلاف كتاب",
        str(title or "")
    ))


def candidate_from_observation(observation):
    asin = observation.get('asin')
    if not isinstance(asin, str) or not re.fullmatch(r'[A-Z0-9]{10}', asin):
        raise ValueError('INVALID_ASIN')
    try:
        pct = Decimal(str(observation.get('displayed_discount_pct')))
        price = Decimal(str(observation.get('current_price')))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError('INVALID_OFFER') from exc
    if not pct.is_finite() or not 0 <= pct <= 100 or not price.is_finite() or price <= 0:
        raise ValueError('INVALID_OFFER')
    if excluded_book_product(observation.get('title')) or excluded_printed_material(observation.get('title')):
        return None

    if excluded_printed_material(observation.get("title")):
        return None

    import os

    if os.environ.get("V16_PRICE_HISTORY_BACKEND") == "worker":
        from worker_price_history import record_price, historical_discount
    elif os.environ.get("V16_PRICE_HISTORY_BACKEND") == "d1":
        from d1_price_history import record_price, historical_discount
    else:
        from price_history import record_price, historical_discount

    evidence = historical_discount(
        observation.get("asin"),
        observation.get("current_price"),
    )

    record_price(
        observation.get("asin"),
        observation.get("current_price"),
    )

    if evidence is None:
        return None

    verified_discount = verified_real_discount({
        **observation,
        "price_verification": evidence,
    })

    if verified_discount is None:
        return None

    pct = verified_discount

    return {
        'asin': asin,
        'title': str(observation.get('title') or 'منتج أمازون مصر')[:180],
        'current_price': str(price),
        'displayed_discount_pct': str(pct),
        'category': 'FLASH' if pct >= 90 else 'SUPER_ULTRA' if pct >= 70 else 'ULTRA' if pct >= 50 else 'GOOD' if pct >= 30 else 'STANDARD',
    }


def send_flash(observation, *, screenshot_path=None, screenshot_sha256=None,
               enabled=False, sender=None, send_once=None, send_screenshot_once=None,
               initialize=None):
    candidate = candidate_from_observation(observation)
    if candidate is None:
        return 'BELOW_THRESHOLD'
    if Decimal(candidate['displayed_discount_pct']) < 70:
        return 'BELOW_THRESHOLD'
    if not enabled or os.environ.get('V16_PRIVATE_TELEGRAM_ENABLED') != '1':
        return 'DISABLED'
    if not os.environ.get('V15_TELEGRAM_BOT_TOKEN') or not os.environ.get('V15_TELEGRAM_REVIEW_CHAT_ID'):
        return 'MISSING_TELEGRAM_CONFIGURATION'
    if sender is None:
        from flash_private_alert import send
        sender = send
    if os.environ.get('V16_DEDUP_BACKEND') == 'sqlite' and screenshot_path is None and send_once is None:
        from smart_dedup import send_once as v16_once
        send_once = v16_once
        # Text-only SQLite mode; never initialize or write V15 D1.
        return send_once(candidate, sender)
    if send_once is None or send_screenshot_once is None or initialize is None:
        from d1_flash_dedup import initialize as init, send_once as once, send_screenshot_once as screenshot_once
        initialize = initialize or init
        send_once = send_once or once
        send_screenshot_once = send_screenshot_once or screenshot_once
    # D1 schema must be initialized once during deployment, never on the urgent send path.
    if screenshot_path and screenshot_sha256:
        path = Path(screenshot_path)
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == screenshot_sha256:
            candidate['screenshot_path'] = str(path)
            candidate['screenshot_sha256'] = screenshot_sha256
            return send_screenshot_once(candidate, sender)
    # A delayed or missing screenshot must NOT delay the first private alert.
    return send_once(candidate, sender)
