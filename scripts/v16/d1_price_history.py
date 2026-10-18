"""V16-only persistent price history in Cloudflare D1."""

import re
from datetime import datetime, timezone
from decimal import Decimal
import sys
from pathlib import Path

V15 = Path(__file__).resolve().parents[1] / "v15"
if str(V15) not in sys.path:
    sys.path.insert(0, str(V15))

from d1_monitoring_lease import query, quote

TABLE = "v16_price_history"


def initialize():
    query(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            asin TEXT NOT NULL,
            price_cents INTEGER NOT NULL,
            observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (asin, observed_at)
        )
    """)


def record_price(asin, price):
    if not isinstance(asin, str) or not re.fullmatch(r"[A-Z0-9]{10}", asin):
        raise ValueError("INVALID_ASIN")

    amount = Decimal(str(price))

    if not amount.is_finite() or amount <= 0:
        raise ValueError("INVALID_PRICE")

    cents = int(amount * 100)

    query(f"""
        INSERT OR IGNORE INTO {TABLE}
        (asin, price_cents)
        VALUES ({quote(asin)}, {cents})
    """)

    return True


def historical_discount(asin, current_price, min_age_days=7):
    amount = Decimal(str(current_price))

    if not amount.is_finite() or amount <= 0:
        return None

    current_cents = int(amount * 100)

    rows = query(f"""
        SELECT MIN(price_cents) AS previous_price
        FROM {TABLE}
        WHERE asin = {quote(asin)}
          AND observed_at <= datetime('now', '-{int(min_age_days)} days')
    """)

    if not rows or rows[0].get("previous_price") is None:
        return None

    previous = int(rows[0]["previous_price"])

    if previous <= current_cents:
        return None

    discount = Decimal(previous - current_cents) * 100 / Decimal(previous)

    if discount < 70:
        return None

    return {
        "asin": asin,
        "status": "verified",
        "source_type": "independent_price_history",
        "source_reference": "v16_d1_price_history",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "historical_price": str(Decimal(previous) / 100),
        "verified_discount_pct": str(discount),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--initialize", action="store_true")
    args = parser.parse_args()

    if not args.initialize:
        parser.error("Use --initialize explicitly")

    initialize()
    print("V16_D1_PRICE_HISTORY_INITIALIZED")
