import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

root = Path('cloudflare_amazon_v14')
x = json.loads((root/'talabat_alerts/first_offer.json').read_text(encoding='utf-8'))
proof = root/'talabat_alerts/talabat_live_proof.png'
if not proof.is_file() or proof.stat().st_size < 4000:
    raise SystemExit('REAL_SCREENSHOT_NOT_FOUND')

host = urlsplit(x['product_link']).hostname
if host != 'www.talabat.com' or '/product/' not in x['product_link']:
    raise SystemExit('INVALID_PRODUCT_LINK')

match = re.search(r'/s/([A-Za-z0-9]+)', x['product_link'])
if not match:
    raise SystemExit('SKU_NOT_FOUND')
sku = match.group(1)
price = float(x['price'])
discount = float(x['discount'])
if price <= 0 or discount < 40:
    raise SystemExit('INVALID_DEAL')

branch_match = re.search(r'/grocery/(\d+)/', x['category_link'])
if not branch_match:
    raise SystemExit('BRANCH_NOT_FOUND')
branch = branch_match.group(1)
now = int(time.time())
day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
offer_id = hashlib.sha256(f'{branch}|{sku}|{price:.2f}|{day}'.encode()).hexdigest()[:32]

bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
worker_url = os.getenv('REVIEW_WORKER_URL', '').rstrip('/')
if not bot_token or not worker_url:
    raise SystemExit('MISSING_ENV')

sess = requests.Session()
res = sess.post(worker_url+'/reserve', json={
    'id': offer_id, 'title': x['title'], 'area': x['area'], 'sku': sku,
    'price': price, 'discount': discount, 'product_url': x['product_link'],
    'source_url': x['category_link'], 'proof_at': now
}, headers={'Authorization': 'Bearer '+bot_token}, timeout=25)
res.raise_for_status()
r = res.json()
if not r.get('reserved'):
    print('ALREADY_RESERVED_OR_REVIEWED:', offer_id)
    raise SystemExit(0)

caption = (
    f"🛒 طلبات مارت | {x['area']}\n"
    f"📦 {x['title'][:145]}\n"
    f"💰 {price:.2f} ج | 🔥 {discount:g}%\n"
    "📸 لقطة شاشة فعلية من طلبات بالسعر\n"
    "⚠️ السعر النهائي والتوفر عند الدفع غير مؤكَّدين\n"
    "🔎 للمراجعة قبل النشر للقناة"
)

with proof.open('rb') as photo:
    msg = sess.post(f'https://api.telegram.org/bot{bot_token}/sendPhoto',
        data={'chat_id': '-1004375874566', 'caption': caption},
        files={'photo': ('talabat_live_proof.png',photo,'image/png')}, timeout=35)
msg.raise_for_status()
message = msg.json()
if not message.get('ok'):
    raise SystemExit('TELEGRAM_REVIEW_PHOTO_FAILED')
message_id = message['result']['message_id']

attach = sess.post(worker_url+'/attach',json={'id':offer_id,'message_id':message_id},
    headers={'Authorization':'Bearer '+bot_token},timeout=25)
attach.raise_for_status()
buttons = attach.json()
if not buttons.get('ok'):
    raise SystemExit('BUTTON_ATTACH_FAILED')

markup = {'inline_keyboard': [
    [{'text':'✅ نشر لقناة أمازون', 'url': buttons['publish_url']},
     {'text':'❌ رفض العرض', 'url': buttons['reject_url']}],
    [{'text':'🛒 صفحة المنتج على الويب', 'url': x['product_link']}]
]}
edit = sess.post(f'https://api.telegram.org/bot{bot_token}/editMessageReplyMarkup',
    json={'chat_id':'-1004375874566','message_id':message_id, 'reply_markup':markup},timeout=25)
edit.raise_for_status()
if not edit.json().get('ok'):
    raise SystemExit('REVIEW_BUTTONS_EDIT_FAILED')
print('TALABAT_REVIEW_BUTTONS: SUCCESS')
print('OFFER_ID:',offer_id)
print('REVIEW_MESSAGE_ID:',message_id)
print('NOTE: Publish opens a confirmation page. Product link may not open in the Talabat mobile app.')
