"""Test production lease against an isolated temporary D1 product."""
import sys
import uuid
from datetime import timedelta

from d1_monitoring_lease import (
    claim, query, quote, release_after_success, timestamp, utc_now
)

asin = "V15LEASE" + uuid.uuid4().hex[:16].upper()
past = timestamp(utc_now() - timedelta(minutes=5))

try:
    query(
        "INSERT INTO product_monitoring "
        "(asin, priority, next_check_at, updated_at) "
        f"VALUES ({quote(asin)}, 'ACTIVE', {quote(past)}, {quote(past)})"
    )

    first = claim(asin)
    assert first is not None, "FIRST_CLAIM_FAILED"
    print("FIRST_CLAIM_OK")

    second = claim(asin)
    assert second is None, "DUPLICATE_CLAIM_ALLOWED"
    print("DUPLICATE_CLAIM_BLOCKED")

    next_due = release_after_success(
        asin,
        first["lease_owner"],
        first["priority"],
    )

    print("RELEASE_OK")
    print("NEXT_CHECK:", next_due)

    third = claim(asin)
    assert third is None, "EARLY_RECLAIM_ALLOWED"
    print("EARLY_RECLAIM_BLOCKED")
    print("V15_PRODUCTION_LEASE_TEST_OK")

finally:
    try:
        query(
            "DELETE FROM product_monitoring "
            f"WHERE asin={quote(asin)}"
        )
        print("TEST_PRODUCT_CLEANED")
    except Exception as exc:
        print(f"TEST_CLEANUP_FAILED: {exc}", file=sys.stderr)
        raise
