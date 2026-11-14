#!/usr/bin/env python3
"""Daily, non-invasive Amazon.eg used offer CANDIDATE watcher.

The Resale storefront may list general product links without proving a used
listing. Only a single product page's used-specific section with a numeric
price can trigger a PRIVATE human-review message. No checkout/stock claims.
No CAPTCHA or anti-bot bypass, no retries after HTTP 429, no public posting.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from probe_transport import fetch_json_via_curl

BASE = 'https://egypt-amazon-used-probe.masoud-amazon-eg.workers.dev/'
OUT = Path(__file__).resolve().parent / 'reports' / 'amazon_used_private_watch.json'
APPROVED_USED_SELECTORS = {
    '#usedBuyBox', '#usedBuyBoxPrice', '#usedBuyBox .a-price .a-offscreen',
    '#usedAccordionRow', '#usedAccordionRow .a-price .a-offscreen',
    '#buybox-used', '#buybox-used .a-price .a-offscreen',
    '#usedOffer', '#usedOffer .a-price .a-offscreen',
}
CONDITIONS = {
    'USED_LIKE_NEW': 'مستعمل – كالجديد',
    'USED_VERY_GOOD': 'مستعمل – جيد جدًا',
    'USED_GOOD': 'مستعمل – جيد',
    'USED_ACCEPTABLE': 'مستعمل – مقبول',
    'USED_UNSPECIFIED': 'مستعمل – الحالة التفصيلية غير محددة',
}


def valid_asin(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[A-Z0-9]{10}', value))


def valid_product_link(value, asin):
    try:
        u = urlsplit(value)
        return (u.scheme == 'https' and u.hostname == 'www.amazon.eg'
                and not u.username and not u.password and not u.port
                and u.path.rstrip('/') == '/dp/' + asin
                and not u.query and not u.fragment)
    except (TypeError, ValueError):
        return False


def candidates_from_source(report):
    if report.get('status') != 'LINK_AUDIT_DIAGNOSTIC_ONLY':
        return []
    if report.get('captcha_text_signal'):
        return []
    products = []
    for obj in report.get('product_candidates', []):
        if not isinstance(obj, dict):
            continue
        asin = obj.get('asin')
        if valid_asin(asin) and valid_product_link(obj.get('url'), asin):
            if asin not in products:
                products.append(asin)
    return products[:20]


def evaluate_product(data, asin):
    """Accept only one price explicitly extracted from used-specific DOM section."""
    if not isinstance(data, dict) or data.get('asin') != asin:
        return None
    if data.get('status') != 'PRODUCT_PAGE_USED_CANDIDATE_NEEDS_VERIFICATION':
        return None
    page = data.get('product_page') or {}
    if page.get('http') != 200 or page.get('blocked'):
        return None
    # Amazon can prefix /dp/<ASIN> with a product slug or append a harmless ref.
    # Accept only the very same ASIN on the exact amazon.eg host.
    if page.get('final_url'):
        try:
            final = urlsplit(page['final_url'])
            path_ok = bool(re.search(r'/(?:dp|gp/product)/' + re.escape(asin) + r'(?:/|$)', final.path, re.I))
            final_ok = (final.scheme == 'https' and final.hostname == 'www.amazon.eg'
                        and not final.username and not final.password and not final.port
                        and path_ok)
        except (TypeError, ValueError):
            final_ok = False
        if not final_ok:
            return None
    entries = data.get('product_page_used_offers') or []
    if not isinstance(entries, list):
        return None
    entries = [x for x in entries if isinstance(x, dict)]
    options = []
    for x in entries:
        price = x.get('price')
        cond = x.get('condition')
        if (x.get('selector') in APPROVED_USED_SELECTORS
                and x.get('status') == 'PRODUCT_PAGE_USED_PRICE_CANDIDATE'
                and isinstance(price, (int, float)) and not isinstance(price, bool)
                and 0 < price < 1000000 and cond in CONDITIONS):
            options.append(x)
    if not options:
        return None
    best = min(options, key=lambda x: x['price'])
    new_price = data.get('new_price')
    if (not isinstance(new_price, (int, float)) or isinstance(new_price, bool)
            or not 0 < new_price < 1000000 or data.get('new_price_status') != 'OBSERVED'):
        new_price = None
    title = ''
    for row in page.get('elements') or []:
        if isinstance(row, dict) and row.get('selector') == '#productTitle':
            samples = row.get('samples') or []
            if samples:
                title = re.sub(r'\s+', ' ', str(samples[0])).strip()[:180]
            break
    used_price = round(float(best['price']), 2)
    saving = round((1-used_price/new_price)*100, 1) if new_price and used_price < new_price else None
    return {
        'asin': asin,
        'product_url': 'https://www.amazon.eg/dp/' + asin,
        'title': title or 'منتج أمازون ' + asin,
        'condition': best['condition'],
        'used_price_candidate_egp': used_price,
        'primary_price_observed_egp': new_price,
        'price_gap_candidate_pct': saving,
        'used_price_verified_checkout': False,
        'stock_verified': False,
        'human_review_required': True,
    }


def send_private_candidate(item, chat, bot):
    if not re.fullmatch(r'-100\d{6,20}', chat):
        raise ValueError('AMAZON_REVIEW_GROUP_NOT_VALID_PRIVATE_CHAT_ID')
    if not re.fullmatch(r'\d{5,12}:[A-Za-z0-9_-]{30,90}', bot):
        raise ValueError('TELEGRAM_BOT_TOKEN_INVALID_FORMAT')
    lines = [
        '♻️ أمازون مصر | مرشح مستعمل للمراجعة فقط',
        '📦 ' + item['title'],
        '🔖 ASIN: ' + item['asin'],
        '🏷️ الحالة الظاهرة: ' + CONDITIONS[item['condition']],
        '💰 سعر مستعمل مرصود: ' + f"{item['used_price_candidate_egp']:,.2f}" + ' جنيه',
    ]
    if item['primary_price_observed_egp'] is not None:
        lines.append('🛍️ سعر العرض الأساسي المرصود: ' + f"{item['primary_price_observed_egp']:,.2f}" + ' جنيه')
    if item['price_gap_candidate_pct'] is not None:
        lines.append('📉 فرق السعر الأولي (ليس خصمًا مؤكّدًا): ' + str(item['price_gap_candidate_pct']) + '%')
    lines.extend([
        '⚠️ مرشح فقط: البائع والتوفر والسعر عند الشراء لم يتم التحقق منهم.',
        '🔒 للمراجعة الخاصة فقط؛ لا نشر عام.',
        item['product_url'],
    ])
    # Verify the destination is a private GROUP, not an accidentally configured channel.
    check = json.dumps({'chat_id': chat}).encode('utf-8')
    verify = Request('https://api.telegram.org/bot' + bot + '/getChat',
                     data=check, headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(verify, timeout=20) as response:
        info = json.loads(response.read(4000))
    group = info.get('result') or {}
    if (info.get('ok') is not True or group.get('type') not in ('group','supergroup')
            or group.get('username')):
        raise ValueError('AMAZON_REVIEW_DESTINATION_NOT_PRIVATE_GROUP')
    payload = json.dumps({'chat_id': chat, 'text': '\n'.join(lines),
                          'disable_web_page_preview': True}, ensure_ascii=False).encode('utf-8')
    req = Request('https://api.telegram.org/bot' + bot + '/sendMessage',
                  data=payload, headers={'Content-Type': 'application/json'}, method='POST')
    # No retry: if the API response is uncertain, do not risk duplicate private alerts.
    with urlopen(req, timeout=25) as response:
        result = json.loads(response.read(2000))
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise ValueError('TELEGRAM_PRIVATE_CANDIDATE_NOT_CONFIRMED')
    return True


def main():
    key = os.environ.get('PROBE_KEY', '').strip()
    if not key:
        raise SystemExit('AMAZON_USED_PROBE_KEY_MISSING')
    record = {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'source_url': 'https://www.amazon.eg/b?node=27972173031',
        'status': 'NOT_STARTED', 'candidate_product_count': 0,
        'product_pages_requested': 0, 'used_candidate_eligible': False,
        'private_alert_sent': False, 'public_posting_enabled': False,
        'verified_checkout_offers': 0,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        try:
            source = fetch_json_via_curl(BASE + '?mode=resale_link_audit_v12', key)
        except (HTTPError, URLError, ValueError, TimeoutError) as ex:
            record['status'] = 'SOURCE_UNAVAILABLE'
            record['error_type'] = type(ex).__name__
            return record
        record['source_status'] = str(source.get('status', 'UNKNOWN'))[:70]
        record['source_http'] = source.get('source_http')
        products = candidates_from_source(source)
        record['candidate_product_count'] = len(products)
        if not products:
            record['status'] = 'NO_VALID_RESALE_PRODUCT_LINKS'
            return record
        # Single product page per DAILY run. Rotate deterministically over source candidates.
        # Do not fetch offer-listing, do not bypass HTTP 429 or CAPTCHA.
        ordinal = datetime.now(timezone.utc).date().toordinal()
        asin = products[ordinal % len(products)]
        record['asin_checked'] = asin
        record['product_pages_requested'] = 1
        try:
            data = fetch_json_via_curl(BASE + '?' + urlencode({'asin': asin, 'main_only':'1'}), key)
        except (HTTPError, URLError, ValueError, TimeoutError) as ex:
            record['status'] = 'PRODUCT_REQUEST_UNAVAILABLE'
            record['error_type'] = type(ex).__name__
            return record
        record['product_status'] = str(data.get('status', 'UNKNOWN'))[:80]
        if data.get('status') in ('PRODUCT_RATE_LIMITED', 'BLOCKED_CAPTCHA'):
            record['status'] = 'AMAZON_ACCESS_LIMITED_NO_RETRY'
            return record
        item = evaluate_product(data, asin)
        if not item:
            record['status'] = 'NO_USED_SPECIFIC_PRICE_EVIDENCE'
            return record
        record['used_candidate_eligible'] = True
        record['candidate'] = item
        bot = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
        chat = os.environ.get('AMAZON_USED_REVIEW_CHAT_ID', '').strip()
        if not bot or not chat:
            record['status'] = 'PRIVATE_REVIEW_SETTINGS_MISSING'
            return record
        try:
            send_private_candidate(item, chat, bot)
        except (HTTPError, URLError, TimeoutError, ValueError) as ex:
            record['status'] = 'PRIVATE_REVIEW_SEND_FAILED'
            record['error_type'] = type(ex).__name__
            return record
        record['private_alert_sent'] = True
        record['status'] = 'PRIVATE_USED_CANDIDATE_SENT_UNVERIFIED'
        return record
    finally:
        OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print('AMAZON_USED_WATCH:', record['status'],
              'LINK_CANDIDATES:',record['candidate_product_count'],
              'PRODUCT_PAGES:',record['product_pages_requested'],
              'USED_PRICE_CANDIDATE:',record['used_candidate_eligible'],
              'PRIVATE_ALERT:',record['private_alert_sent'],flush=True)

if __name__ == '__main__':
    main()
