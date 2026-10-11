"""V15 monitoring dispatcher — read-only validation stage."""

import json
import os
import subprocess
from datetime import datetime, timezone

DATABASE = "egypt-amazon-v15-db"

PRIORITY_ORDER = {
    "HOT": 0,
    "ACTIVE": 1,
    "STABLE": 2,
    "LOW": 3,
}


def query_d1(sql):
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
        check=False,
    )

    if result.returncode:
        raise RuntimeError(
            "D1_QUERY_FAILED: "
            + (result.stdout + result.stderr)[-2000:]
        )

    decoder = json.JSONDecoder()

    for i, character in enumerate(result.stdout):
        if character != "[":
            continue

        try:
            data, _ = decoder.raw_decode(result.stdout[i:])
        except json.JSONDecodeError:
            continue

        if isinstance(data, list):
            if not all(item.get("success") for item in data):
                raise RuntimeError("D1_QUERY_UNSUCCESSFUL")

            return [
                row
                for item in data
                for row in item.get("results", [])
            ]

    raise RuntimeError("D1_JSON_RESPONSE_NOT_FOUND")


def main():
    if not os.getenv("CLOUDFLARE_API_TOKEN"):
        raise RuntimeError("CLOUDFLARE_API_TOKEN_MISSING")

    now = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )

    sql = (
        "SELECT asin, priority, next_check_at, "
        "lease_owner, lease_until, consecutive_errors "
        "FROM product_monitoring "
        f"WHERE next_check_at <= '{now}' "
        "AND (lease_until IS NULL "
        f"OR lease_until <= '{now}') "
        "ORDER BY CASE priority "
        "WHEN 'HOT' THEN 0 "
        "WHEN 'ACTIVE' THEN 1 "
        "WHEN 'STABLE' THEN 2 "
        "ELSE 3 END, next_check_at "
        "LIMIT 20"
    )

    products = query_d1(sql)

    print("V15_DISPATCHER_READ_ONLY")
    print("DUE_PRODUCTS:", len(products))

    for product in products:
        print(
            "DUE:",
            product["asin"],
            product["priority"],
            product["next_check_at"],
        )

    print("V15_DISPATCHER_CHECK_OK")


if __name__ == "__main__":
    main()
