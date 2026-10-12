"""V15 only: best-effort private early warning; never publishes publicly."""
import json
import os
import re
import urllib.parse
import urllib.request
from decimal import Decimal
from flash_review import keyboard, interactive_enabled

ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")

def payload(candidate):
    asin = str(candidate.get('asin', ''))
    if not ASIN_RE.fullmatch(asin):
        raise ValueError('INVALID_ASIN')
    price = Decimal(str(candidate['current_price']))
    reference = Decimal(str(candidate['displayed_reference']))
    discount = Decimal(str(candidate['displayed_discount_pct']))
    if not (price.is_finite() and reference.is_finite() and discount.is_finite() and 0 < price < reference and 70 <= discount < 100):
        raise ValueError('INVALID_FLASH_PRICE')
    url = 'https://www.amazon.eg/dp/' + asin
    text = (f'🚨 عرض استثنائي محتمل — V15\n'
            f'💰 السعر المرصود: {price:,.2f} جنيه\n'
            f'🏷 السعر المرجعي المعروض: {reference:,.2f} جنيه\n'
            f'📉 الخصم الظاهر: {discount}%\n'
            f'📦 ASIN: {asin}\n'
            f'🕒 وقت الرصد: {str(candidate.get("captured_at") or "غير متاح")[:50]}\n'
            '⚠️ غير مؤكد: السعر المرجعي ليس تاريخ سعر موثقًا. تحقق من صفحة المنتج.\n'
            '🔒 رسالة خاصة فقط؛ لا نشر عام تلقائي.')
    return {'text': text, 'reply_markup': json.dumps(keyboard(candidate, interactive=interactive_enabled()), ensure_ascii=False)}

def send(candidate, *, token=None, chat_id=None, opener=None):
    token = token if token is not None else os.environ.get('V15_TELEGRAM_BOT_TOKEN', '')
    chat_id = chat_id if chat_id is not None else os.environ.get('V15_TELEGRAM_REVIEW_CHAT_ID', '')
    if not token or not re.fullmatch(r'-?\d+', str(chat_id).strip()):
        return False
    data = payload(candidate)
    data['chat_id'] = str(chat_id).strip()
    req = urllib.request.Request('https://api.telegram.org/bot' + token + '/sendMessage', data=urllib.parse.urlencode(data).encode(), method='POST')
    op = opener or urllib.request.urlopen
    with op(req, timeout=12) as response:
        result = json.load(response)
    return result.get('ok') is True
