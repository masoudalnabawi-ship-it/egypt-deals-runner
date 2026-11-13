"""Incrementally discover publicly listed Talabat Mart branches in Egypt.

Uses the public grocery-area index and area store pages. Stores ONLY verified
mart branches (matching groceryStore.branchId and mart branding). Not a claim
that private/hidden or address-gated branches are comprehensively exposed.
"""
import concurrent.futures
import json
import os
import re
import time
import urllib.parse
import urllib.request
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

BASE = 'https://www.talabat.com'
INDEX = BASE + '/egypt/all-areas/groceries'
OUT = Path('reports/talabat_discovered_branches.json')
STATUS = Path('reports/talabat_discovery_status.json')
BATCH = max(1, min(int(os.getenv('TALABAT_DISCOVERY_BATCH', '80')), 300))
WORKERS = max(1, min(int(os.getenv('TALABAT_DISCOVERY_WORKERS', '6')), 10))
MART = re.compile(r'talabat[\s-]*mart|tmart', re.I)
AREA_RE = re.compile(r'^/egypt/groceries/(\d{2,8})/([a-z0-9-]+)/?$', re.I)
STORE_RE = re.compile(r'^/egypt/grocery/(\d{3,10})/([a-z0-9-]+)/?$', re.I)
UA = 'Mozilla/5.0 (compatible; TalabatBranchDirectoryResearch/1.0)'


def get(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme != 'https' or u.hostname != 'www.talabat.com':
        raise ValueError('UNTRUSTED_URL')
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Accept-Language': 'en-EG,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml'
    })
    with urllib.request.urlopen(req, timeout=18) as response:
        final = urllib.parse.urlsplit(response.geturl())
        if final.scheme != 'https' or final.hostname != 'www.talabat.com':
            raise ValueError('UNTRUSTED_REDIRECT')
        if response.status != 200:
            raise ValueError('HTTP_' + str(response.status))
        return response.read(9_000_000).decode('utf-8', 'replace')


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == 'a' and self.current is None:
            self.current = {'href': d.get('href', ''), 'text': ''}
        if self.current is not None and tag == 'img':
            self.current['text'] += ' ' + str(d.get('alt', '')) + ' '

    def handle_data(self, data):
        if self.current is not None:
            self.current['text'] += data[:500]

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            self.links.append(self.current)
            self.current = None


def anchors(html):
    a = Anchors()
    a.feed(html)
    return a.links


def canonical(raw):
    url = urllib.parse.urlsplit(urllib.parse.urljoin(BASE, unescape(raw)))
    if url.scheme != 'https' or url.hostname != 'www.talabat.com':
        return None
    return url


def areas_from_index(html):
    found = {}
    for a in anchors(html):
        u = canonical(a['href'])
        if not u:
            continue
        m = AREA_RE.fullmatch(u.path)
        if not m:
            continue
        aid, slug = m.groups()
        found[aid] = {
            'area_id': aid,
            'slug': slug,
            'label': re.sub(r'\s+', ' ', a['text']).strip()[:140]
                     or slug.replace('-', ' ').title(),
            'url': BASE + u.path,
        }
    return sorted(found.values(), key=lambda x: int(x['area_id']))


def stores_from_area(html, area):
    choices = []
    seen = set()
    for a in anchors(html):
        u = canonical(a['href'])
        if not u:
            continue
        match = STORE_RE.fullmatch(u.path)
        if not match:
            continue
        branch_id, slug = match.groups()
        if branch_id in seen:
            continue
        seen.add(branch_id)
        query = urllib.parse.parse_qs(u.query)
        aid = query.get('aid', [area['area_id']])[0]
        if not aid.isdigit():
            aid = area['area_id']
        url = BASE + u.path + '?aid=' + urllib.parse.quote(aid)
        hint = bool(MART.search(a['text'] + ' ' + slug))
        choices.append((0 if hint else 1, url, branch_id, a['text'][:80]))
    # The first store card can be the "tmart / Shop now" banner. A link is
    # considered verified only after inspecting the merchant landing page.
    ranked = sorted(choices, key=lambda x: x[0])
    hinted = [x for x in ranked if x[0] == 0]
    return (hinted[:5] if hinted else ranked[:2])


def validated_mart(url, claimed_id, area):
    html = get(url)
    state_match = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.I | re.S)
    if not state_match:
        return None
    try:
        state = json.loads(state_match.group(1))['props']['pageProps']['initialState']
        store = state.get('groceryStore') or {}
    except (KeyError, TypeError, ValueError):
        return None
    actual = str(store.get('branchId') or '')
    if actual != claimed_id:
        return None
    branch_name = str(store.get('branchName') or store.get('name') or '')
    title = re.search(r'<title[^>]*>([^<]{0,300})</title>', html, re.I)
    title_text = unescape(title.group(1)) if title else ''
    if not MART.search(branch_name + ' ' + title_text):
        return None
    return {
        'area': area['label'],
        'branch_id': actual,
        'branch_name': branch_name or title_text[:120],
        'source': url,
        'prices_verified': False,
        'discovered_via': 'talabat_public_grocery_directory',
        'service_area_id': area['area_id'],
    }


def discover_area(area):
    try:
        html = get(area['url'])
        candidates = stores_from_area(html, area)
        matches = []
        for _, url, bid, _ in candidates:
            try:
                rec = validated_mart(url, bid, area)
                if rec:
                    matches.append(rec)
            except Exception:
                continue
        return (area, matches, None, len(candidates))
    except Exception as exc:
        return (area, [], type(exc).__name__, 0)


def main():
    if OUT.exists():
        old = json.loads(OUT.read_text(encoding='utf-8'))
        if not isinstance(old, list):
            raise ValueError('INVALID_EXISTING_CATALOG')
    else:
        old = []
    known = {str(b['branch_id']): b for b in old if b.get('branch_id')}

    area_list = areas_from_index(get(INDEX))
    if not area_list:
        raise RuntimeError('PUBLIC_DIRECTORY_HAS_NO_AREAS: CATALOG_UNCHANGED')

    total = len(area_list)
    groups = (total + BATCH - 1) // BATCH
    # Fixed-length time windows let hourly scheduled jobs explore every area
    # systematically without a stateful cursor or repeated full-directory scan.
    index = int(os.getenv('TALABAT_DISCOVERY_SHARD',
                          str(int(time.time() // 3600) % groups))) % groups
    start = index * BATCH
    batch = area_list[start:start+BATCH]
    print('AREAS_IN_EGYPT_DIRECTORY:', total, flush=True)
    print('AREA_SHARD:', index+1, '/', groups,
          'AREAS_IN_BATCH:', len(batch), flush=True)

    fresh = 0
    errors = []
    got_pages = 0
    candidates_tested = 0
    now = int(time.time())
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(discover_area, area) for area in batch]
        for future in concurrent.futures.as_completed(futures):
            area, branches, err, tested = future.result()
            candidates_tested += tested
            if err:
                errors.append({'area_id': area['area_id'], 'error': err})
                continue
            got_pages += 1
            for row in branches:
                bid = row['branch_id']
                if bid in known:
                    # Keep first verified source for a stable branch/area path.
                    known[bid]['last_seen'] = now
                    ids = set(str(x) for x in known[bid].get('service_area_ids', []))
                    ids.add(row['service_area_id'])
                    known[bid]['service_area_ids'] = sorted(ids, key=int)[:120]
                else:
                    row['first_seen'] = now
                    row['last_seen'] = now
                    row['service_area_ids'] = [row['service_area_id']]
                    known[bid] = row
                    fresh += 1
                    print('NEW_MART_BRANCH:', bid, row['branch_name'],
                          row['area'], flush=True)

    if got_pages == 0:
        raise RuntimeError('ALL_AREA_PAGES_FAILED: CATALOG_UNCHANGED')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(sorted(known.values(),key=lambda b:int(b['branch_id'])),
                              ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    report = {'areas_in_directory':total,'shards':groups,'this_shard':index+1,
              'areas_processed':len(batch),'areas_success':got_pages,
              'areas_failed':errors[:30],'candidates_checked':candidates_tested,
              'new_branches':fresh,'known_branches':len(known),
              'checked_at':now,
              'note':'Publicly reachable and validated mart branches only; not an exhaustive private inventory'}
    STATUS.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',
                      encoding='utf-8')
    print('NEW_BRANCHES:',fresh,flush=True)
    print('VERIFIED_DISCOVERED_BRANCHES:',len(known),flush=True)
    print('DISCOVERY_REPORT:',STATUS,flush=True)


if __name__ == '__main__':
    main()
