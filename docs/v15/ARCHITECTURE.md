# Amazon V15 — Egypt Deals Intelligence

## Scope
Amazon Egypt only. Noon remains independent and unchanged.

## Ultra Policy
- Minimum verified real discount: 50%.
- Eligible range: 50% to 100%.
- Never publish an unverified discount.
- Display the actual verified discount.
- Apply confidence and price-validity checks.

## Architecture
1. Discovery
2. Product Verification
3. Discount Calculation
4. Quality Scoring
5. Duplicate Detection
6. Delivery Queue
7. Telegram Publishing
8. Monitoring and Recovery

## Delivery States
- discovered
- verifying
- verified
- delivering
- sent
- rejected
- delivery_unknown

## Delivery Safety
- Persist delivery attempts.
- Preserve Telegram message IDs.
- Do not automatically retry uncertain sends.
- Never resend a previously confirmed delivery.
- Keep an auditable event history.

## Deployment
- Build and test V15 independently.
- Keep V14 production unchanged.
- Preserve existing sent history.
- Deploy only after integration tests pass.
- Maintain a rollback path.
