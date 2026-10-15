"""V16 bounded multi-source candidate discovery; never treats hints as verified offers."""
import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Search pages are discovery HINTS only. Every candidate is verified on its own
# Amazon product page before being accepted; URL filters are not trusted.
SOURCES = (
    'https://www.amazon.eg/s?k=electronics&pct-off=50-99',
    'https://www.amazon.eg/s?k=home+and+kitchen&pct-off=50-99',
    'https://www.amazon.eg/s?k=beauty&pct-off=50-99',
    'https://www.amazon.eg/s?k=fashion&pct-off=50-99',
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
        text: [
            (n.innerText || '').slice(0, 3000),
            ...Array.from(n.querySelectorAll(
                '.savingsPercentage, [class*="savingsPercentage"]'
            )).map(e => e.textContent || '')
        ].join(' ')
    }))''')
    result, seen = [], set()
    for row in rows:
        asin = row.get('asin', '')
        if not ASIN.fullmatch(asin) or asin in seen:
            continue
        seen.add(asin)
        # Amazon listings may contain invisible bidirectional Unicode marks.
        text = re.sub(r'[\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069]', '',
                      row.get('text', ''))
        hints = [int(a or b) for a, b in DISCOUNT.findall(text)]
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
    found, errors, source_stats = {}, [], []
    with browser_factory() as playwright:
        browser = playwright.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            context = browser.new_context(locale='ar-EG', timezone_id='Africa/Cairo')
            for url in pages[:max_pages]:
                tab = context.new_page()
                try:
                    response = None
                    challenge = False

                    for attempt in range(2):
                        try:
                            response = tab.goto(
                                url,
                                wait_until='domcontentloaded',
                                timeout=25000
                            )
                        except Exception:
                            if attempt == 0:
                                time.sleep(2)
                                continue
                            raise

                        title = tab.title().lower()

                        if any(x in title for x in (
                            'captcha', 'robot check', 'sign in'
                        )):
                            errors.append({
                                'source': url,
                                'reason': 'ACCESS_CHALLENGE'
                            })
                            challenge = True
                            break

                        if response and response.status == 503 and attempt == 0:
                            time.sleep(2)
                            continue

                        break

                    if challenge:
                        continue

                    if response and response.status >= 400:
                        errors.append({
                            'source': url,
                            'reason': 'HTTP_' + str(response.status)
                        })
                        continue
                    # Diagnose empty Amazon listings without logging page contents.
                    diagnostics = tab.evaluate('''() => ({
                        title: document.title.slice(0, 100),
                        asin_nodes: document.querySelectorAll('[data-asin]').length,
                        search_cards: document.querySelectorAll('[data-component-type="s-search-result"]').length,
                        product_links: document.querySelectorAll('a[href*="/dp/"]').length,
                        body_length: document.body ? document.body.innerText.length : 0
                    })''')
                    print('V16_PAGE_DIAGNOSTICS', json.dumps({
                        'source': url,
                        'http_status': response.status if response else None,
                        **diagnostics
                    }, ensure_ascii=False), flush=True)
                    # Collect per-source metrics BEFORE global ASIN dedup/truncation.
                    cards = extract_cards(tab, limit=max_candidates)
                    if response and response.status >= 400:
                        errors.append({'source': url, 'reason': 'HTTP_' + str(response.status)})
                    elif not cards:
                        errors.append({'source': url, 'reason': 'NO_PRODUCT_CARDS'})
                    source_stats.append({
                        'source': url,
                        'cards': len(cards),
                        'discount_hints': sum(x.get('listing_discount_hint') is not None for x in cards),
                        'discount_50_plus': sum((x.get('listing_discount_hint') or 0) >= 50 for x in cards),
                    })
                    for item in cards:
                        asin = item['asin']
                        prior = found.get(asin)
                        if prior is None or (item.get('listing_discount_hint') or 0) > (prior.get('listing_discount_hint') or 0):
                            found[asin] = item
                except Exception as exc:
                    errors.append({'source': url, 'reason': type(exc).__name__})
                finally:
                    tab.close()
        finally:
            browser.close()
    return {'captured_at': datetime.now(timezone.utc).isoformat(),
            'status': 'UNVERIFIED_LISTING_CANDIDATES',
            'sources_checked': min(max_pages, len(pages)), 'errors': errors,
            'source_stats': source_stats,
            'candidates': sorted(found.values(), key=lambda row: (row.get('listing_discount_hint') is None, -(row.get('listing_discount_hint') or 0)))[:max_candidates]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='v16-discovery-candidates.json')
    parser.add_argument('--max-pages', type=int, default=4)
    parser.add_argument('--max-candidates', type=int, default=80)
    args = parser.parse_args()
    report = discover(args.max_pages, args.max_candidates)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    hints = [x['listing_discount_hint'] for x in report['candidates']
             if x.get('listing_discount_hint') is not None]
    print('V16_SOURCE_STATS', json.dumps(report['source_stats'], ensure_ascii=False), flush=True)
    print('V16_DISCOUNT_STATS', {
        'total': len(report['candidates']),
        'with_discount_hint': len(hints),
        'discount_50_plus': sum(x >= 50 for x in hints),
        'discount_90_plus': sum(x >= 90 for x in hints),
        'without_discount_hint': len(report['candidates']) - len(hints),
    }, flush=True)
    print('V16_DISCOVERY_CANDIDATES', len(report['candidates']), 'ERRORS', len(report['errors']), 'D1_CALLS=0', flush=True)


if __name__ == '__main__':
    main()
