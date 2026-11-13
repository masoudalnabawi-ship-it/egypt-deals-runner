#!/usr/bin/env python3
"""A tiny, non-aggressive ASIN pilot. Does not crawl offer-listing or post alerts."""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json
import os
import re
import time

# User's previously assembled watchlist is reused, rather than making up products.
ROOT = Path(__file__).resolve().parents[2]
WATCH = ROOT / 'seed_state' / 'amazon_manual_watch.txt'
OUT = Path(__file__).resolve().parent / 'reports' / 'amazon_used_rotation.json'
URL = 'https://egypt-amazon-used-probe.masoud-amazon-eg.workers.dev/'
KEY = os.getenv('PROBE_KEY', '')
if not KEY:
    raise SystemExit('AMAZON_USED_PILOT_KEY_MISSING')
if not WATCH.exists():
    raise SystemExit('AMAZON_USED_PILOT_WATCHLIST_MISSING')
all_asins = list(dict.fromkeys(
    s.upper() for s in WATCH.read_text(encoding='utf-8').splitlines()
    if re.fullmatch(r'[A-Za-z0-9]{10}', s.strip())
))
if not all_asins:
    raise SystemExit('AMAZON_USED_PILOT_NO_ASINS')

# Rotate three nonadjacent samples from the user's existing watched catalog.
# One CI run is deliberately bounded to three product-page reads.
slot = int(time.time() // 1800)
index = slot % len(all_asins)
selected = []
for jump in (0, len(all_asins)//3, 2*len(all_asins)//3):
    asin = all_asins[(index + jump) % len(all_asins)]
    if asin not in selected:
        selected.append(asin)
selected = selected[:3]
result = {'started_at': datetime.now(timezone.utc).isoformat(),
          'scope': 'amazon.eg product pages only; no direct offer listing',
          'selected_asins': selected, 'results': [], 'verified_offers': 0,
          'public_posting_enabled': False}
OUT.parent.mkdir(parents=True, exist_ok=True)

def save():
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

blocked = False
for pos, asin in enumerate(selected):
    if pos:
        time.sleep(12)   # little load; no retry after a throttle
    path = URL + '?' + urlencode({'asin': asin, 'main_only':'1'})
    req = Request(path, headers={'Authorization': 'Bearer '+KEY,
                                 'Accept': 'application/json'})
    try:
        with urlopen(req, timeout=50) as response:
            raw = json.load(response)
        p = raw.get('product_page') or {}
        status = str(raw.get('status') or 'UNKNOWN')
        record = {'asin': asin, 'status': status,
                  'product_http': p.get('http'),
                  'new_price': raw.get('new_price'),
                  'used_price_candidate': raw.get('lowest_used_price_candidate'),
                  'saving_percent_candidate': raw.get('used_saving_vs_new_percent_candidate'),
                  'used_condition': [i.get('condition') for i in raw.get('product_page_used_offers', [])],
                  'used_price_verified': False,
                  'url': 'https://www.amazon.eg/dp/'+asin}
        result['results'].append(record)
        print('USED_PRODUCT_PAGE_PILOT:', asin, status,
              'NEW', record['new_price'], 'USED_CANDIDATE', record['used_price_candidate'], flush=True)
        if status in ('PRODUCT_RATE_LIMITED','BLOCKED_CAPTCHA') or p.get('http') == 429:
            blocked = True
            result['stopped_due_to_restriction'] = True
            break
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        result['results'].append({'asin':asin, 'status':'REQUEST_ERROR',
                                  'error_type':type(error).__name__})
        blocked = True
        result['stopped_due_to_request_error'] = True
        break
    finally:
        save()
result['finished_at'] = datetime.now(timezone.utc).isoformat()
result['candidate_count'] = sum(1 for x in result['results'] if x.get('used_price_candidate') is not None)
save()
print('AMAZON_USED_PILOT_SUMMARY:', 'ITEMS',len(result['results']),
      'CANDIDATES',result['candidate_count'],'BLOCKED',blocked,
      'PUBLISHED',False,flush=True)
