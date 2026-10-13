"""V16 opt-in private Telegram transport, reusing V15's persistent D1 dedup.

Not connected to production, GitHub Actions, or automatic monitoring.
Never sends anything without an explicit caller and opt-in environment flag.
"""
import os
import sys
from pathlib import Path

V15 = Path(__file__).resolve().parents[1] / 'v15'
if str(V15) not in sys.path:
    sys.path.insert(0, str(V15))

from verified_alert_bridge import from_verified_report


def candidate_from_report(report):
    decision = from_verified_report(report)
    alert = decision['private_alert']
    if alert is None:
        return None
    asin = alert['asin']
    return {
        'asin': asin,
        'title': str(report.get('title') or 'Amazon Egypt product ' + asin),
        'current_price': str(report.get('current_price_egp', report.get('price_egp'))),
        'displayed_discount_pct': str(report['displayed_discount_pct']),
        'category': alert['tier'],
    }


def send_verified_private(report, *, enabled=False, sender=None, dedup=None):
    """Explicitly send via V15 private sender and persistent D1 dedup.

    Returns a status string. The caller must supply a genuine report and must
    opt in. Missing secrets or D1 failures do not trigger unguarded sends.
    """
    candidate = candidate_from_report(report)
    if candidate is None:
        return 'BELOW_THRESHOLD'
    if not enabled or os.environ.get('V16_PRIVATE_TELEGRAM_ENABLED') != '1':
        return 'DISABLED'
    if not os.environ.get('V15_TELEGRAM_BOT_TOKEN') or not os.environ.get('V15_TELEGRAM_REVIEW_CHAT_ID'):
        return 'MISSING_TELEGRAM_CONFIGURATION'
    if sender is None:
        from flash_private_alert import send
        sender = send
    if dedup is None:
        from flash_dedup import initialize, send_once
        initialize()
        dedup = send_once
    return dedup(candidate, sender)
