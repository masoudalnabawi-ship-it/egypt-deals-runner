"""V16 professional private alert formatting. No Telegram calls."""
import json
import re
from decimal import Decimal

ASIN_RE = re.compile(r'^[A-Z0-9]{10}$')


def format_alert(candidate):
    asin = str(candidate.get('asin', ''))
    if not ASIN_RE.fullmatch(asin):
        raise ValueError('INVALID_ASIN')

    title = re.sub(r'[\x00-\x1f\x7f]', ' ', str(candidate.get('title') or 'منتج على أمازون مصر')).strip()[:180]
    price = Decimal(str(candidate['current_price']))
    discount = Decimal(str(candidate['displayed_discount_pct']))

    if not price.is_finite() or price <= 0:
        raise ValueError('INVALID_PRICE')
    if not discount.is_finite() or not 0 <= discount <= 100:
        raise ValueError('INVALID_DISCOUNT')

    label = (
        '🚨⚡ عرض فلاش' if discount >= 90 else
        '🚨🔥 سوبر ألترا' if discount >= 70 else
        '🔥 عرض ألترا' if discount >= 50 else
        '🟠 عرض قوي' if discount >= 30 else
        '🟢 عرض مميز'
    )

    before = price / (Decimal('1') - discount / Decimal('100')) if discount < 100 else None
    before_line = (
        f'🏷️ السعر قبل الخصم (تقديري): {before:,.2f} جنيه\\n'
        if before is not None else
        '🏷️ السعر قبل الخصم: غير متاح\\n'
    )

    return (
        f'{label} | V16 أمازون مصر 🇪🇬\n\n'
        f'📦 {title}\n\n'
        f'💰 السعر الحالي: {price:,.2f} جنيه\n'
        f'{before_line}'
        f'📉 الخصم المعلن: {discount}%\n\n'
        f'🛒 https://www.amazon.eg/dp/{asin}\n\n'
        '⚡ الخصم ظاهر على أمازون وقت الرصد.\n'
        '⚠️ لم تتم مقارنة السعر بتاريخ الأسعار.\n'
        '🔒 للمراجعة الخاصة — لا يوجد نشر تلقائي.'
    )


def review_keyboard(candidate, *, interactive=False):
    asin = str(candidate.get('asin', ''))
    if not ASIN_RE.fullmatch(asin):
        raise ValueError('INVALID_ASIN')

    rows = [
        [{'text': '🛒 فتح المنتج',
          'url': f'https://www.amazon.eg/dp/{asin}'}]
    ]

    if interactive:
        rows = [
            [
                {'text': '🚀 نشر',
                 'callback_data': f'v16:publish:{asin}'},
                {'text': '❌ رفض',
                 'callback_data': f'v16:reject:{asin}'},
            ],
            [
                {'text': '✍️ رسالة مخصصة',
                 'callback_data': f'v16:custom:{asin}'},
            ],
            [
                {'text': '🛒 فتح المنتج',
                 'url': f'https://www.amazon.eg/dp/{asin}'},
            ],
        ]

    return json.dumps(
        {'inline_keyboard': rows},
        ensure_ascii=False,
    )
