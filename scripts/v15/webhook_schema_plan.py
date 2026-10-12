"""Build safe, additive D1 migration based on existing table columns.

Never drops or rewrites tables. Existing tables are handled via separate
ALTER statements; new tables are created idempotently.
"""
from pathlib import Path

schema = Path('cloudflare/v15-telegram-webhook/schema.sql').read_text()
# SQLite IF NOT EXISTS is not an ALTER TABLE migration. We only add columns
# with explicit ALTER after inspecting D1; for now require clean tables.
# This script intentionally stops rather than risking an incorrect migration.
raise SystemExit('MIGRATION_REQUIRES_SCHEMA_INSPECTION: preflight first; no database changes made')
