# Egypt Deals V14 — Cloudflare Edition

Cloud-native port of V14 preserving the core safety policy:

- Noon is **always Normal** and can never enter Amazon Ultra.
- Amazon Ultra requires verified effective/real discount **>=65%** and confidence **>=0.76**.
- Amazon **>=75%** gets maximum priority only after strong verification.
- Explicit product coupons can reduce effective price; bank/card/installment offers are excluded.
- D1 replaces local SQLite.
- Cron only enqueues one cycle per minute; a single-concurrency Cloudflare Queue performs discovery, verification, and delivery so the Free-plan Cron CPU limit is not used for heavy work.
- Browser Run is reserved for strong Amazon fallback verification and suspicious/extreme Noon price confirmation, with a 9-minute/day software budget under the 10-minute Free allowance.
- Telegram callbacks use webhooks rather than a long-running polling loop.

`install_cloudflare_v14.sh` handles queue creation, migrations, secure secret import, checks, deployment, Telegram webhook registration, one controlled production cycle, health check, commit, and push.
