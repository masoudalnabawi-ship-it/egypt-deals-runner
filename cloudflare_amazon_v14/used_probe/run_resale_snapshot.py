#!/usr/bin/env python3
"""Single bounded Resale snapshot diagnostic, no used prices claimed or Telegram posts."""
from pathlib import Path
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
import json, os
from probe_transport import fetch_json_via_curl

BASE='https://egypt-amazon-used-probe.masoud-amazon-eg.workers.dev/'
OUT=Path(__file__).resolve().parent/'reports'/'amazon_used_resale_snapshot_v11.json'
OUT.parent.mkdir(parents=True, exist_ok=True)
report={'checked_at':datetime.now(timezone.utc).isoformat(),'status':'NOT_RUN',
        'public_posting_enabled':False,'verified_used_offers':0}
try:
    key=os.environ.get('PROBE_KEY','')
    if not key: raise ValueError('PROBE_KEY_MISSING')
    report.update(fetch_json_via_curl(BASE+'?mode=resale_snapshot_v11',key))
except (HTTPError, URLError, ValueError, TimeoutError) as exc:
    report['status']='PROBE_CONNECTION_ERROR'
    report['error_type']=type(exc).__name__
    if isinstance(exc,HTTPError): report['endpoint_http']=exc.code
finally:
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('AMAZON_RESALE_SNAPSHOT_V11:',report.get('status'),
      'ORIGIN_HTTP:',report.get('source_http'),
      'TITLE:',report.get('source_title'),
      'MARKDOWN_LENGTH:',report.get('markdown_length'),
      'A11Y_NODES:',report.get('accessibility_nodes_seen'),
      'PRODUCTS:',report.get('product_candidate_count',0),
      'CATEGORIES:',report.get('category_link_count',0),
      'VERIFIED_USED:',0,flush=True)
if report.get('status') in ('PROBE_CONNECTION_ERROR','SOURCE_SNAPSHOT_FAILED','SOURCE_RATE_LIMITED','SOURCE_CAPTCHA_REQUIRES_REVIEW','SOURCE_REDIRECT_UNVERIFIED'):
    raise SystemExit('AMAZON_RESALE_SNAPSHOT_V11_REQUIRES_REVIEW')
print('AMAZON_RESALE_SNAPSHOT_V11_DIAGNOSTIC_COMPLETE',flush=True)
