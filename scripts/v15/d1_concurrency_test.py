import concurrent.futures
import json
import os
import subprocess
import sys
import uuid

DB = "egypt-amazon-v15-db"
ASIN = "V15RACE" + uuid.uuid4().hex[:16].upper()
NOW = "2026-10-11T12:00:00+00:00"
PAST = "2026-01-01T00:00:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"


def execute(sql):
    cmd = [
        "npx", "--yes", "wrangler@4.149.0",
        "d1", "execute", DB,
        "--remote", "--command", sql, "--json"
    ]
    p = subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=90, env=os.environ.copy()
    )
    if p.returncode:
        raise RuntimeError(
            "D1_FAILED: " + (p.stdout + p.stderr)[-2500:]
        )

    decoder = json.JSONDecoder()
    for i, char in enumerate(p.stdout):
        if char == "[":
            try:
                data, _ = decoder.raw_decode(p.stdout[i:])
                if isinstance(data, list):
                    if not all(x.get("success") for x in data):
                        raise RuntimeError("D1_UNSUCCESSFUL_RESPONSE")
                    return data
            except json.JSONDecodeError:
                pass
    raise RuntimeError("D1_JSON_NOT_FOUND")


def claim(worker):
    sql = (
        "UPDATE product_monitoring "
        f"SET lease_owner='{worker}', "
        f"lease_until='{FUTURE}', updated_at='{NOW}' "
        f"WHERE asin='{ASIN}' "
        f"AND next_check_at <= '{NOW}' "
        f"AND (lease_until IS NULL OR lease_until <= '{NOW}') "
        "RETURNING lease_owner"
    )
    data = execute(sql)
    results = [
        row for item in data
        for row in item.get("results", [])
    ]
    return worker, results


def main():
    if not os.environ.get("CLOUDFLARE_API_TOKEN"):
        raise RuntimeError("CLOUDFLARE_API_TOKEN missing")

    try:
        execute(
            "INSERT INTO product_monitoring "
            "(asin, priority, next_check_at, updated_at) "
            f"VALUES ('{ASIN}', 'HOT', '{PAST}', '{PAST}')"
        )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=2
        ) as pool:
            futures = [
                pool.submit(claim, "worker-a"),
                pool.submit(claim, "worker-b")
            ]
            outcomes = [f.result() for f in futures]

        winners = [
            worker for worker, rows in outcomes
            if len(rows) == 1
            and rows[0].get("lease_owner") == worker
        ]

        if len(winners) != 1:
            raise AssertionError(
                f"EXPECTED_ONE_WINNER: {outcomes}"
            )

        final = execute(
            "SELECT lease_owner FROM product_monitoring "
            f"WHERE asin='{ASIN}'"
        )
        owners = [
            row["lease_owner"]
            for item in final
            for row in item.get("results", [])
        ]

        if owners != winners:
            raise AssertionError(
                f"FINAL_OWNER_MISMATCH: {owners}, {winners}"
            )

        print("V15_CONCURRENT_LEASE_TEST_OK")
        print("EXACTLY_ONE_WINNER: PASS")
        print("WINNER:", winners[0])

    finally:
        execute(
            "DELETE FROM product_monitoring "
            f"WHERE asin='{ASIN}'"
        )
        print("V15_RACE_TEST_CLEANED")


if __name__ == "__main__":
    main()
