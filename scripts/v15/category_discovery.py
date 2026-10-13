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

# V15_DISCOVERY_V4: rotate real source URLs, not only ASIN positions.
# Public pages only; bounded requests; no CAPTCHA or access-control bypass.
from urllib.parse import urlencode

# V13-inspired Ultra radar: public Amazon search surfaces.
# Search filters are discovery hints, NOT proof of a verified discount.
# V15_V14_INSPIRED_SURFACES
# Adapted from V14's productive discovery strategy.
# These URLs are discovery hints; Amazon may reject individual requests.
ULTRA_SURFACES = (
    ("goldbox", "https://www.amazon.eg/gp/goldbox/"),
    ("limited_time", "https://www.amazon.eg/s?k=limited+time+deals"),
    ("clearance", "https://www.amazon.eg/s?k=clearance+deals"),
    ("90off", "https://www.amazon.eg/s?k=90%25+off+deals"),
    ("75off", "https://www.amazon.eg/s?k=75%25+off+deals"),
    ("70off", "https://www.amazon.eg/s?k=70%25+off+deals"),
    ("65off", "https://www.amazon.eg/s?k=65%25+off+deals"),
)

ULTRA_SEARCH_TERMS = (
    "electronics", "television", "laptop", "headphones",
    "home appliances", "beauty", "fashion", "toys",
)

def ultra_discovery_source(term, page=1):
    """Generate a public search URL with a 50%+ discount filter."""
    from urllib.parse import urlencode
    return "https://www.amazon.eg/-/en/s?" + urlencode({
        "k": term,
        "rh": "p_n_pct-off-with-tax:270",
        "page": page,
    })

SEARCH_TERMS = {
    "electronics": ("headphones", "smart tv", "bluetooth speaker", "camera"),
    "computers": ("laptop", "monitor", "keyboard", "ssd"),
    "home": ("kitchen", "vacuum cleaner", "air fryer", "coffee maker"),
    "beauty": ("skincare", "shampoo", "perfume", "hair dryer"),
    "fashion": ("shoes", "backpack", "watch", "jacket"),
    "grocery": ("coffee", "chocolate", "detergent", "olive oil"),
    "toys": ("lego", "puzzle", "remote control car", "board games"),
    "sports": ("fitness", "football", "running shoes", "dumbbells"),
}

def discovery_source(name, landing_url, visit):
    """Return a different public Amazon search URL on successive visits."""
    terms = SEARCH_TERMS.get(name, ())
    if not terms:
        return landing_url

    # Alternate landing pages with rotating search terms and result pages.
    mode = visit % (len(terms) * 3 + 1)
    if mode == 0:
        return landing_url

    index = mode - 1
    term = terms[index % len(terms)]
    page = 1 + ((index // len(terms)) % 3)

    return "https://www.amazon.eg/-/en/s?" + urlencode({
        "k": term,
        "page": page,
    })

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
    offset=(int(now.timestamp())//300*4)%len(CATEGORIES)
    selected=[CATEGORIES[(offset+i)%len(CATEGORIES)] for i in range(4)]
    discovered=set()
    # V15_DISCOVERY_V3: on successive visits, rotate through a category's
    # ASINs instead of repeatedly sampling its first 12 entries.
    slot=int(now.timestamp())//300
    visit=slot//(len(CATEGORIES)//2)
    for name,url in selected:
        try:
            source_url=discovery_source(name,url,visit)
            try:
                body=fetch(source_url)
                asins=extract_asins(body)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                print('V15_DISCOVERY_PRIMARY_FAILED',name,type(exc).__name__,flush=True)
                asins=[]

            if not asins and source_url != url:
                try:
                    asins=extract_asins(fetch(url))
                    print('V15_DISCOVERY_FALLBACK',name,len(asins),flush=True)
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    print('V15_DISCOVERY_FALLBACK_FAILED',name,type(exc).__name__,flush=True)
                    asins=[]
            print('V15_DISCOVERY_CATEGORY',name,'found',len(asins),'source',source_url.split('?')[0],flush=True)
            if asins:
                take=min(40,len(asins))
                start=(visit*take)%len(asins)
                rotated=(asins+asins)[start:start+take]
                discovered.update(rotated)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print('V15_DISCOVERY_UNAVAILABLE',name,type(exc).__name__,flush=True)
        time.sleep(2)
    # V13-inspired Ultra discovery: candidate collection only.
    # Never treat a search filter as verified discount evidence.
    def extract_ultra_badges(html):
        """Read displayed search-card discount badges; discovery hints only."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        result = {}

        for card in soup.select(
            "[data-component-type='s-search-result'][data-asin]"
        ):
            asin = str(card.get("data-asin") or "").strip().upper()
            if not re.fullmatch(r"[A-Z0-9]{10}", asin):
                continue

            for badge in card.select(
                ".savingsPercentage, [class*='savingsPercentage']"
            ):
                match = re.search(
                    r"-?\s*(\d+(?:\.\d+)?)\s*%",
                    badge.get_text(" ", strip=True)
                )
                if not match:
                    continue

                percent = float(match.group(1))
                if 50.0 <= percent < 100.0:
                    result[asin] = max(
                        percent, result.get(asin, 0.0)
                    )

        return result

    ultra_slot = int(now.timestamp()) // 300
    ultra_found = set()
    ultra_verified_hints = set()
    ultra_discount_hints = {}

    # Always check Goldbox; rotate two additional V14-inspired sources.
    rotating = ULTRA_SURFACES[1:]
    selected_surfaces = [
        ULTRA_SURFACES[0],
        rotating[ultra_slot % len(rotating)],
        rotating[(ultra_slot + 1) % len(rotating)],
    ]

    for name, url in selected_surfaces:
        try:
            body = fetch(url)
            asins = set(extract_asins(body))

            # V15 reads high-discount badges independently of V14's
            # 90% derived-price ceiling.
            badge_hints = extract_ultra_badges(body)
            asins.update(badge_hints)
            for asin, discount in badge_hints.items():
                ultra_verified_hints.add(asin)
                ultra_discount_hints[asin] = max(
                    discount,
                    ultra_discount_hints.get(asin, 0.0)
                )

            # V14 parser handles structured Goldbox and search-card data.
            # Import only: V14 source files and runtime state are unchanged.
            try:
                import sys
                from pathlib import Path
                repo_root = str(Path(__file__).resolve().parents[2])
                if repo_root not in sys.path:
                    sys.path.insert(0, repo_root)
                from deals_v14.discovery.amazon import AmazonDiscovery
                from deals_v14.discovery.scheduler import Surface

                surface = Surface(name, "global", url)
                parsed = AmazonDiscovery.parse_search(body, surface)
                for item in parsed:
                    asin = str(item.external_id).upper()
                    if not re.fullmatch(r"[A-Z0-9]{10}", asin):
                        continue

                    asins.add(asin)

                    # Displayed discovery discounts are hints only.
                    # A live product-page check is still mandatory.
                    try:
                        discount = float(item.discount_percent)
                    except (TypeError, ValueError, AttributeError):
                        discount = 0.0

                    if discount >= 50.0:
                        ultra_verified_hints.add(asin)
                        ultra_discount_hints[asin] = max(
                            discount,
                            ultra_discount_hints.get(asin, 0.0)
                        )
            except (ImportError, ValueError, AttributeError) as exc:
                print(
                    "V15_ULTRA_PARSER_FALLBACK",
                    name,
                    type(exc).__name__,
                    flush=True
                )

            # Prioritize displayed 50%+ discount hints before other ASINs.
            # These are discovery signals, NOT verified discounts.
            ranked_asins = sorted(
                asins,
                key=lambda asin: (
                    -ultra_discount_hints.get(asin, 0.0),
                    asin
                )
            )
            ultra_found.update(ranked_asins[:40])
            print(
                "V15_ULTRA_SURFACE",
                name,
                "found",
                len(asins),
                flush=True
            )

        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(
                "V15_ULTRA_SURFACE_FAILED",
                name,
                type(exc).__name__,
                flush=True
            )

        time.sleep(2)

    discovered.update(ultra_found)
    print("V15_ULTRA_RADAR_FOUND", len(ultra_found), flush=True)

    # Ultra candidate ASINs are discovery hints, not verified deals.
    # Keep them separate so the scheduler can prioritize them safely.
    # HOT only for candidates with a displayed 50%+ discount.
    # This is NOT verification of the original price.
    ultra_candidate_asins = ultra_verified_hints & ultra_found
    print("V15_ULTRA_PRIORITY_CANDIDATES", len(ultra_candidate_asins), flush=True)

    # V15 private early-warning lane:
    # displayed Amazon discount >=50%; historical price verification NOT required.
    # Public Telegram publication is never invoked here.
    if ultra_candidate_asins:
        try:
            from flash_dedup import initialize, send_once
            from flash_private_alert import send

            initialize()

            for asin in sorted(
                ultra_candidate_asins,
                key=lambda value: (
                    -ultra_discount_hints.get(value, 0.0),
                    value
                )
            ):
                discount = ultra_discount_hints.get(asin, 0.0)

                if not 50.0 <= discount < 100.0:
                    continue

                candidate = {
                    "asin": asin,
                    "title": "منتج على أمازون مصر",
                    "displayed_discount_pct": str(discount),
                    "category": (
                        "FLASH" if discount >= 90
                        else "SUPER_ULTRA" if discount >= 70
                        else "ULTRA"
                    ),
                    "current_price": None,
                    "status": "AMAZON_DISPLAYED_DISCOUNT_UNVERIFIED",
                    "publication_allowed": False,
                }

                try:
                    result = send_once(candidate, send)
                    print(
                        "V15_ULTRA_PRIVATE_ALERT",
                        asin,
                        result,
                        flush=True
                    )
                except Exception as exc:
                    print(
                        "V15_ULTRA_PRIVATE_ALERT_FAILED",
                        asin,
                        type(exc).__name__,
                        flush=True
                    )

        except Exception as exc:
            print(
                "V15_ULTRA_ALERT_SETUP_FAILED",
                type(exc).__name__,
                flush=True
            )


    # Batch INSERT OR IGNORE: never overwrite existing priorities, leases or schedules.
    # Look up existing products in one bounded D1 query; only seed new ASINs.
    # Never modify an existing product's priority, lease or schedule.
    from book_filter import classify
    candidates=sorted(asin for asin in discovered if not classify(asin=asin))
    known=set()
    for offset in range(0, len(candidates), 100):
        batch = candidates[offset:offset + 100]
        rows = query('SELECT asin FROM product_monitoring WHERE asin IN (' +
                     ','.join(quote(asin) for asin in batch) + ');')
        known.update(str(row['asin']).upper() for row in rows)
    # Give new Ultra radar candidates first access to the bounded seed batch.
    # Search results are unverified; HOT means urgent verification only.
    fresh = [asin for asin in candidates if asin not in known]
    asins = sorted(
        fresh,
        key=lambda asin: (
            -ultra_discount_hints.get(asin, 0.0),
            asin
        )
    )[:80]
    print('V15_DISCOVERY_CANDIDATES',len(candidates),flush=True)
    print('V15_DISCOVERY_ALREADY_KNOWN',len(known),flush=True)
    if asins:
        stamp=timestamp(now)
        values=','.join(
            '('+','.join(map(quote,(
                asin,
                'HOT' if asin in ultra_candidate_asins else 'STABLE',
                stamp,
                stamp
            )))+')'
            for asin in asins
        )
        query('INSERT OR IGNORE INTO product_monitoring (asin,priority,next_check_at,updated_at) VALUES '+values+';')

    print('V15_DISCOVERY_ATTEMPTED',len(asins),flush=True)
    print('V15_DISCOVERY_NEW_COUNT','not_measured',flush=True)
    print('V15_DISCOVERY_STATS','full_table_counts_disabled',flush=True)

if __name__=='__main__':main()
