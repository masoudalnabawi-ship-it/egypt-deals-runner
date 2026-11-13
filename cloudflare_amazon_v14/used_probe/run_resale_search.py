#!/usr/bin/env python3
"""One rate-limit-respecting test of a constrained Resale browse-node search page."""
import json, os
from pathlib import Path
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from probe_transport import fetch_json_via_curl

BASE='https://egypt-amazon-used-probe.masoud-amazon-eg.workers.dev/'
OUT=Path(__file__).resolve().parent/'reports'/'amazon_used_resale_search.json'
OUT.parent.mkdir(parents=True, exist_ok=True)
report={'checked_at':datetime.now(timezone.utc).isoformat(),'status':'NOT_RUN',
        'public_posting_enabled':False,'verified_offers':0}
try:
    key=os.environ.get('PROBE_KEY','')
    if not key: raise ValueError('PROBE_KEY_MISSING')
    report.update(fetch_json_via_curl(BASE+'?mode=resale_search',key))
except (HTTPError,URLError,ValueError,TimeoutError) as e:
    report['status']='PROBE_CONNECTION_ERROR'
    report['error_kind']=type(e).__name__
    if isinstance(e,HTTPError):report['endpoint_http']=e.code
finally:
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('AMAZON_RESALE_SEARCH_DIAG:',report.get('status'),
      'ORIGIN_HTTP:',report.get('source_http'),'CANDIDATES:',report.get('candidate_count',0),
      'VERIFIED_USED:',0,flush=True)
if report['status'] in ('PROBE_CONNECTION_ERROR','SEARCH_RATE_LIMITED','SEARCH_FETCH_FAILED',
                        'SEARCH_CAPTCHA_REQUIRES_REVIEW','SEARCH_REDIRECT_UNVERIFIED'):
    raise SystemExit('AMAZON_RESALE_SEARCH_REQUIRES_REVIEW')
print('AMAZON_RESALE_SEARCH_DIAGNOSTIC_COMPLETE',flush=True)
