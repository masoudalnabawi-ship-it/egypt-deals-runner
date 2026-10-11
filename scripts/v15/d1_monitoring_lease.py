"""Atomic Cloudflare D1 leasing for Amazon V15 monitoring."""

import json
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone

DATABASE = "egypt-amazon-v15-db"


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value):
    return value.isoformat(timespec="seconds")


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def query(sql):
    if not os.environ.get("CLOUDFLARE_API_TOKEN"):
        raise RuntimeError("V15_CLOUDFLARE_TOKEN_MISSING")

    command = [
        "npx", "--yes", "wrangler@4.149.0",
        "d1", "execute", DATABASE,
        "--remote", "--command", sql, "--json",
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=90,
    )

    if result.returncode:
        raise RuntimeError(
            "V15_D1_QUERY_FAILED: " + result.stderr[-1500:]
        )

    decoder = json.JSONDecoder()

    for index, char in enumerate(result.stdout):
        if char != "[":
            continue
        try:
            data, _ = decoder.raw_decode(result.stdout[index:])
            if isinstance(data, list):
                output = []
                for item in data:
                    if not item.get("success", False):
                        raise RuntimeError("V15_D1_UNSUCCESSFUL")
                    output.extend(item.get("results", []))
                return output
        except json.JSONDecodeError:
            continue

    raise RuntimeError("V15_D1_INVALID_RESPONSE")


def claim(asin, lease_minutes=15):
    if not 1 <= lease_minutes <= 60:
        raise ValueError("Invalid lease duration")

    now = utc_now()
    owner = "v15-" + uuid.uuid4().hex
    expires = now + timedelta(minutes=lease_minutes)

    sql = f"""
    UPDATE product_monitoring
    SET lease_owner={quote(owner)},
        lease_until={quote(timestamp(expires))},
        updated_at={quote(timestamp(now))}
    WHERE asin={quote(asin)}
      AND next_check_at <= {quote(timestamp(now))}
      AND (
          lease_until IS NULL
          OR lease_until <= {quote(timestamp(now))}
      )
    RETURNING asin, priority, consecutive_errors, lease_owner;
    """

    rows = query(sql)

    if len(rows) > 1:
        raise RuntimeError("V15_UNEXPECTED_MULTIPLE_CLAIMS")

    if not rows:
        return None

    if rows[0]["lease_owner"] != owner:
        raise RuntimeError("V15_LEASE_OWNER_MISMATCH")

    return rows[0]


def release_after_success(asin, owner, priority):
    from smart_scheduler import ProductState, next_check_at

    now = utc_now()

    state = ProductState(
        asin=asin,
        priority=priority,
        last_checked_at=now,
        consecutive_errors=0,
    )

    next_due = next_check_at(state, now)

    sql = f"""
    UPDATE product_monitoring
    SET lease_owner=NULL,
        lease_until=NULL,
        last_checked_at={quote(timestamp(now))},
        next_check_at={quote(timestamp(next_due))},
        consecutive_errors=0,
        updated_at={quote(timestamp(now))}
    WHERE asin={quote(asin)}
      AND lease_owner={quote(owner)}
      AND lease_until > {quote(timestamp(now))}
    RETURNING asin;
    """

    rows = query(sql)

    if len(rows) != 1:
        raise RuntimeError("V15_LEASE_LOST_BEFORE_RELEASE")

    return timestamp(next_due)


if __name__ == "__main__":
    print("V15_PRODUCTION_LEASING_MODULE_READY")
