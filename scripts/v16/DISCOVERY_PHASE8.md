# V16 phase 8: real listing discovery (experimental)

Run `python scripts/v16/live_discovery.py` in an environment with Playwright + Chromium.
This fetches at most two Amazon Egypt listing pages and records up to 40 candidate
ASINs without any D1 calls. Listing discounts are unverified hints. Amazon can
change markup, challenge automation, or show no cards; zero candidates is possible.
This stage DOES NOT yet inspect product prices, capture product screenshots,
send Telegram alerts, or run on a schedule. Those must be integrated and tested
before calling this a live deal alert bot. Never bypass access challenges.
