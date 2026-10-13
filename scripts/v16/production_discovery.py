"""V16 bounded multi-source candidate discovery; never treats hints as verified offers."""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

SOURCES = (
    'https://www.amazon.eg/gp/goldbox',
    'https://www.amazon.eg/deals',
    'https://www.amazon.eg/gp/bestsellers',
    'https://www.amazon.eg/gp/new-releases',
)
ASIN = re.compile(r'^[A-Z0-9]{10}$')
DISCOUNT = re.compile(r'(?:خصم\s*|[-−]\s*)(100|\d{1,2})\s*%|(?:وفر|توفير)\s*(100|\d{1,2})\s*%', re.I)


def valid_source(url):
    p = urlparse(url)
    return p.scheme == 'https' and p.netloc == 'www.amazon.eg' and p.path.startswith('/') and not p.username and not p.password


def extract_cards(page, limit=100):
    rows = page.locator('[data-asin]').evaluate_all('''nodes => nodes.map(n => ({
        asin: (n.getAttribute('data-asin') || '').trim().toUpperCase(),
        text: (n.innerText || '').slice(0, 900)
    }))''')
    result, seen = [], set()
    for row in rows:
        asin = row.get('asin', '')
        if not ASIN.fullmatch(asin) or asin in seen:
            continue
        seen.add(asin)
        hints = [int(a or b) for a, b in DISCOUNT.findall(row.get('text', ''))]
        pct = max((v for v in hints if 5 <= v <= 100), default=None)
        result.append({'asin': asin, 'url': f'https://www.amazon.eg/dp/{asin}',
                       'listing_discount_hint': pct, 'source': page.url})
        if len(result) >= limit:
            break
    return result


def discover(max_pages=4, max_candidates=80, pages=None, browser_factory=None):
    if not 1 <= max_pages <= 8 or not 1 <= max_candidates <= 150:
        raise ValueError('Unsafe bounds')
    pages = tuple(pages or SOURCES)
    if not all(valid_source(u) for u in pages):
        raise ValueError('Only https://www.amazon.eg/ allowed')
    if browser_factory is None:
        from playwright.sync_api import sync_playwright
        browser_factory = sync_playwright
    found, errors = {}, []
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
                        errors.append({'source': url, 'reason': 'ACCESS_CHALLENGE'})
                        continue
                    for item in extract_cards(tab, limit=max_candidates):
                        found.setdefault(item['asin'], item)
                        if len(found) >= max_candidates:
                            break
                except Exception as exc:
                    errors.append({'source': url, 'reason': type(exc).__name__})
                finally:
                    tab.close()
                if len(found) >= max_candidates:
                    break
        finally:
            browser.close()
    return {'captured_at': datetime.now(timezone.utc).isoformat(),
            'status': 'UNVERIFIED_LISTING_CANDIDATES',
            'sources_checked': min(max_pages, len(pages)), 'errors': errors,
            'candidates': sorted(found.values(), key=lambda row: (row['listing_discount_hint'] is None, -(row['listing_discount_hint'] or 0)))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='v16-discovery-candidates.json')
    parser.add_argument('--max-pages', type=int, default=4)
    parser.add_argument('--max-candidates', type=int, default=80)
    args = parser.parse_args()
    report = discover(args.max_pages, args.max_candidates)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('V16_DISCOVERY_CANDIDATES', len(report['candidates']), 'ERRORS', len(report['errors']), 'D1_CALLS=0', flush=True)


if __name__ == '__main__':
    main()
