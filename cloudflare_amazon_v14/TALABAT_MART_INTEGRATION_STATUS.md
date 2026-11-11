# Talabat Mart integration — safety-first status

**NOT LIVE / NOT CONNECTED.** The repository does not include a verified, authorized, location-specific Talabat Mart offer source. The new `src/talabat_mart.ts` is a validated offer adapter, not a scraper or Telegram publisher.

- Threshold: **40–99%** (calculated from observed current and original prices).
- Regional coverage: any explicitly observed supported delivery region; El Mahalla El Kubra is flagged as priority.
- Reject unavailable offers, untrusted domains, missing delivery region, stale observations (>15 minutes), invalid prices, and discounts outside the requested range.
- Next dependency: a legitimate data feed or independently verified public storefront that supplies product IDs, current and original prices, delivery region, availability and timestamps. Test El Mahalla El Kubra first, then enumerate *actually supported* regions.
- Then integrate the feed with a **separate** scheduled collector, D1 storage, verifier, deduplicated Telegram delivery, and per-region monitoring. Do not reuse Amazon's 65% gate or Noon delivery channel.

## Amazon changes

- Added 100 discount-filtered search surfaces across 20 additional product departments and 90/80/75/70/65 tiers.
- Added one bounded scan per discovery cycle with a 90% weighted rotation, reusing the existing URL deduplication and verification pipeline.
- Preserved the four local bicycle sources and their fast lane.

## Deployment and testing

- No live Worker or database has been modified.
- Static type checking requires installing `@cloudflare/workers-types` and the project dependencies on a supported environment. `workerd` is unsupported in native Android Termux.
- Run `npm ci && npm run typecheck && npm test` on GitHub Actions or a supported machine before deploying.
- Existing Amazon screenshot and publication logic remains on GitHub, not Cloudflare. This package does not modify that separate pipeline.
