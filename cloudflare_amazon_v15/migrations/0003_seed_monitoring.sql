-- Register first real Amazon Egypt product for V15 monitoring.
-- Do not overwrite an existing monitoring schedule.

INSERT OR IGNORE INTO product_monitoring (
    asin,
    priority,
    next_check_at,
    consecutive_errors,
    updated_at
)
VALUES (
    'B0DK4Z4GPJ',
    'ACTIVE',
    '2026-01-01T00:00:00+00:00',
    0,
    '2026-10-11T00:00:00+00:00'
);
