"""Prepare a validated Amazon V15 price observation for Cloudflare D1.

No Telegram delivery. No V14 production changes.
"""

import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

try:
    from scripts.v15.evidence_pipeline import evaluate_evidence
    from scripts.v15.price_history import valid_price
except ModuleNotFoundError:
    from evidence_pipeline import evaluate_evidence
    from price_history import valid_price


SOURCE = "amazon_egypt_playwright"


def prepare_observation(report_path):
    report_path = Path(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    evidence = evaluate_evidence(report_path)

    if evidence["status"] != "awaiting_reference_verification":
        raise ValueError("Invalid V15 evidence")

    asin = report["asin"]
    price = valid_price(report["observation"]["current_price"])

    captured_at = report["captured_at"]
    timestamp = datetime.fromisoformat(
        captured_at.replace("Z", "+00:00")
    )

    if timestamp.tzinfo is None:
        raise ValueError("Timestamp must include timezone")

    timestamp = timestamp.astimezone(timezone.utc)

    if timestamp > datetime.now(timezone.utc):
        raise ValueError("Future observation")

    return {
        "asin": asin,
        "price": str(price),
        "observed_at": timestamp.isoformat(),
        "source": SOURCE,
        "status": "observation_only",
        "discount_verified": False,
        "telegram_sent": False,
    }


def sql_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def build_insert_sql(observation):
    values = [
        sql_quote(observation["asin"]),
        sql_quote(observation["price"]),
        sql_quote(observation["observed_at"]),
        sql_quote(observation["source"]),
    ]

    return (
        "INSERT OR IGNORE INTO price_observations "
        "(asin, price, observed_at, source) "
        "VALUES (" + ", ".join(values) + ");"
    )


def main():
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: d1_price_observation.py "
            "<verification.json> <output.sql>"
        )

    observation = prepare_observation(sys.argv[1])
    output = Path(sys.argv[2])
    output.parent.mkdir(parents=True, exist_ok=True)

    output.write_text(
        build_insert_sql(observation) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(observation, ensure_ascii=False, indent=2))
    print("V15_D1_OBSERVATION_SQL_READY")


if __name__ == "__main__":
    main()
