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
                if data is None: raise ValueError('no_verified_egp_device_product')
                db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)', (store, url, data['sku'], data['title'], data['price'], datetime.now(timezone.utc).isoformat()))
                db.commit()
                results.append({'store': store, 'url': url, 'verified': True, **data})
            except Exception as exc:
                results.append({'store': store, 'url': url, 'verified': False, 'reason': str(exc)[:160]})
            finally: page.close()
        context.close(); browser.close()
    db.close()
    return {'results': results, 'published': 0}

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
