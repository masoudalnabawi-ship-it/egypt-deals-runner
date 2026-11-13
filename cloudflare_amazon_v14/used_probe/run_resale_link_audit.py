#!/usr/bin/env python3
"""Exactly one read-only diagnostic of link shapes on Amazon Egypt Resale."""
import json,os
from pathlib import Path
from datetime import datetime,timezone
from urllib.error import HTTPError,URLError
from probe_transport import fetch_json_via_curl

ENDPOINT='https://egypt-amazon-used-probe.masoud-amazon-eg.workers.dev/?mode=resale_link_audit_v12'
OUT=Path(__file__).resolve().parent/'reports'/'amazon_used_resale_link_audit_v12.json'
OUT.parent.mkdir(parents=True,exist_ok=True)
report={'checked_at':datetime.now(timezone.utc).isoformat(),'status':'NOT_RUN',
        'verified_used_offers':0,'public_posting_enabled':False}
try:
    key=os.environ.get('PROBE_KEY','')
    if not key:raise ValueError('PROBE_KEY_MISSING')
    report.update(fetch_json_via_curl(ENDPOINT,key))
except (HTTPError,URLError,ValueError,TimeoutError) as exc:
    report['status']='PROBE_CONNECTION_ERROR'
    report['error_type']=type(exc).__name__
    if isinstance(exc,HTTPError):report['endpoint_http']=exc.code
finally:
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('AMAZON_RESALE_LINK_AUDIT_V12:',report.get('status'),
      'HTTP:',report.get('source_http'),
      'A11Y_LINKS:',report.get('accessibility_link_roles'),
      'LINKS_WITH_TARGET:',report.get('accessibility_link_roles_with_target'),
      'MARKDOWN_LINKS:',report.get('markdown_links_seen'),
      'PRODUCTS:',report.get('product_candidate_count'),
      'CATEGORIES:',report.get('category_candidate_count'),
      'DIAGNOSIS:',report.get('diagnosis'),flush=True)
if report['status'] in ('PROBE_CONNECTION_ERROR','SOURCE_LINK_AUDIT_FAILED','SOURCE_RATE_LIMITED',
                        'SOURCE_REDIRECT_UNVERIFIED','SOURCE_CAPTCHA_REQUIRES_REVIEW'):
    raise SystemExit('AMAZON_RESALE_LINK_AUDIT_V12_NEEDS_REVIEW')
print('AMAZON_RESALE_LINK_AUDIT_V12_DIAGNOSTIC_COMPLETE',flush=True)
