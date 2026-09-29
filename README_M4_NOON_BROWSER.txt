V13 Milestone 4 - Noon browser fallback

Why:
- Milestone 3 proved the Noon catalog endpoint is blocked with HTTP 403 from the current GitHub/cloud egress.
- The browser fallback renders the public Egypt storefront path (/egypt-en/) only after direct+proxy fail.
- It does not solve or bypass CAPTCHAs; protected pages are rejected.

Transport ladder for Noon:
1) direct catalog/storefront
2) existing cloud proxy
3) Playwright Chromium -> public Egypt storefront

The existing Live Probe will exercise the fallback immediately after push.
