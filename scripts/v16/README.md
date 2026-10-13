# V16 Smart Deals Engine — Phase 1 (isolated prototype)

This branch adds a **pure, side-effect-free** deal intelligence module and tests.
It does not scan Amazon, query Cloudflare D1, send Telegram messages, change
schedules, or alter V14/V15 production. The `urgent_private_alert` flag is a
policy signal for eventual integration, **not** an actual notification.

The score is intentionally **out of 70** because rarity and independent
reliability cannot be honestly measured yet. Historical data is optional,
and unknown history must not block the 50–99% private-alert policy.

Next stages (not yet implemented): candidate discovery, real-time private alert
integration, historical price store, adaptive quota accounting, end-to-end tests.

## Phase 2 — candidate prioritization (isolated)

`candidate_discovery.prioritize` ranks **already supplied** candidate products
by displayed discount, puts 50–99% first, deduplicates ASINs, bounds the batch,
and limits per-category concentration. It has no network calls and **does not
actually discover Amazon listings or send Telegram alerts**. The next phase
must connect it to an authorized source and the live alert pipeline, with
end-to-end tests and quota measurements before production activation.

## Phase 3 — Flash Hunter alert policy (isolated)

`flash_hunter.prepare_private_alert` prepares private-only, clearly marked
unverified advertised-discount alerts for 50% to less than 100%, without
requiring historical prices. `LocalDeduplicator` is **in-memory only** and
not suitable for production. This phase **does not send Telegram messages**,
query Amazon, or change V15. Future integration must reuse V15's persistent
Telegram deduplication and transport, with live integration tests.

## Phase 4: verified report bridge (read-only)
`verified_alert_bridge.py` accepts a verified V15-style JSON report, calculates
V16 scoring and prepares an urgent private alert for advertised 50%–<100%.
It does **not** send Telegram messages, access Amazon, write D1, or change
production monitoring. V15's existing Telegram path remains untouched.
Run: `python scripts/v16/verified_alert_bridge.py path/to/verification.json`.
Production integration requires a separate reviewed change with live evidence.

## Phase 5: opt-in private Telegram transport (NOT deployed)
`private_telegram_transport.send_verified_private(report, enabled=True)` uses
V15's existing private Telegram sender and D1-backed dedup. It requires
`V16_PRIVATE_TELEGRAM_ENABLED=1`, existing V15 Telegram credentials, and an
explicit caller. It is **not** wired to any scheduled production workflow;
no live monitoring or delivery is claimed. D1 outages fail closed.
