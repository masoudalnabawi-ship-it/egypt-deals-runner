V13 review media upgrade

- Sends a real Playwright screenshot of the live Amazon/Noon product page first.
- Falls back to the store product image if screenshot capture fails.
- Falls back to verified text if all media fails.
- Fixes literal \n appearing in Telegram captions.
- Reorganizes review details in Arabic: current/old/effective price, real discount,
  score, confidence, ASIN/SKU, category, cross-store comparison, verification reasons,
  and review time.
- Keeps the existing publish/reject buttons.
