"""V16 read-only bridge: score verified V15 evidence and prepare private alerts.

No network, D1, Telegram, or mutation. The production transport remains V15.
"""
import json
from pathlib import Path
from decimal import Decimal, InvalidOperation
from deal_intelligence import Deal, evaluate
from flash_hunter import FlashOffer, prepare_private_alert


def from_verified_report(report: dict) -> dict:
    if not isinstance(report, dict):
        raise ValueError('report must be a dictionary')
    asin = report.get('asin')
    if not isinstance(asin, str) or len(asin) != 10 or not asin.isalnum():
        raise ValueError('invalid ASIN')
    # Reject unverifiable values rather than inventing discounts.
    price = report.get('current_price_egp', report.get('price_egp'))
    discount = report.get('displayed_discount_pct')
    if price is None or discount is None:
        raise ValueError('verified report has no price or displayed discount')
    scoring = evaluate(Deal(asin, str(price), str(discount)))
    title = report.get('title') or ('Amazon Egypt product ' + asin)
    url = report.get('url') or ('https://www.amazon.eg/dp/' + asin)
    alert = prepare_private_alert(FlashOffer(asin, str(title), str(price), str(discount), str(url)))
    return {'score': scoring, 'private_alert': alert}


def read_verified(path: str | Path) -> dict:
    source = Path(path)
    if not source.is_file():
        raise ValueError('report not found')
    return from_verified_report(json.loads(source.read_text(encoding='utf-8')))


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python scripts/v16/verified_alert_bridge.py VERIFIED_REPORT.json')
    print(json.dumps(read_verified(sys.argv[1]), ensure_ascii=False, indent=2))
