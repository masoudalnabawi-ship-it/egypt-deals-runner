#!/usr/bin/env python3
"""Single, non-publishing Amazon.eg used-offer product-page test for a known ASIN.

Does not query rate-limited offer listings. A product-page price is a candidate,
not proof of an orderable second-hand item. Scope: isolated used-probe worker only.
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
import json
import os
import re
import sys

BASE='https://egypt-amazon-used-probe.masoud-amazon-eg.workers.dev/'
TARGET='B0DBHRWRKC'
OUT=Path(__file__).resolve().parent/'reports'/'amazon_used_known_product.json'


def interpret_response(data, asin):
    """Return only safe, explicitly tentative product-page observations."""
    if not isinstance(data, dict) or data.get('asin') != asin:
        raise ValueError('ASIN_RESPONSE_MISMATCH')
    p=data.get('product_page') or {}
    if not isinstance(p,dict):
        raise ValueError('INVALID_PRODUCT_PAGE')
    title=''
    for r in (p.get('elements') or []):
        if isinstance(r,dict) and r.get('selector')=='#productTitle':
            title=str(next(iter(r.get('samples') or []),'')).strip()[:300]
            break
    offers=data.get('product_page_used_offers') or []
    if not isinstance(offers,list):
        offers=[]
    candidate=data.get('lowest_used_price_candidate')
    candidate=round(float(candidate),2) if isinstance(candidate,(int,float)) and not isinstance(candidate,bool) and 0 < candidate < 1000000 else None
    new=data.get('new_price')
    new=round(float(new),2) if isinstance(new,(int,float)) and not isinstance(new,bool) and 0 < new < 1000000 else None
    status=str(data.get('status','UNKNOWN'))[:80]
    result={
        'asin':asin,'status':status,'product_http':p.get('http'),
        'product_title':title,'new_price_observed':new,
        'used_price_candidate':candidate,
        'used_condition_candidates':list(dict.fromkeys(str(x.get('condition','UNKNOWN'))[:60] for x in offers if isinstance(x,dict)))[:8],
        'saving_percent_candidate':round((1-candidate/new)*100,1) if new and candidate and candidate<new else None,
        'used_price_verified':False,'checkout_verified':False,
        'public_posting_enabled':False,
        'product_url':f'https://www.amazon.eg/dp/{asin}',
    }
    if p.get('http') != 200 or p.get('blocked') or status in ('PRODUCT_RATE_LIMITED','BLOCKED_CAPTCHA','PRODUCT_BROWSER_ERROR','ERROR'):
        result['diagnosis']='PRODUCT_NOT_READABLE'
    elif asin==TARGET and not (re.search(r'redmi',title,re.I) or 'ريدمي' in title):
        result['diagnosis']='TITLE_NOT_MATCHING_EXPECTED_REDMI'
    elif candidate is None:
        result['diagnosis']='NO_USED_PRICE_VISIBLE_ON_THIS_PRODUCT_PAGE'
    else:
        result['diagnosis']='USED_PRICE_CANDIDATE_MANUAL_CHECK_REQUIRED'
    return result


def main():
    asin=(sys.argv[1] if len(sys.argv)>1 else TARGET).strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{10}',asin):
        raise SystemExit('INVALID_TARGET_ASIN')
    key=os.environ.get('PROBE_KEY','')
    if not key:
        raise SystemExit('PROBE_KEY_MISSING')
    OUT.parent.mkdir(parents=True,exist_ok=True)
    report={'checked_at':datetime.now(timezone.utc).isoformat(),
            'source_shared_short_link':'https://amzn.eu/d/02jVqMPl',
            'short_link_redirect_verified':False,
            'requested_asin':asin,
            'public_posting_enabled':False,'used_price_verified':False,
            'diagnosis':'NOT_RUN'}
    try:
        from probe_transport import fetch_json_via_curl
        # Exactly one request to isolated worker and one product page, no retries.
        raw=fetch_json_via_curl(BASE+'?'+urlencode({'asin':asin,'main_only':'1'}),key)
        report.update(interpret_response(raw,asin))
    except (HTTPError,URLError,ValueError,TimeoutError) as exc:
        report['diagnosis']='PROBE_CONNECTION_ERROR'
        report['error_type']=type(exc).__name__
        if isinstance(exc,HTTPError):report['endpoint_http']=exc.code
    finally:
        OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('AMAZON_USED_REDMI_CHECK',
          'ASIN',asin,'HTTP',report.get('product_http'),
          'NEW',report.get('new_price_observed'),
          'USED_CANDIDATE',report.get('used_price_candidate'),
          'DIAGNOSIS',report['diagnosis'],
          'VERIFIED',False,flush=True)
    if report['diagnosis'] in ('PROBE_CONNECTION_ERROR','PRODUCT_NOT_READABLE','TITLE_NOT_MATCHING_EXPECTED_REDMI'):
        raise SystemExit('AMAZON_USED_REDMI_REQUIRES_REVIEW')
    print('AMAZON_USED_REDMI_CHECK_COMPLETE',flush=True)


if __name__=='__main__':
    main()
