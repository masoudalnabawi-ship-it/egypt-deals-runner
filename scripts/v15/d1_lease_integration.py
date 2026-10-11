import json
import os
import subprocess
import sys
import uuid

DATABASE = "egypt-amazon-v15-db"
WRANGLER = ["npx", "--yes", "wrangler@4.149.0"]
ASIN = "V15TEST" + uuid.uuid4().hex[:16].upper()

NOW = "2026-10-11T12:00:00+00:00"
PAST = "2026-01-01T00:00:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"


def execute(sql):
    command = WRANGLER + [
        "d1", "execute", DATABASE,
        "--remote",
        "--command", sql,
        "--json",
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=90,
        env=os.environ.copy(),
    )

    if result.returncode:
        print("D1_COMMAND_FAILED", file=sys.stderr)
        print(result.stdout[-3000:], file=sys.stderr)
        print(result.stderr[-3000:], file=sys.stderr)
        raise RuntimeError("D1 execution failed")

    raw = result.stdout.strip()

    # Wrangler may print progress before its JSON response.
    decoder = json.JSONDecoder()

    for index, char in enumerate(raw):
        if char != "[":
            continue
        try:
            data, _ = decoder.raw_decode(raw[index:])
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            continue

    raise RuntimeError(
        "Cannot parse Wrangler JSON: " + raw[-1500:]
    )


def rows(sql):
    data = execute(sql)
    output = []

    for item in data:
        if not item.get("success", False):
            raise RuntimeError("D1_QUERY_NOT_SUCCESSFUL")
        output.extend(item.get("results", []))

    return output


def owner():
    result = rows(
        "SELECT lease_owner FROM product_monitoring "
        f"WHERE asin='{ASIN}'"
    )

    if len(result) != 1:
        raise AssertionError(
            f"Expected one test row, found {len(result)}"
        )

    return result[0]["lease_owner"]


def claim(worker):
    rows(
        "UPDATE product_monitoring "
        f"SET lease_owner='{worker}', "
        f"lease_until='{FUTURE}', "
        f"updated_at='{NOW}' "
        f"WHERE asin='{ASIN}' "
        f"AND next_check_at <= '{NOW}' "
        "AND (lease_until IS NULL "
        f"OR lease_until <= '{NOW}')"
    )


def assert_owner(expected, label):
    actual = owner()

    if actual != expected:
        raise AssertionError(
            f"{label}: expected={expected}, actual={actual}"
        )

    print(f"{label}: PASS")


def main():
    if not os.environ.get("CLOUDFLARE_API_TOKEN"):
        raise RuntimeError("Cloudflare token missing")

    try:
        rows(
            "INSERT INTO product_monitoring "
            "(asin, priority, next_check_at, updated_at) "
            f"VALUES ('{ASIN}', 'HOT', '{PAST}', '{PAST}')"
        )

        claim("worker-a")
        assert_owner("worker-a", "FIRST_CLAIM")

        claim("worker-b")
        assert_owner("worker-a", "SECOND_CLAIM_BLOCKED")

        rows(
            "UPDATE product_monitoring "
            f"SET lease_until='{PAST}' "
            f"WHERE asin='{ASIN}'"
        )

        claim("worker-b")
        assert_owner("worker-b", "EXPIRED_LEASE_RECOVERED")

        print("V15_D1_LEASE_TEST_OK")

    finally:
        try:
            rows(
                "DELETE FROM product_monitoring "
                f"WHERE asin='{ASIN}'"
            )
            print("V15_TEST_ROW_CLEANED")
        except Exception as exc:
            print(
                f"V15_TEST_CLEANUP_FAILED: {exc}",
                file=sys.stderr,
            )
            raise


if __name__ == "__main__":
    main()
