"""V16 local price-history tracker. No changes to V14/V15."""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

DB = Path(os.environ.get(
    "V16_PRICE_HISTORY_DB",
    str(Path(__file__).resolve().parents[2] / "data" / "v16_prices.sqlite3")
))


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS price_observations (
            asin TEXT NOT NULL,
            price TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            PRIMARY KEY (asin, observed_at)
        )
    """)
    return con


def record_price(asin, price):
    try:
        value = Decimal(str(price))
    except (InvalidOperation, TypeError, ValueError):
        return False

    if (
        not isinstance(asin, str)
        or len(asin) != 10
        or not asin.isalnum()
        or not value.is_finite()
        or value <= 0
    ):
        return False

    now = datetime.now(timezone.utc).isoformat()

    with connect() as con:
        con.execute(
            "INSERT OR IGNORE INTO price_observations VALUES (?, ?, ?)",
            (asin, str(value), now),
        )

    return True


def historical_discount(asin, current_price, min_age_days=7):
    """Use an older observed price, never Amazon's advertised list price."""
    try:
        current = Decimal(str(current_price))
    except (InvalidOperation, TypeError, ValueError):
        return None

    if not current.is_finite() or current <= 0:
        return None

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=min_age_days)
    ).isoformat()

    with connect() as con:
        rows = con.execute(
            """
            SELECT price FROM price_observations
            WHERE asin = ? AND observed_at <= ?
            """,
            (asin, cutoff),
        ).fetchall()

    prices = []

    for (raw,) in rows:
        try:
            value = Decimal(raw)
            if value.is_finite() and value > 0:
                prices.append(value)
        except InvalidOperation:
            continue

    if not prices:
        return None

    # Conservative baseline: lowest previously observed price.
    previous = min(prices)

    if previous <= current:
        return None

    discount = (previous - current) * 100 / previous

    if discount < 70:
        return None

    return {
        "asin": asin,
        "status": "verified",
        "source_type": "independent_price_history",
        "source_reference": "v16_local_price_history",
        "observed_at": cutoff,
        "historical_price": str(previous),
        "verified_discount_pct": str(discount),
    }
