"""Conservative V15 product-family intelligence; no publishing decisions."""
import re
from decimal import Decimal, InvalidOperation
from statistics import median

# Match full products separately from accessories, parts and service plans.
FAMILIES = {
    'treadmill': (r'\b(treadmill|walking pad)\b|مشاية|جهاز\s+جري',),
    'android_phone': (r'\b(android|smartphone|smart phone)\b|هاتف\s+ذكي|موبايل\s+اندرويد',),
    'feature_phone': (r'\b(feature phone|keypad phone|button phone)\b|موبايل\s+زراير|هاتف\s+بأزرار',),
    'laptop': (r'\b(laptop|notebook computer)\b|لابتوب|حاسب\s+محمول',),
    'television': (r'\b(television|smart tv|led tv|oled tv)\b|تلفزيون|شاشة\s+تلفزيون',),
    'washing_machine': (r'\b(washing machine|washer dryer)\b|غسالة',),
    'refrigerator': (r'\b(refrigerator|fridge)\b|ثلاجة',),
}
ACCESSORY = re.compile(r'\b(case|cover|protector|screen guard|charger|adapter|cable|remote|replacement|spare part|motor only|belt only|lubricant|oil|stand|holder|strap|manual|toy|miniature|sticker|refurbished parts)\b|جراب|غطاء|شاحن|كابل|قطعة\s+غيار|سير\s+مشاية|زيت\s+تشحيم|حامل|ريموت|مجسم|لعبة\s+على\s+شكل', re.I)
INSTALLMENT = re.compile(r'\b(per month|monthly payment|installment|deposit|down payment)\b|قسط\s+شهري|مقدم\s+حجز|دفعة\s+مقدمة', re.I)
CONDITION = re.compile(r'\b(used|renewed|refurbished|open box)\b|مستعمل|مجدد|مفتوح\s+العلبة', re.I)

def classify(title):
    if not isinstance(title, str) or not title.strip():
        return {'family': 'unknown', 'comparable': False, 'reason': 'missing_title'}
    if INSTALLMENT.search(title):
        return {'family': 'unknown', 'comparable': False, 'reason': 'payment_ambiguity'}
    if ACCESSORY.search(title):
        return {'family': 'accessory', 'comparable': False, 'reason': 'accessory_or_part'}
    if CONDITION.search(title):
        return {'family': 'unknown', 'comparable': False, 'reason': 'condition_ambiguity'}
    hits=[family for family,patterns in FAMILIES.items() if any(re.search(p,title,re.I) for p in patterns)]
    if len(hits)!=1:
        return {'family': 'unknown', 'comparable': False, 'reason': 'ambiguous_or_unknown'}
    return {'family': hits[0], 'comparable': True, 'reason': 'family_candidate_only'}

def first_listing_signal(title, current_price, comparable_prices, *, minimum_comparables=3):
    """Research-only candidate. Never claims a verified discount or publishes."""
    category=classify(title)
    if not category['comparable']:
        return {'status': 'insufficient_evidence', 'reason': category['reason'], 'publish_allowed': False}
    try:
        price=Decimal(str(current_price))
        refs=[Decimal(str(p)) for p in comparable_prices]
    except (InvalidOperation, TypeError, ValueError):
        return {'status': 'insufficient_evidence', 'reason': 'invalid_prices', 'publish_allowed': False}
    if not price.is_finite() or price<=0 or any(not p.is_finite() or p<=0 for p in refs) or len(refs)<minimum_comparables:
        return {'status': 'insufficient_evidence', 'reason': 'invalid_or_sparse_comparables', 'publish_allowed': False}
    baseline=median(refs)
    ratio=price/baseline
    return {'status': 'extreme_candidate' if ratio<=Decimal('0.20') else 'ordinary_candidate',
            'family': category['family'], 'current_price': str(price),
            'comparison_median': str(baseline), 'price_to_median_ratio': str(round(ratio,4)),
            'publish_allowed': False, 'reason': 'comparables_require_model_spec_condition_validation'}
