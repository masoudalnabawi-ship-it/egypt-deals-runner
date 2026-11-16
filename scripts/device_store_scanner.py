"""Isolated read-only B.TECH / 2B device-price scanner; never publishes.

Input targets JSON: [{"store":"btech","url":"https://btech.com/..."}, ...].
Runs independently of V14 until the store verification and publishing routes exist.
"""
from __future__ import annotations
import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from statistics import median
from pathlib import Path
from urllib.parse import urlsplit

HOSTS = {'btech': ('btech.com', 'www.btech.com'), '2b': ('2b.com.eg', 'www.2b.com.eg')}
BLOCK = re.compile(r'جراب|كفر|اسكرينة|سكرينة|واقي شاشة|شاحن|كابل|وصلة|حامل|ريموت|قطعة غيار|بطارية بديلة|ملابس|تيشيرت|بنطلون|حذاء|سوبر ماركت|مأكولات|منظف|case\b|screen protector|charger|cable|adapter|accessor|replacement|grocer|fashion|clothing', re.I)
DEVICE = re.compile(r'موبايل|هاتف|تليفون|تابلت|لابتوب|لاب توب|كمبيوتر|حاسوب|شاشة|تلفزيون|تكييف|ثلاجة|غسالة|بوتاجاز|ميكروويف|ديب فريزر|مكنسة|سخان|غسالة أطباق|مروحة|خلاط|فرن|قلاية هوائية|طابعة|راوتر|كاميرا|سماعة رأس|smartphone|mobile phone|tablet|laptop|notebook|desktop|monitor|television|smart tv|refrigerator|washing machine|air conditioner|microwave|vacuum cleaner|printer|router|camera', re.I)

def target(row):
    if not isinstance(row, dict): raise ValueError('invalid_target')
    store = str(row.get('store', '')).lower()
    url = str(row.get('url', '')).strip()
    parsed = urlsplit(url)
    if store not in HOSTS or parsed.scheme != 'https' or parsed.hostname not in HOSTS[store] or parsed.username or parsed.password:
        raise ValueError('unsupported_store_or_url')
    return store, url

def eligible(title):
    return bool(title and DEVICE.search(title) and not BLOCK.search(title))

def parse_jsonld(raw):
    try: doc = json.loads(raw)
    except (ValueError, TypeError): return []
    def walk(obj):
        if isinstance(obj, list):
            for x in obj: yield from walk(x)
        elif isinstance(obj, dict):
            if str(obj.get('@type', '')).lower() in ('product', 'https://schema.org/product'): yield obj
            for key in ('@graph', 'mainEntity'):
                if key in obj: yield from walk(obj[key])
    return list(walk(doc))

def extract_product(jsonld_texts):
    for raw in jsonld_texts:
        for product in parse_jsonld(raw):
            title = str(product.get('name') or '').strip()
            offers = product.get('offers') or {}
            if isinstance(offers, list): offers = offers[0] if offers else {}
            if not isinstance(offers, dict): continue
            try: price = float(str(offers.get('price') or offers.get('lowPrice') or '').replace(',', ''))
            except ValueError: continue
            currency = str(offers.get('priceCurrency') or '').upper()
            if eligible(title) and 0 < price < 100000000 and currency == 'EGP':
                return {'title': title, 'price': price, 'currency': currency, 'sku': str(product.get('sku') or product.get('productID') or '')}
    return None

def store_diagnostic(page):
    # Evidence only: never turn unverified visible prices into verified offers.
    try:
        return {
            "page_title": page.title()[:120],
            "jsonld_count": page.locator('script[type="application/ld+json"]').count(),
            "price_meta_count": page.locator('meta[property="product:price:amount"]').count(),
            "price_element_count": page.locator('[itemprop="price"], [data-price], .price').count(),
            "final_url": page.url[:250],
        }
    except Exception as exc:
        return {"diagnostic_error": str(exc)[:100]}


def classify_candidate(db, store, sku, current, ultra_min=65):
    # Strict historical baseline: five observations over at least three days.
    if not sku:
        return {"lane": "unclassified", "reason": "missing_sku", "publish": False}
    history = []
    for price, observed in db.execute('SELECT price, observed_at FROM observations WHERE store=? AND sku=?', (store, sku)):
        try:
            dt = datetime.fromisoformat(observed.replace('Z', '+00:00'))
            age = (datetime.now(timezone.utc) - dt).total_seconds()
            if dt.tzinfo and 0 <= age <= 180 * 86400 and 0 < float(price) < 100000000:
                history.append((float(price), dt.date()))
        except (ValueError, TypeError, AttributeError):
            continue
    if len(history) < 5 or len(set(d for _, d in history)) < 3:
        return {"lane": "unclassified", "reason": "insufficient_verified_history", "publish": False}
    baseline = median(price for price, _ in history)
    discount = round(100 * (baseline - current) / baseline, 2)
    if discount >= 90:
        return {"lane": "ultra", "alert_type": "price_crash_pending", "discount_percent": discount,
                "reason": "needs_two_live_checks_120s_apart_and_manual_review", "publish": False}
    if discount >= ultra_min:
        return {"lane": "ultra", "alert_type": "large_discount_review", "discount_percent": discount, "publish": False}
    if discount >= 10:
        return {"lane": "normal", "alert_type": "discount_review", "discount_percent": discount, "publish": False}
    return {"lane": "unclassified", "discount_percent": discount, "publish": False}

def run(targets, db_path):
    from playwright.sync_api import sync_playwright
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    db.execute('CREATE TABLE IF NOT EXISTS observations (store TEXT,url TEXT,sku TEXT,title TEXT,price REAL,observed_at TEXT)')
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = browser.new_context(locale='ar-EG')
        for row in targets:
            store, url = target(row)
            page = context.new_page()
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                if urlsplit(page.url).hostname not in HOSTS[store]: raise ValueError('cross_store_redirect')
                data = extract_product(page.locator('script[type="application/ld+json"]').all_text_contents())
                if data is None:
                    results.append({'store': store, 'url': url, 'verified': False, 'reason': 'no_verified_egp_device_product', 'diagnostic': store_diagnostic(page)})
                    continue
                review = classify_candidate(db, store, data['sku'], data['price'])
                db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)', (store, url, data['sku'], data['title'], data['price'], datetime.now(timezone.utc).isoformat()))
                db.commit()
                results.append({'store': store, 'url': url, 'verified': True, **data, 'review': review})
            except Exception as exc:
                results.append({'store': store, 'url': url, 'verified': False, 'reason': str(exc)[:160]})
            finally: page.close()
        context.close(); browser.close()
    db.close()
    return {'results': results, 'published': 0, 'telegram_sent': 0}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--targets', required=True, type=Path)
    ap.add_argument('--db', type=Path, default=Path('device_store_history.sqlite3'))
    args = ap.parse_args()
    targets = json.loads(args.targets.read_text(encoding='utf-8'))
    if not isinstance(targets, list) or not targets: ap.error('nonempty targets list required')
    for row in targets: target(row)
    print(json.dumps(run(targets, args.db), ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
