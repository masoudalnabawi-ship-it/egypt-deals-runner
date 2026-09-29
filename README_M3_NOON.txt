V13 Milestone 3 - Noon fast-path

Changes:
- Noon discovery now uses the lightweight public catalog JSON API instead of rendered storefront pages.
- Requests send x-locale: en-eg and Egypt storefront context.
- Noon verification resolves SKU directly through the product catalog API.
- Search parser handles hits[] with list/sale prices and canonical Egypt URLs.
- Safety guard drops payloads that explicitly identify UAE/Dubai market.
- Amazon verifier also gains extra live-price fallbacks.
- Adds Noon JSON API unit tests.

After push, the existing V13 Live Probe workflow will run automatically.
