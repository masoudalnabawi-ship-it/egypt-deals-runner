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
        diagnostic = (result.stderr.strip() or result.stdout.strip())[-1500:]
        token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
        if token:
            diagnostic = diagnostic.replace(token, "[REDACTED]")
        raise RuntimeError(
            f"V15_D1_QUERY_FAILED exit={result.returncode}: "
            f"{diagnostic or 'no diagnostic output'}"
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


def claim_next_due(lease_minutes=30):
    """Atomically claim the oldest due, unleased product across all ASINs."""
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
    WHERE asin = (
        SELECT asin FROM product_monitoring
        WHERE next_check_at <= {quote(timestamp(now))}
          AND (lease_until IS NULL OR lease_until <= {quote(timestamp(now))})
        ORDER BY next_check_at ASC,
          CASE priority WHEN 'HOT' THEN 0 WHEN 'ACTIVE' THEN 1
            WHEN 'STABLE' THEN 2 ELSE 3 END,
          asin ASC
        LIMIT 1
    )
      AND (lease_until IS NULL OR lease_until <= {quote(timestamp(now))})
    RETURNING asin, priority, consecutive_errors, lease_owner;
    """
    rows = query(sql)
    if not rows:
        return None
    if len(rows) != 1 or rows[0]['lease_owner'] != owner:
        raise RuntimeError('V15_GLOBAL_LEASE_INVARIANT_FAILED')
    return rows[0]


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


def release_after_failure(asin, owner):
    """Reschedule a failed probe without claiming a successful observation.

    The conditional UPDATE prevents a stale worker from releasing another lease.
    """
    from smart_scheduler import INTERVALS, MAX_BACKOFF_MINUTES

    now = utc_now()
    # Calculate backoff inside D1 using the current error count, so a stale
    # worker cannot overwrite a newer count. Priority is read from the row.
    intervals = "CASE priority WHEN 'HOT' THEN 3 WHEN 'ACTIVE' THEN 10 WHEN 'STABLE' THEN 30 WHEN 'LOW' THEN 60 ELSE 60 END"
    # Clamp exponential backoff at 6 hours. SQLite supports POWER().
    backoff = """CASE
        WHEN consecutive_errors <= 0 THEN 2
        WHEN consecutive_errors = 1 THEN 4
        WHEN consecutive_errors = 2 THEN 8
        WHEN consecutive_errors = 3 THEN 16
        WHEN consecutive_errors = 4 THEN 32
        ELSE 64
    END"""
    minutes = f"MIN({MAX_BACKOFF_MINUTES}, ({intervals}) * ({backoff}))"
    sql = f"""
    UPDATE product_monitoring
    SET consecutive_errors = consecutive_errors + 1,
        next_check_at = strftime('%Y-%m-%dT%H:%M:%S',
          julianday({quote(timestamp(now))}) + ({minutes}) / 1440.0) || '+00:00',
        lease_owner = NULL,
        lease_until = NULL,
        updated_at = {quote(timestamp(now))}
    WHERE asin = {quote(asin)}
      AND lease_owner = {quote(owner)}
      AND lease_until > {quote(timestamp(now))}
    RETURNING asin, consecutive_errors, next_check_at;
    """
    result = query(sql)
    if len(result) != 1:
        raise RuntimeError('V15_FAILURE_LEASE_LOST')
    return result[0]
