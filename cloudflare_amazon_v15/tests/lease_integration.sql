-- V15 isolated lease integration test.
-- Uses a dedicated test ASIN, never a real monitored product.

BEGIN TRANSACTION;

INSERT INTO product_monitoring (
    asin,
    priority,
    next_check_at,
    updated_at
)
VALUES (
    'V15LEASE01',
    'HOT',
    '2026-01-01T00:00:00+00:00',
    '2026-01-01T00:00:00+00:00'
)
ON CONFLICT(asin) DO UPDATE SET
    priority = 'HOT',
    next_check_at = '2026-01-01T00:00:00+00:00',
    lease_owner = NULL,
    lease_until = NULL,
    updated_at = '2026-01-01T00:00:00+00:00';

UPDATE product_monitoring
SET lease_owner = 'worker-a',
    lease_until = '2099-01-01T00:00:00+00:00',
    updated_at = '2026-10-11T12:00:00+00:00'
WHERE asin = 'V15LEASE01'
  AND next_check_at <= '2026-10-11T12:00:00+00:00'
  AND (
      lease_until IS NULL
      OR lease_until <= '2026-10-11T12:00:00+00:00'
  );

SELECT
    'FIRST_CLAIM' AS test,
    lease_owner
FROM product_monitoring
WHERE asin = 'V15LEASE01';

UPDATE product_monitoring
SET lease_owner = 'worker-b',
    lease_until = '2099-01-01T00:00:00+00:00'
WHERE asin = 'V15LEASE01'
  AND next_check_at <= '2026-10-11T12:00:00+00:00'
  AND (
      lease_until IS NULL
      OR lease_until <= '2026-10-11T12:00:00+00:00'
  );

SELECT
    'SECOND_CLAIM_BLOCKED' AS test,
    lease_owner
FROM product_monitoring
WHERE asin = 'V15LEASE01';

UPDATE product_monitoring
SET lease_until = '2026-01-01T00:00:00+00:00'
WHERE asin = 'V15LEASE01';

UPDATE product_monitoring
SET lease_owner = 'worker-b',
    lease_until = '2099-01-01T00:00:00+00:00'
WHERE asin = 'V15LEASE01'
  AND next_check_at <= '2026-10-11T12:00:00+00:00'
  AND (
      lease_until IS NULL
      OR lease_until <= '2026-10-11T12:00:00+00:00'
  );

SELECT
    'EXPIRED_LEASE_RECOVERED' AS test,
    lease_owner
FROM product_monitoring
WHERE asin = 'V15LEASE01';

DELETE FROM product_monitoring
WHERE asin = 'V15LEASE01';

COMMIT;
