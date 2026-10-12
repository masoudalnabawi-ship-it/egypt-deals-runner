"""V15 private review controls. Callback buttons stay OFF until secure webhook is deployed."""
import json
import os
import re
from decimal import Decimal

ASIN = re.compile(r"^[A-Z0-9]{10}$")

def keyboard(candidate, *, interactive=False):
    asin = str(candidate.get('asin', ''))
    if not ASIN.fullmatch(asin):
        raise ValueError('INVALID_ASIN')
    rows = [[{'text': '🛒 فتح المنتج', 'url': 'https://www.amazon.eg/dp/' + asin}]]
    if interactive:
        rows += [
            [{'text': '🚀 نشر فورًا', 'callback_data': 'v15:publish:' + asin},
             {'text': '✏️ تعديل / رسالة مخصصة', 'callback_data': 'v15:edit:' + asin}],
            [{'text': '🔍 انتظار التحقق', 'callback_data': 'v15:wait:' + asin},
             {'text': '❌ تجاهل', 'callback_data': 'v15:ignore:' + asin}],
        ]
    return {'inline_keyboard': rows}

def validate_custom_message(message, *, max_length=3000):
    if not isinstance(message, str) or not message.strip() or len(message) > max_length:
        raise ValueError('INVALID_CUSTOM_MESSAGE')
    if any(ord(c) < 32 and c not in '\n\t' for c in message):
        raise ValueError('INVALID_CUSTOM_MESSAGE')
    return message.strip()

def preview(candidate, custom_message):
    asin = candidate['asin']
    if not ASIN.fullmatch(str(asin)):
        raise ValueError('INVALID_ASIN')
    message = validate_custom_message(custom_message)
    price = Decimal(str(candidate['current_price']))
    if not price.is_finite() or price <= 0:
        raise ValueError('INVALID_PRICE')
    return (message + '\n\n' +
            f'📦 رابط المنتج: https://www.amazon.eg/dp/{asin}\n' +
            f'⚠️ السعر المرصود: {price:,.2f} جنيه — غير مؤكد؛ راجع صفحة المنتج قبل النشر.\n' +
            '🔒 معاينة فقط — النشر العام غير مفعّل.')

def interactive_enabled():
    # Fail closed: never expose buttons that have no deployed secure handler.
    return os.environ.get('V15_SECURE_WEBHOOK_READY') == 'true' and os.environ.get('V15_INTERACTIVE_BUTTONS_ENABLED') == 'true'
