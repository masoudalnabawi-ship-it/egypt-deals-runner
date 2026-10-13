-- V15 only: accelerate priority-aware due-product selection.
-- Apply to D1 only after validation and approval.
CREATE INDEX IF NOT EXISTS idx_v15_priority_due
ON product_monitoring(priority, next_check_at, asin);
