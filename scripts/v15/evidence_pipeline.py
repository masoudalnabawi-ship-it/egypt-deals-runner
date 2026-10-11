"""V15: validate real Amazon evidence before discount evaluation."""

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path


def evaluate_evidence(report_path):
    report_path = Path(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    asin = str(report.get("asin", "")).strip().upper()
    obs = report.get("observation") or {}

    result = {
        "asin": asin,
        "status": "rejected",
        "route": None,
        "reasons": [],
    }

    if len(asin) != 10 or not asin.isalnum():
        result["reasons"].append("invalid_asin")

    if obs.get("page_asin") != asin:
        result["reasons"].append("asin_mismatch")

    image_name = report.get("screenshot")

    if not isinstance(image_name, str):
        result["reasons"].append("missing_screenshot")
    else:
        image_path = report_path.parent / image_name

        if (
            Path(image_name).name != image_name
            or not image_path.is_file()
        ):
            result["reasons"].append("invalid_screenshot_path")
        else:
            image = image_path.read_bytes()

            if not image.startswith(b"\xff\xd8\xff"):
                result["reasons"].append("invalid_jpeg")

            digest = hashlib.sha256(image).hexdigest()

            if digest != report.get("screenshot_sha256"):
                result["reasons"].append("screenshot_hash_mismatch")

    try:
        current = Decimal(str(obs["current_price"]))
        reference = Decimal(str(obs["old_price"]))

        if (
            not current.is_finite()
            or not reference.is_finite()
            or current <= 0
            or reference <= current
        ):
            result["reasons"].append("invalid_prices")
        else:
            discount = (
                (reference - current)
                / reference
                * Decimal("100")
            )

            result["displayed_discount"] = str(
                discount.quantize(Decimal("0.01"))
            )

    except (KeyError, InvalidOperation, ValueError, TypeError):
        result["reasons"].append("missing_or_invalid_prices")

    if result["reasons"]:
        return result

    # An Amazon struck-through price is not automatically
    # a trustworthy historical reference price.
    result["status"] = "awaiting_reference_verification"
    result["reasons"].append("historical_price_not_verified")

    # Never send an unverified discount to either review channel.
    result["route"] = None

    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python scripts/v15/evidence_pipeline.py "
            "<verification.json>"
        )

    print(
        json.dumps(
            evaluate_evidence(sys.argv[1]),
            ensure_ascii=False,
            indent=2,
        )
    )
