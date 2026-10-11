"""Amazon V15 — persistent verified price observations."""

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS price_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asin TEXT NOT NULL,
    price TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(asin, observed_at, source)
);
CREATE INDEX IF NOT EXISTS idx_v15_price_history
ON price_observations(asin, observed_at);
"""


def valid_price(value):
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid price")

    if not price.is_finite() or price <= 0:
        raise ValueError("Invalid price")

    return price


def record_observation(database, report_path):
    report_path = Path(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # Reuse the V15 evidence gate.
    try:
        from scripts.v15.evidence_pipeline import evaluate_evidence
    except ModuleNotFoundError:
        from evidence_pipeline import evaluate_evidence

    result = evaluate_evidence(report_path)

    if result["status"] != "awaiting_reference_verification":
        raise ValueError("Evidence validation failed")

    asin = report["asin"]
    price = valid_price(report["observation"]["current_price"])

    captured_at = report.get("captured_at")
    if not isinstance(captured_at, str):
        raise ValueError("Missing capture timestamp")

    timestamp = datetime.fromisoformat(
        captured_at.replace("Z", "+00:00")
    )

    if timestamp.tzinfo is None:
        raise ValueError("Timestamp must include timezone")

    if timestamp > datetime.now(timezone.utc):
        raise ValueError("Future observation")

    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            """
            INSERT OR IGNORE INTO price_observations
            (asin, price, observed_at, source)
            VALUES (?, ?, ?, ?)
            """,
            (
                asin,
                str(price),
                timestamp.astimezone(timezone.utc).isoformat(),
                "amazon_egypt_playwright",
            ),
        )

        rows = connection.execute(
            """
            SELECT price, observed_at
            FROM price_observations
            WHERE asin = ?
            ORDER BY observed_at
            """,
            (asin,),
        ).fetchall()

    historical = [
        (valid_price(p), t)
        for p, t in rows
        if t < timestamp.astimezone(timezone.utc).isoformat()
    ]

    output = {
        "asin": asin,
        "current_price": str(price),
        "observations": len(rows),
        "historical_reference": None,
        "historical_discount": None,
        "status": "collecting_history",
        "route": None,
    }

    if historical:
        highest = max(p for p, _ in historical)

        output["historical_reference"] = str(highest)

        if highest > price:
            discount = (highest - price) / highest * Decimal("100")
            output["historical_discount"] = str(
                discount.quantize(Decimal("0.01"))
            )

        # Historical observations alone are not sufficient
        # to automatically approve a genuine discount.
        output["status"] = "history_available_requires_policy"

    return output


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: price_history.py <database.sqlite> <verification.json>"
        )

    print(
        json.dumps(
            record_observation(sys.argv[1], sys.argv[2]),
            ensure_ascii=False,
            indent=2,
        )
    )
