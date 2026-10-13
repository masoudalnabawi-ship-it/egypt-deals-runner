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
