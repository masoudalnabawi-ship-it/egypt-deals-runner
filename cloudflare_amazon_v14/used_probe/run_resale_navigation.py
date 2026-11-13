#!/usr/bin/env python3
"""One Amazon Resale navigation probe, optional one category page, no publication."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from probe_transport import fetch_json_via_curl

BASE='https://egypt-amazon-used-probe.masoud-amazon-eg.workers.dev/'
OUTPUT=Path(__file__).resolve().parent/'reports'/'amazon_used_resale_navigation.json'
OUTPUT.parent.mkdir(parents=True,exist_ok=True)
record={'checked_at':datetime.now(timezone.utc).isoformat(),
        'scope':'Resale landing and at most one evidenced category page',
        'public_posting_enabled':False,'verified_offers':0}
try:
    key=os.environ.get('PROBE_KEY','')
    if not key:raise ValueError('PROBE_KEY_MISSING')
    data=fetch_json_via_curl(BASE+'?mode=resale_nav',key)
    record.update(data)
except (HTTPError, URLError, ValueError, TimeoutError) as exc:
    record['status']='PROBE_CONNECTION_ERROR'
    record['error_kind']=type(exc).__name__
    if isinstance(exc,HTTPError):record['endpoint_http']=exc.code
finally:
    OUTPUT.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

status=record.get('status','UNKNOWN')
nav=record.get('navigation') or {}
cat=record.get('category_probe') or {}
print('RESALE_NAV_STATUS:',status,
      'LANDING_HTTP:',record.get('source_http'),
      'CATEGORY_LINKS:',record.get('category_urls_discovered',0),
      'LANDING_PRODUCTS:',record.get('product_candidates_on_landing',0),
      'CATEGORY_PRODUCTS:',cat.get('product_count',0),
      'VERIFIED_USED_OFFERS: 0',flush=True)
print('RESALE_NAV_DIAGNOSTICS:',
      'ANCHORS:',nav.get('anchor_elements',0),
      'HREFS:',nav.get('anchors_with_href',0),
      'CATEGORIES_PROBED:',int(bool(cat)),flush=True)
if status in ('PROBE_CONNECTION_ERROR','SOURCE_RATE_LIMITED','SOURCE_FETCH_FAILED',
              'SOURCE_REDIRECT_UNVERIFIED','SOURCE_CAPTCHA_REQUIRES_MANUAL_REVIEW',
              'CATEGORY_RATE_LIMITED','CATEGORY_FETCH_FAILED','CATEGORY_REDIRECT_UNVERIFIED',
              'CATEGORY_CAPTCHA_REQUIRES_MANUAL_REVIEW'):
    raise SystemExit('AMAZON_RESALE_NAV_SOURCE_REQUIRES_REVIEW')
if status=='SOURCE_NO_CATEGORY_NAV_OBSERVED':
    print('AMAZON_RESALE_NAV_EMPTY: no product or category DOM available; not proof that inventory is empty',flush=True)
print('AMAZON_RESALE_NAV_DIAGNOSTIC_COMPLETE',flush=True)
