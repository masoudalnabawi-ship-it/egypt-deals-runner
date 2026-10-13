"""Bounded, read-only live discovery of Amazon Egypt listing candidates.

No Cloudflare D1 usage, no Telegram sends, no price claims based on listing alone.
Requires Playwright and a browser in the execution environment. Access challenges
are respected (no CAPTCHA bypass). Results are candidates for product verification.
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ASIN = re.compile(r'^[A-Z0-9]{10}$')
DEFAULT_PAGES = [
    'https://www.amazon.eg/gp/goldbox',
    'https://www.amazon.eg/deals',
]


def extract_cards(page, *, limit=50):
    """Extract only ASINs and visible listing hints; never fabricate discounts."""
    rows = page.locator('[data-asin]').evaluate_all('''nodes => nodes.map(n => ({
      asin: (n.getAttribute('data-asin') || '').trim().toUpperCase(),
      text: (n.innerText || '').slice(0, 600)
    }))''')
    out = []
    seen = set()
    for row in rows:
        asin = row.get('asin', '')
        if not ASIN.fullmatch(asin) or asin in seen:
            continue
        seen.add(asin)
        text = row.get('text', '')
        # A listing discount is only a hint; product-page inspection is required.
        matches = re.findall(r'(?:-|خصم\s*)\s*(\d{1,2})\s*%', text)
        pct = max((int(x) for x in matches), default=None)
        if pct is not None and pct < 50:
            continue
        out.append({'asin': asin, 'url': f'https://www.amazon.eg/dp/{asin}',
                    'listing_discount_hint': pct, 'source': page.url})
        if len(out) >= limit:
            break
    return out


def discover(*, pages=None, max_pages=2, max_candidates=40, browser_factory=None):
    if not 1 <= max_pages <= 3 or not 1 <= max_candidates <= 100:
        raise ValueError('Unsafe discovery bounds')
    pages = pages or DEFAULT_PAGES
    if any(not u.startswith('https://www.amazon.eg/') for u in pages):
        raise ValueError('Only Amazon Egypt listing pages are allowed')
    if browser_factory is None:
        from playwright.sync_api import sync_playwright
        browser_factory = sync_playwright
    found = {}
    with browser_factory() as playwright:
        browser = playwright.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            context = browser.new_context(locale='ar-EG', timezone_id='Africa/Cairo')
            for url in pages[:max_pages]:
                tab = context.new_page()
                try:
                    tab.goto(url, wait_until='domcontentloaded', timeout=25000)
                    title = tab.title().lower()
                    if any(x in title for x in ('captcha', 'robot check', 'sign in')):
                        print('V16_DISCOVERY_ACCESS_CHALLENGE', url, flush=True)
                        continue
                    for item in extract_cards(tab, limit=max_candidates):
                        found.setdefault(item['asin'], item)
                        if len(found) >= max_candidates:
                            break
                except Exception as exc:
                    print('V16_DISCOVERY_PAGE_FAILED', url, type(exc).__name__, flush=True)
                finally:
                    tab.close()
                if len(found) >= max_candidates:
                    break
        finally:
            browser.close()
    return list(found.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='v16-discovery-candidates.json')
    parser.add_argument('--max-pages', type=int, default=2)
    parser.add_argument('--max-candidates', type=int, default=40)
    args = parser.parse_args()
    items = discover(max_pages=args.max_pages, max_candidates=args.max_candidates)
    result = {'captured_at': datetime.now(timezone.utc).isoformat(),
              'status': 'UNVERIFIED_LISTING_CANDIDATES', 'candidates': items}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('V16_DISCOVERY_CANDIDATES', len(items), 'D1_CALLS=0', flush=True)


if __name__ == '__main__':
    main()
