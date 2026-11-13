#!/usr/bin/env python3
"""Single bounded observation of the alternative /l/ Amazon Egypt Resale URL."""
import json, os
from pathlib import Path
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from probe_transport import fetch_json_via_curl

BASE='https://egypt-amazon-used-probe.masoud-amazon-eg.workers.dev/'
OUT=Path(__file__).resolve().parent/'reports'/'amazon_used_resale_real_v8.json'
OUT.parent.mkdir(parents=True, exist_ok=True)
report={'checked_at':datetime.now(timezone.utc).isoformat(),'status':'NOT_RUN','public_posting_enabled':False,'verified_used_offers':0}
try:
    key=os.environ.get('PROBE_KEY','')
    if not key: raise ValueError('PROBE_KEY_MISSING')
    report.update(fetch_json_via_curl(BASE+'?mode=resale_real_v8',key))
except (HTTPError,URLError,ValueError,TimeoutError) as e:
    report['status']='PROBE_CONNECTION_ERROR'
    report['error_kind']=type(e).__name__
    if isinstance(e,HTTPError):report['endpoint_http']=e.code
finally:
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('AMAZON_RESALE_REAL_V8:',report.get('status'),'ORIGIN_HTTP:',report.get('source_http'),
      'PRODUCTS:',report.get('candidate_count',0),'CATEGORY_LINKS:',report.get('category_count',0),
      'VERIFIED_USED:',0,flush=True)
if report['status'] in ('PROBE_CONNECTION_ERROR','REAL_SOURCE_RATE_LIMITED','REAL_SOURCE_FETCH_FAILED',
                        'REAL_SOURCE_REDIRECT_UNVERIFIED','REAL_SOURCE_CAPTCHA_REQUIRES_REVIEW'):
    raise SystemExit('AMAZON_RESALE_REAL_V8_REQUIRES_REVIEW')
print('AMAZON_RESALE_REAL_V8_DIAGNOSTIC_COMPLETE',flush=True)
