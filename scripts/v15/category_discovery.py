"""Bounded, public-page category discovery for Amazon Egypt; V15 only.
No CAPTCHA bypass, login, proxies, or automated purchase. Failed pages are skipped.
Coverage is progressive and best-effort, not a full Amazon catalog index.
"""
import html
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from d1_monitoring_lease import query, quote, timestamp

# Category landing pages; rotate two per run to limit load.
CATEGORIES = (
    ('electronics', 'https://www.amazon.eg/-/en/gp/browse.html?node=18018102031'),
    ('computers', 'https://www.amazon.eg/-/en/gp/browse.html?node=21832883031'),
    ('home', 'https://www.amazon.eg/-/en/gp/browse.html?node=18022560031'),
    ('beauty', 'https://www.amazon.eg/-/en/gp/browse.html?node=18017993031'),
    ('fashion', 'https://www.amazon.eg/-/en/gp/browse.html?node=18018292031'),
    ('grocery', 'https://www.amazon.eg/-/en/gp/browse.html?node=18017917031'),
    ('toys', 'https://www.amazon.eg/-/en/gp/browse.html?node=18022591031'),
    ('sports', 'https://www.amazon.eg/-/en/gp/browse.html?node=18022589031'),
)
ASIN_RE = re.compile(r'(?:/dp/|/gp/product/)([A-Z0-9]{10})(?![A-Z0-9])', re.I)
DATA_RE = re.compile(r'data-asin=["\']([A-Z0-9]{10})["\']', re.I)

def extract_asins(body):
    body=html.unescape(body)
    return sorted({x.upper() for x in ASIN_RE.findall(body)+DATA_RE.findall(body)
                   if len(x)==10 and x.isalnum()})

def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; V15ProductDiscovery/1.0)', 'Accept-Language':'en-EG,en;q=0.8'})
    with urllib.request.urlopen(req,timeout=18) as response:
        if response.status!=200:return ''
        content_type=response.headers.get('Content-Type','')
        if 'html' not in content_type.lower():return ''
        return response.read(1200000).decode('utf-8','replace')

def main():
    if not os.environ.get('CLOUDFLARE_API_TOKEN'):
        raise RuntimeError('V15_CLOUDFLARE_TOKEN_MISSING')
    now=datetime.now(timezone.utc)
    # Rotate category pair every 5-minute slot; bounded to two pages per run.
    offset=(int(now.timestamp())//300*2)%len(CATEGORIES)
    selected=[CATEGORIES[(offset+i)%len(CATEGORIES)] for i in range(2)]
    discovered=set()
    # V15_DISCOVERY_V3: on successive visits, rotate through a category's
    # ASINs instead of repeatedly sampling its first 12 entries.
    slot=int(now.timestamp())//300
    visit=slot//(len(CATEGORIES)//2)
    for name,url in selected:
        try:
            body=fetch(url)
            asins=extract_asins(body)
            print('V15_DISCOVERY_CATEGORY',name,'found',len(asins),flush=True)
            if asins:
                take=min(20,len(asins))
                start=(visit*take)%len(asins)
                rotated=(asins+asins)[start:start+take]
                discovered.update(rotated)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print('V15_DISCOVERY_UNAVAILABLE',name,type(exc).__name__,flush=True)
        time.sleep(2)
    # Batch INSERT OR IGNORE: never overwrite existing priorities, leases or schedules.
    # Look up existing products in one bounded D1 query; only seed new ASINs.
    # Never modify an existing product's priority, lease or schedule.
    from book_filter import classify
    candidates=sorted(asin for asin in discovered if not classify(asin=asin))
    known=set()
    if candidates:
        rows=query('SELECT asin FROM product_monitoring WHERE asin IN (' +
                   ','.join(quote(asin) for asin in candidates) + ');')
        known={str(row['asin']).upper() for row in rows}
    asins=[asin for asin in candidates if asin not in known][:20]
    print('V15_DISCOVERY_CANDIDATES',len(candidates),flush=True)
    print('V15_DISCOVERY_ALREADY_KNOWN',len(known),flush=True)
    before_rows=query('SELECT COUNT(*) AS total FROM product_monitoring;')
    before=int(before_rows[0]['total']) if before_rows else 0
    if asins:
        stamp=timestamp(now)
        values=','.join('('+','.join(map(quote,(asin,'STABLE',stamp,stamp)))+')' for asin in asins)
        query('INSERT OR IGNORE INTO product_monitoring (asin,priority,next_check_at,updated_at) VALUES '+values+';')
    after_rows=query('SELECT COUNT(*) AS total FROM product_monitoring;')
    after=int(after_rows[0]['total']) if after_rows else before
    print('V15_DISCOVERY_NEW',max(0,after-before),flush=True)
    print('V15_DISCOVERY_ATTEMPTED',len(asins),flush=True)
    print('V15_DISCOVERY_SEEDED',max(0,after-before),'actual_new_count',flush=True)
    # Read-only counters to distinguish no catalog from not-yet-due.
    try:
        rows=query("SELECT COUNT(*) AS total, SUM(CASE WHEN next_check_at <= strftime('%Y-%m-%dT%H:%M:%S+00:00','now') THEN 1 ELSE 0 END) AS due FROM product_monitoring;")
        print('V15_MONITORING_TOTAL',rows[0]['total'] if rows else 'unknown',flush=True)
    except Exception as exc:
        print('V15_DIAGNOSTIC_UNAVAILABLE',type(exc).__name__,flush=True)

if __name__=='__main__':main()
