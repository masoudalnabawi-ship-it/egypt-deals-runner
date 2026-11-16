"""Read-only, bounded sitemap discovery for B.TECH/2B. No production writes or alerts."""
from __future__ import annotations
import argparse
import html
from html.parser import HTMLParser
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from device_store_scanner import HOSTS, target

SITEMAP_HINT = re.compile(r'(?:product|item|catalog|sitemap)', re.I)
PRODUCT_HINT = re.compile(r'(?:/p/|/product/|/products/|/item/|/dp/)', re.I)
CATEGORY_SEEDS = {
 '2b': ['/ar/computers/laptops.html','/ar/mobile-and-tablet/mobiles.html','/ar/televisions/tvs.html','/ar/computers/desktops-all-in-ones.html','/ar/computers/printers.html'],
 'btech': ['/']
}
EXCLUDE = re.compile(
 r'accessor|charg|cable|case|cover|screen.protector|adapter|headphone|earphone|'
 r'gaming.acc|supplies|power.bank|bags|usb.flash|hard.driv|wireless.adapter|'
 r'keyboard|mouse|converter|presenter|cartridge|ink|toner|range.extender|'
 r'router|switch|/storage/|/network/|/media/|/offers/|/home.pag|'
 r'printer.suppl|cooling.pad|stand|speaker|webcam|memory.card|ssd|hdd|'
 r'flash.drive|monitor.arm|mouse.pad|power.outlet|/gaming/|\bcard.reader\b|\bbackpack\b|\bshoulder.bag\b|\btrolley\b|\blaptop.lock\b|\bconnecting.solution\b', re.I)
DEVICE = re.compile(
 r'iphone|ipad|galaxy|smartphone|mobile.phone|mobile-|tablet|laptop|notebook|'
 r'macbook|imac|desktop|all.in.one|television|smart.tv|led.tv|oled|qled|'
 r'printer|washing.machine|refrigerator|fridge|freezer|dishwasher|'
 r'microwave|air.conditioner|air.fryer|vacuum.cleaner|cooker|oven|'
 r'بوتاجاز|ثلاجة|غسالة|تليفزيون|موبايل|لابتوب', re.I)
CATEGORY_LEAF = re.compile(
 r'^(?:computers|mobiles|mobile.tablet|tablets|laptops|printers|tvs|'
 r'televisions|home.appliances|desktops.all.in.ones|samsung|apple|'
 r'huawei|infinix|acer|hp|lenovo|dell|asus|lg|sony|toshiba|'
 r'laser.jet|inkjet|professional|gaming|offers|home.page.tv.home.applaince)$', re.I)
CATEGORY = re.compile(r'/(?:computers|mobile.and.tablet|mobiles|laptops|televisions|tvs|appliances|printers|desktops|tablets)(?:/|$)', re.I)
PAGE = re.compile(r'\.html$',re.I)
class Anchors(HTMLParser):
 def __init__(self):
  super().__init__(); self.links=[]
 def handle_starttag(self,tag,attrs):
  if tag=='a':
   u=dict(attrs).get('href')
   if u: self.links.append(html.unescape(u))

def page_links(store, url, max_bytes=2_000_000):
 if not safe_url(store,url): return []
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'text/html'})
 with urllib.request.urlopen(req,timeout=12) as resp:
  if not safe_url(store,resp.geturl()): raise ValueError('unsafe_redirect')
  raw=resp.read(max_bytes+1)
  if len(raw)>max_bytes: raise ValueError('oversized_html')
  parser=Anchors(); parser.feed(raw.decode('utf-8','replace'))
  from urllib.parse import urldefrag
  return [urldefrag(urljoin(resp.geturl(),u))[0] for u in parser.links]

def is_product_url(store,url):
 if not safe_url(store,url): return False
 path=urlsplit(url).path.lower()
 if EXCLUDE.search(path): return False
 leaf=path.rsplit('/',1)[-1]
 if leaf in ('','index.html') or CATEGORY_LEAF.fullmatch(leaf.removesuffix('.html')): return False
 if store=='2b' and len(path.strip('/').split('/')) >= 3 and path.endswith('.html') and not re.search(r'\d',leaf): return False
 if store=='2b':
  if not PAGE.search(path): return False
  slug=leaf[:-5]
  return len(slug)>=16 and bool(DEVICE.search(slug)) and bool(re.search(r'\d',slug))
 if PRODUCT_HINT.search(path):
  return bool(DEVICE.search(path))
 return False

def discover_categories(store, limit=40, max_pages=8):
 origin='https://'+HOSTS[store][0]
 queue=[origin+p for p in CATEGORY_SEEDS[store]]
 visited=set(); products=[]; errors=[]
 while queue and len(visited)<max_pages and len(products)<limit:
  url=queue.pop(0)
  if url in visited: continue
  visited.add(url)
  try:
   for link in page_links(store,url):
    if not safe_url(store,link): continue
    if is_product_url(store,link):
     if link not in products: products.append(link)
    elif CATEGORY.search(urlsplit(link).path) and not EXCLUDE.search(link) and link not in visited and link not in queue and len(queue)<30:
     queue.append(link)
    if len(products)>=limit: break
  except (OSError,ValueError) as exc: errors.append({'page':url,'error':str(exc)[:100]})
 return products,errors

MAX_BYTES = 32_000_000  # bounded: larger retailer sitemaps, never unlimited


def safe_url(store: str, url: str) -> bool:
    try:
        p = urlsplit(url)
        return p.scheme == 'https' and p.hostname in HOSTS[store] and not p.username and not p.password and p.port in (None, 443)
    except ValueError:
        return False


def sitemap_urls(xml: bytes) -> tuple[list[str], list[str]]:
    root = ET.fromstring(xml)
    tag = root.tag.rsplit('}', 1)[-1]
    if tag not in ('urlset', 'sitemapindex'):
        return [], []
    locs = [el.text.strip() for el in root.iter() if el.tag.rsplit('}', 1)[-1] == 'loc' and el.text]
    return (locs, []) if tag == 'sitemapindex' else ([], locs)


def fetch(url: str, store: str) -> bytes:
    if not safe_url(store, url):
        raise ValueError('unsafe_sitemap_url')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; DeviceDealsReadOnly/1.0)', 'Accept': 'application/xml,text/xml,application/xhtml+xml'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not safe_url(store, newurl):
                raise ValueError('unsafe_redirect')
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    with urllib.request.build_opener(NoRedirect).open(req, timeout=15) as resp:
        if not safe_url(store, resp.geturl()):
            raise ValueError('unsafe_final_url')
        payload = resp.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise ValueError('oversized_sitemap')
        return payload


def discover(store: str, max_sitemaps=8, max_products=60) -> dict:
    if store not in HOSTS:
        raise ValueError('unsupported_store')
    origin = f'https://{HOSTS[store][0]}'
    queue = [origin + '/sitemap.xml', origin + '/sitemap_index.xml']
    visited = set()
    products = []
    errors = []
    while queue and len(visited) < max_sitemaps and len(products) < max_products:
        url = queue.pop(0)
        if url in visited or not safe_url(store, url):
            continue
        visited.add(url)
        try:
            children, urls = sitemap_urls(fetch(url, store))
            for child in children:
                if safe_url(store, child) and child not in visited and child not in queue and len(queue) < 100:
                    queue.append(child)
            for product in urls:
                if is_product_url(store, product) and product not in products:
                    products.append(product)
                    if len(products) >= max_products:
                        break
        except (ValueError, OSError, ET.ParseError) as exc:
            errors.append({'sitemap': url, 'error': str(exc)[:120]})
    # Sitemap may contain category pages rather than products. Discover actual product links.
    if len(products)<max_products:
        found, page_errors = discover_categories(store, max_products-len(products))
        errors.extend(page_errors)
        for item in found:
            if item not in products: products.append(item)
    return {'store': store, 'targets': [{'store': store, 'url': url} for url in products], 'sitemaps_checked': len(visited), 'errors': errors}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('device_store_targets.json'))
    parser.add_argument('--max-products-per-store', type=int, default=40)
    args = parser.parse_args()
    if not 1 <= args.max_products_per_store <= 200:
        parser.error('max products must be 1..200')
    results = [discover(s, max_products=args.max_products_per_store) for s in HOSTS]
    targets = [t for result in results for t in result['targets']]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(targets, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'targets': len(targets), 'output': str(args.output), 'stores': results}, ensure_ascii=False))

if __name__ == '__main__':
    main()
