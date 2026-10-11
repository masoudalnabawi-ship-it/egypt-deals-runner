"""Amazon V15 atomic product leasing.

No network calls, Telegram delivery, or production modifications.
"""

import sqlite3
from datetime import datetime, timedelta, timezone


def utc_timestamp(value):
    if value.tzinfo is None:
        raise ValueError("Timezone-aware datetime required")
    return value.astimezone(timezone.utc).isoformat()


def claim_product(connection, asin, owner, now, lease_minutes=10):
    if not owner or not owner.strip():
        raise ValueError("Lease owner required")

    if lease_minutes < 1 or lease_minutes > 60:
        raise ValueError("Invalid lease duration")

    current = utc_timestamp(now)
    expires = utc_timestamp(now + timedelta(minutes=lease_minutes))

    cursor = connection.execute(
        """
        UPDATE product_monitoring
        SET lease_owner = ?,
            lease_until = ?,
            updated_at = ?
        WHERE asin = ?
          AND next_check_at <= ?
          AND (
              lease_until IS NULL
              OR lease_until <= ?
          )
        """,
        (owner, expires, current, asin, current, current),
    )

    connection.commit()
    return cursor.rowcount == 1


def release_product(connection, asin, owner, now, next_check):
    current = utc_timestamp(now)
    next_time = utc_timestamp(next_check)

    cursor = connection.execute(
        """
        UPDATE product_monitoring
        SET lease_owner = NULL,
            lease_until = NULL,
            last_checked_at = ?,
            next_check_at = ?,
            updated_at = ?
        WHERE asin = ?
          AND lease_owner = ?
          AND lease_until > ?
        """,
        (
            current,
            next_time,
            current,
            asin,
            owner,
            current,
        ),
    )

    connection.commit()
    return cursor.rowcount == 1
