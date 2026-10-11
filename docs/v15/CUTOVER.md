# Amazon V15 — Production Cutover

## Goal
Amazon V15 becomes the ONLY active Amazon deals pipeline.

## Mandatory readiness checks
- Real Amazon Egypt verification works.
- Reference prices are independently verified.
- Real Playwright screenshots are captured.
- Normal: verified discount below 50%.
- Ultra: verified discount from 50% to 100%.
- Telegram delivery is protected against duplicates.
- Competitor signals are persisted.
- End-to-end tests pass.

## Cutover order
1. Deploy V15 separately.
2. Run end-to-end tests without production Telegram delivery.
3. Verify V15 health and evidence.
4. Disable legacy Amazon schedules and workers.
5. Enable V15 production delivery.
6. Confirm exactly one Amazon delivery pipeline is active.
7. Monitor failures and duplicate attempts.

## Safety
- Do not modify Noon.
- Do not delete historical data.
- Preserve rollback configuration.
- Never activate V15 and legacy Amazon delivery simultaneously.
