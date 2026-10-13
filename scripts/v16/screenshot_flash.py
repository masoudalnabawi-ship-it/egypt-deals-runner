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


def candidate_from_observation(observation):
    asin = observation.get('asin')
    if not isinstance(asin, str) or not re.fullmatch(r'[A-Z0-9]{10}', asin):
        raise ValueError('INVALID_ASIN')
    try:
        pct = Decimal(str(observation.get('displayed_discount_pct')))
        price = Decimal(str(observation.get('current_price')))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError('INVALID_OFFER') from exc
    if not pct.is_finite() or not 0 <= pct < 100 or not price.is_finite() or price <= 0:
        raise ValueError('INVALID_OFFER')
    if pct < 50:
        return None
    return {
        'asin': asin,
        'title': str(observation.get('title') or 'منتج أمازون مصر')[:180],
        'current_price': str(price),
        'displayed_discount_pct': str(pct),
        'category': 'FLASH' if pct >= 90 else 'SUPER_ULTRA' if pct >= 70 else 'ULTRA',
    }


def send_flash(observation, *, screenshot_path=None, screenshot_sha256=None,
               enabled=False, sender=None, send_once=None, send_screenshot_once=None,
               initialize=None):
    candidate = candidate_from_observation(observation)
    if candidate is None:
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
        from flash_dedup import initialize as init, send_once as once, send_screenshot_once as screenshot_once
        initialize = initialize or init
        send_once = send_once or once
        send_screenshot_once = send_screenshot_once or screenshot_once
    initialize()
    if screenshot_path and screenshot_sha256:
        path = Path(screenshot_path)
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == screenshot_sha256:
            candidate['screenshot_path'] = str(path)
            candidate['screenshot_sha256'] = screenshot_sha256
            return send_screenshot_once(candidate, sender)
    # A delayed or missing screenshot must NOT delay the first private alert.
    return send_once(candidate, sender)
