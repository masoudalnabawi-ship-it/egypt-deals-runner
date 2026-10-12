"""V15 private alerts for observed price drops; no public publishing."""
from decimal import Decimal, InvalidOperation
from d1_monitoring_lease import query, quote
from flash_dedup import initialize, send_once
from flash_private_alert import send


def review(report):
    asin = str(report.get("asin", ""))
    obs = report.get("observation") or {}

    if len(asin) != 10 or not asin.isalnum() or asin != asin.upper():
        return "INVALID_ASIN"

    if obs.get("page_asin") != asin:
        return "INVALID_PAGE"

    try:
        current = Decimal(str(obs["current_price"]))
    except (InvalidOperation, ValueError, TypeError, KeyError):
        return "INVALID_PRICE"

    if not current.is_finite() or current <= 0:
        return "INVALID_PRICE"

    rows = query(
        "SELECT price FROM price_observations "
        "WHERE asin=" + quote(asin) +
        " AND observed_at < " + quote(report["captured_at"]) +
        " ORDER BY observed_at DESC LIMIT 1"
    )

    if not rows:
        return "COLLECTING_HISTORY"

    try:
        previous = Decimal(str(rows[0]["price"]))
    except (InvalidOperation, ValueError, TypeError):
        return "INVALID_HISTORY"

    if not previous.is_finite() or previous <= 0:
        return "INVALID_HISTORY"

    if current * 100 > previous * 90:
        return "NO_SIGNIFICANT_DROP"

    candidate = {
        "asin": asin,
        "current_price": str(current),
        "title": obs.get("title") or "منتج على أمازون مصر",
        "review_type": "PRICE_ONLY",
        "publication_allowed": False,
        "screenshot_path": report.get("screenshot_path"),
        "screenshot_sha256": report.get("screenshot_sha256"),
    }

    initialize()
    return send_once(candidate, send)
