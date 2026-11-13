#!/usr/bin/env python3
"""One read of an Amazon Egypt Resale landing, then save conservative report.
No automated product visits or retries, and never publishes to Telegram.
"""
import json, os
from pathlib import Path
from datetime import datetime, timezone
from probe_transport import fetch_json_via_curl
from urllib.error import HTTPError, URLError

URL='https://egypt-amazon-used-probe.masoud-amazon-eg.workers.dev/?mode=resale'
KEY=os.environ.get('PROBE_KEY','')
OUT=Path(__file__).resolve().parent/'reports'/'amazon_used_resale_source.json'
OUT.parent.mkdir(parents=True,exist_ok=True)
report={'checked_at':datetime.now(timezone.utc).isoformat(),'source_url':'https://www.amazon.eg/b?node=27972175031',
        'public_posting_enabled':False,'verified_offers':0}
try:
    if not KEY: raise ValueError('PROBE_KEY_MISSING')
    result=fetch_json_via_curl(URL,KEY)
    report.update(result)
    print('RESALE_SOURCE_STATUS:',result.get('status'),'SOURCE_HTTP:',result.get('source_http'),
          'CANDIDATES:',len(result.get('candidates') or []),flush=True)
except (HTTPError, URLError, ValueError, TimeoutError) as e:
    report['status']='PROBE_REQUEST_FAILED'
    report['error_kind']=type(e).__name__
    if isinstance(e,HTTPError):report['endpoint_http']=e.code
finally:
    OUT.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
if report['status'] in ('PROBE_REQUEST_FAILED','SOURCE_RATE_LIMITED','SOURCE_BROWSER_ERROR','SOURCE_REDIRECT_UNVERIFIED'):
    raise SystemExit('AMAZON_RESALE_SOURCE_NOT_ACCESSIBLE')
print('AMAZON_RESALE_SOURCE_PROBE_COMPLETE',flush=True)
