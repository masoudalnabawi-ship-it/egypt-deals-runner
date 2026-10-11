"""Amazon V15 final review eligibility gate.

This module validates evidence metadata. It does not capture screenshots,
verify Amazon pages, or send Telegram messages.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from scripts.v15.price_intelligence import VerifiedPrice, evaluate_price


@dataclass(frozen=True)
class ScreenshotEvidence:
    asin: str
    captured_at: int
    verified_at: int
    source: str
    image_reference: str


def review_decision(
    price: VerifiedPrice,
    screenshot: ScreenshotEvidence | None,
    now: int,
    max_age_seconds: int = 900,
):
    result = evaluate_price(price)

    if result.get("publish_allowed") is not True:
        return {
            "approved": False,
            "reason": result.get("status", "price_rejected"),
        }

    if screenshot is None:
        return {"approved": False, "reason": "missing_screenshot"}

    asin = str(price.asin).strip().upper()

    if (
        screenshot.asin.strip().upper() != asin
        or screenshot.source != "amazon_egypt_playwright"
        or not screenshot.image_reference.strip()
    ):
        return {"approved": False, "reason": "invalid_screenshot"}

    if (
        screenshot.captured_at > now
        or screenshot.verified_at > now
        or screenshot.captured_at < screenshot.verified_at
        or now - screenshot.captured_at > max_age_seconds
        or now - screenshot.verified_at > max_age_seconds
    ):
        return {"approved": False, "reason": "stale_evidence"}

    if result["route"] not in ("normal", "ultra"):
        return {"approved": False, "reason": "invalid_route"}

    return {
        "approved": True,
        "route": result["route"],
        "asin": asin,
        "discount": result["discount"],
        "image_reference": screenshot.image_reference,
        "status": "ready_for_review",
    }
