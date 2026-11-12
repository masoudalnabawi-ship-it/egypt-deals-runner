"""Send fresh, rechecked Talabat products to private Telegram review only.

No public-channel posting, no broken product link button.
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, parse_qsl, urlencode, urlunsplit

import requests
from playwright.sync_api import sync_playwright

REPORT = Path('reports/talabat_rechecked.json')
REVIEW_CHAT = '-1004375874566'
ROOT = 'https://www.talabat.com'
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
WORKER = os.getenv('REVIEW_WORKER_URL', '').rstrip('/')
MAX_ALERTS = 2 if os.getenv('TALABAT_FAST') == '1' else 5
PAGE_LIMIT = 3 if os.getenv('TALABAT_FAST') == '1' else 12

if not TOKEN or not WORKER:
    raise SystemExit('MISSING_TELEGRAM_BOT_TOKEN_OR_WORKER_URL')
if not REPORT.is_file():
    raise SystemExit('RECHECK_REPORT_MISSING')

session = requests.Session()
headers = {'Authorization': 'Bearer ' + TOKEN}

def valid_talabat(url, product=False):
    try:
        x = urlsplit(url)
        return (x.scheme == 'https' and x.hostname == 'www.talabat.com'
                and x.path.startswith('/egypt/grocery/')
                and (not product or '/product/' in x.path))
    except Exception:
        return False

def worker_post(endpoint, payload):
    r = session.post(WORKER + endpoint, json=payload, headers=headers, timeout=25)
    r.raise_for_status()
    x = r.json()
    if not x.get('ok'):
        raise RuntimeError('WORKER_'+endpoint+'_NOT_OK')
    return x

def offer_identity(item):
    branch = str(item['branch_id'])
    sku = str(item['sku'])
    price = float(item['live_price'])
    return hashlib.sha256(f'{branch}|{sku}|{price:.2f}'.encode()).hexdigest()[:32]

def card_photo(page, item, offer_id):
    """Find actual SKU-linked DOM card, ensure matching live price, screenshot it."""
    sku = str(item['sku'])
    if not re.fullmatch(r'[A-Za-z0-9_-]+', sku):
        return None
    source = str(item['source'])
    if not valid_talabat(source):
        return None
    price = float(item['live_price'])
    price_pattern = re.compile(r'(?<!\d)' + re.escape(f'{price:.2f}').replace(r'\.', r'[.,]') + r'(?!\d)')
    sku_pattern = re.compile(r'/s/' + re.escape(sku) + r'(?=$|[/?#])', re.I)

    out = Path('reports/talabat_review_proofs') / f'{offer_id}.png'
    out.parent.mkdir(parents=True, exist_ok=True)

    for index in range(1, PAGE_LIMIT + 1):
        p = urlsplit(source)
        query = [(k,v) for k,v in parse_qsl(p.query) if k != 'page']
        if index > 1:
            query.append(('page', str(index)))
        url = urlunsplit(p._replace(query=urlencode(query)))
        try:
            response = page.goto(url, wait_until='domcontentloaded', timeout=22000)
            if response is None or response.status >= 400:
                continue
            page.wait_for_timeout(700)
            locators = page.locator('a[href*="/s/"]')
            n = min(locators.count(), 200)
            for i in range(n):
                anchor = locators.nth(i)
                href = anchor.get_attribute('href', timeout=1500)
                if not href:
                    continue
                product_url = urljoin(ROOT, href)
                if not valid_talabat(product_url, product=True):
                    continue
                if not sku_pattern.search(urlsplit(product_url).path):
                    continue
                node = anchor
                for _ in range(5):
                    try:
                        text = node.inner_text(timeout=1300)
                        box = node.bounding_box(timeout=1300)
                        if (box and price_pattern.search(text)
                            and 160 <= box['width'] <= 1100
                            and 90 <= box['height'] <= 1250):
                            node.screenshot(path=str(out), timeout=10000, animations='disabled')
                            if out.exists() and out.stat().st_size > 4000:
                                return out, product_url
                    except Exception:
                        pass
                    node = node.locator('xpath=..')
        except Exception as e:
            print('CARD_PAGE_ERROR:', item['area'], sku, index, type(e).__name__, flush=True)
    return None

def send_photo_and_controls(item, photo, product_url, offer_id):
    now = int(time.time())
    p = worker_post('/reserve', {
        'id': offer_id,
        'title': str(item.get('title') or '')[:400],
        'area': str(item['area'])[:80],
        'sku': str(item['sku'])[:90],
        'price': float(item['live_price']),
        'discount': float(item['live_discount']),
        'product_url': product_url,
        'source_url': str(item['source']),
        'proof_at': now,
    })
    if not p.get('reserved'):
        print('ALREADY_REVIEWED:', item['area'], item['sku'], flush=True)
        return False

    caption = (f"🛒 طلبات مارت | {item['area']}\n"
               f"📦 {str(item.get('title') or '')[:150]}\n"
               f"💰 {float(item['live_price']):.2f} جنيه | 🔥 {float(item['live_discount']):.1f}%\n"
               "📸 صورة حقيقية للبطاقة والسعر عند الفحص\n"
               "✅ السعر والمخزون مطابقان لإعادة الفحص\n"
               "⚠️ التوصيل والسعر النهائي في السلة غير مؤكدين\n"
               "⏸️ النشر العام متوقف لحين إصلاح الروابط")
    with photo.open('rb') as file:
        r = session.post(f'https://api.telegram.org/bot{TOKEN}/sendPhoto',
                         data={'chat_id': REVIEW_CHAT, 'caption': caption[:1024]},
                         files={'photo': ('real_card.png', file, 'image/png')}, timeout=40)
    r.raise_for_status()
    resp = r.json()
    if not resp.get('ok'):
        raise RuntimeError('TELEGRAM_SEND_PHOTO_FAILED')

    message_id = int(resp['result']['message_id'])
    urls = worker_post('/attach', {'id': offer_id, 'message_id': message_id})
    markup = {'inline_keyboard': [
        [{'text': '❌ رفض العرض', 'url': urls['reject_url']}],
    ]}
    edit = session.post(f'https://api.telegram.org/bot{TOKEN}/editMessageReplyMarkup',
                        json={'chat_id': REVIEW_CHAT,
                              'message_id': message_id,
                              'reply_markup': markup}, timeout=25)
    edit.raise_for_status()
    if not edit.json().get('ok'):
        raise RuntimeError('REJECT_BUTTON_ATTACH_FAILED')
    print('PRIVATE_REVIEW_SENT:', item['area'], item['sku'], offer_id, flush=True)
    return True

records = json.loads(REPORT.read_text(encoding='utf-8'))
eligible = []
for item in records:
    try:
        if item.get('recheck_status') != 'PRICE_STOCK_CONFIRMED':
            continue
        if (float(item.get('live_price') or 0) <= 0 or
            float(item.get('live_stock') or 0) <= 0 or
            float(item.get('live_discount') or 0) < 40 or
            not valid_talabat(item.get('source', ''))):
            continue
        eligible.append(item)
    except (ValueError, TypeError):
        continue

eligible.sort(key=lambda x: (-float(x['live_discount']), str(x['area']), str(x['sku'])))
print('ELIGIBLE_FOR_PRIVATE_REVIEW:', len(eligible), flush=True)
if not eligible:
    raise SystemExit(0)

sent = seen = fail = 0
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width':1080, 'height':900}, device_scale_factor=1.2)
    try:
        for item in eligible:
            if sent >= MAX_ALERTS:
                break
            identity = offer_identity(item)
            try:
                status = worker_post('/seen', {'id': identity})
                if status.get('seen'):
                    seen += 1
                    continue
                screenshot = card_photo(page, item, identity)
                if not screenshot:
                    print('REAL_CARD_NOT_FOUND:', item['area'], item['sku'], flush=True)
                    continue
                if send_photo_and_controls(item, *screenshot, identity):
                    sent += 1
            except Exception as exc:
                fail += 1
                print('PRIVATE_REVIEW_ERROR:', item['area'], item['sku'],
                      type(exc).__name__, str(exc)[:100], flush=True)
    finally:
        browser.close()

print('TALABAT_PRIVATE_REVIEW_SUMMARY:', 'SENT', sent, 'SEEN', seen, 'ERRORS', fail, flush=True)
if fail and not sent and not seen:
    raise SystemExit('ALL_PRIVATE_REVIEW_ATTEMPTS_FAILED')
