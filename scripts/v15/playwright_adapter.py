"""Amazon V15 adapter for real Playwright observations.

Competitor discounts, coupons, and saving badges cannot independently
establish a verified reference price.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from scripts.v15.price_intelligence import VerifiedPrice, evaluate_price


ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


@dataclass(frozen=True)
class VerificationResult:
    asin: str
    observation: dict
    page_verified: bool


def adapt_playwright_result(result: VerificationResult):
    asin = str(result.asin).strip().upper()
    obs = result.observation

    if not ASIN_RE.fullmatch(asin):
        return {"approved": False, "reason": "invalid_asin"}

    if not isinstance(obs, dict):
        return {"approved": False, "reason": "invalid_observation"}

    page_asin = str(obs.get("page_asin") or "").strip().upper()

    if page_asin != asin:
        return {"approved": False, "reason": "asin_mismatch"}

    if result.page_verified is not True:
        return {"approved": False, "reason": "page_unverified"}

    current = obs.get("current_price")
    old = obs.get("old_price")

    # This flag must come from the trusted verifier, not a competitor.
    reference_trusted = obs.get("reference_trusted") is True

    decision = evaluate_price(
        VerifiedPrice(
            asin=asin,
            current_price=current,
            reference_price=old,
            verified=True,
            reference_trusted=reference_trusted,
        )
    )

    if decision.get("publish_allowed") is not True:
        return {
            "approved": False,
            "reason": decision.get("status", "price_rejected"),
        }

    return {
        "approved": True,
        "asin": asin,
        "route": decision["route"],
        "discount": decision["discount"],
        "current_price": decision["current_price"],
        "reference_price": decision["reference_price"],
        "requires_real_screenshot": True,
        "status": "awaiting_screenshot",
    }
