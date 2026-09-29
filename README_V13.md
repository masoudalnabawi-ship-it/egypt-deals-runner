# Egypt Deals V13

Clean rebuild for **Amazon Egypt + Noon Egypt only**.

## Design

`Discovery -> Normalize/Deduplicate -> Verification -> Intelligence -> Lane -> Delivery`

V13 deliberately keeps one HTTP layer for both discovery and verification, so Direct/Cloud Proxy behavior cannot diverge. SQLite is the durable queue; worker ownership is lease-based, and Normal/Ultra delivery lanes are isolated.

## Intelligence

A deal is not promoted solely because a store prints a large percentage. V13 combines:

- live product-page verification;
- current vs crossed-out price;
- coupon/effective price;
- recent local price history;
- cross-store Amazon/Noon title/model matching;
- flash/anomaly signals;
- confidence scoring;
- accessory/extreme-price defenses.

A raw 50% result is only given **Ultra verification priority**. It becomes **Ultra delivery** only after confidence gates are met.

## Discovery diversity

Amazon and Noon have broad category surfaces. `AdaptiveSurfaceSelector` uses:
- forced exploration;
- historical candidate yield;
- source freshness;
- failure penalties;
- per-batch category diversity.

This prevents the scanner from converging on one easy category.

## Environment

Existing secrets are supported:

- `TELEGRAM_BOT_TOKEN`
- `CLOUD_API_URL`
- `CLOUD_API_KEY`
- `AMAZON_NORMAL_REVIEW_CHAT_ID` (or `REVIEW_CHAT_ID`)
- `AMAZON_REVIEW_GROUP_ID`

Optional V13/Noon overrides:
- `V13_NORMAL_REVIEW_CHAT_ID`
- `V13_ULTRA_REVIEW_CHAT_ID`
- `NOON_NORMAL_REVIEW_CHAT_ID`
- `NOON_ULTRA_REVIEW_CHAT_ID`

Useful tuning:
- `V13_DB_PATH=.runtime_state/v13.db`
- `V13_DISCOVERY_INTERVAL=20`
- `V13_VERIFY_WORKERS_PER_STORE=2`
- `V13_SURFACE_BATCH_SIZE=5`
- `V13_EXPLORATION_RATE=0.22`
- `V13_NORMAL_MIN_DISCOUNT=10`
- `V13_ULTRA_MIN_DISCOUNT=50`

## Test

```bash
PYTHONPATH=. python -m unittest discover -s tests/v13 -p 'test_*.py' -v
```

## Run

```bash
PYTHONPATH=. python scripts/run_v13.py
```

V12 is not modified by this bundle.

## Milestone 2: identity + live validation

V13 now uses structured product signatures (brand/model/capacity/RAM/size/pack count) before cross-store comparison. A 128GB product cannot be used as market evidence for a 256GB product, and conflicting model numbers are rejected.

`v13_live_probe.py` performs a **no-send** live check against Amazon Egypt and Noon Egypt using the exact same HTTP/failover and verifier code as production. It writes `v13-live-probe.json`, which makes parser/proxy regressions visible before Telegram delivery is enabled.

Delivery ordering balances both store and category over the recent six-hour window, so one easy source/category cannot monopolize the review feed.
