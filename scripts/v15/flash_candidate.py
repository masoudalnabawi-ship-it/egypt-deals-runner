"""V15 read-only flash candidate classification. No messages, no publication."""
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from book_filter import from_report

def candidate(report, threshold=Decimal("5")):
    if from_report(report):
        return None

    obs = report.get("observation") or {}
    if not isinstance(obs, dict) or obs.get("page_asin") != report.get("asin"):
        return None

    try:
        pct = Decimal(str(obs.get("savings_percent") or 0))
    except (InvalidOperation, ValueError, TypeError):
        return None

    if not pct.is_finite() or not threshold <= pct < 100:
        return None

    if pct >= 90:
        category = "FLASH"
    elif pct >= 70:
        category = "SUPER_ULTRA"
    elif pct >= 50:
        category = "ULTRA"
    elif pct >= 30:
        category = "STRONG"
    elif pct >= 10:
        category = "GOOD"
    else:
        category = "NORMAL"

    try:
        current = Decimal(str(obs.get("current_price")))
        price = str(current) if current.is_finite() and current > 0 else None
    except (InvalidOperation, ValueError, TypeError):
        price = None

    return {
        "asin": report["asin"],
        "url": report.get("url"),
        "current_price": price,
        "title": str(obs.get("title") or "").strip()[:180],
        "displayed_discount_pct": str(pct),
        "category": category,
        "captured_at": report.get("captured_at"),
        "status": "AMAZON_DISPLAYED_DISCOUNT",
        "publication_allowed": False,
        "note": "Discount displayed on Amazon; not historically verified",
    }

def stage(report, output_dir):
    item=candidate(report)
    if item is None:return None
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    path=out/(item['asin']+'.json')
    path.write_text(json.dumps(item,ensure_ascii=False,indent=2),encoding='utf-8')
    return path
