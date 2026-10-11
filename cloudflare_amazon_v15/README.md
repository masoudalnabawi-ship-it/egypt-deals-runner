# Amazon V15 — Independent Cloudflare Storage

This directory contains the initial V15 D1 schema.

Safety rules:
- Never apply V15 migrations to the V14 production database.
- Never modify Noon.
- Create a separate V15 D1 database before deployment.
- Price observations must come from validated Amazon evidence.
- Historical prices require sufficient independent observations.
- Delivery must be idempotent across retries.
- Ambiguous Telegram delivery must not be retried blindly.
- V15 must pass end-to-end tests before production cutover.

Status: Schema prepared. No production deployment.
