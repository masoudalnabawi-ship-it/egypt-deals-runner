import json, re, urllib.request, urllib.parse, time, os
import math

# ROTATION_COPRIME_V2: avoid missing branches/categories when batch and total
# share a common divisor (e.g. three branches per run in a nine-branch catalog).
def fair_start(slot, total, batch):
    if total <= batch: return 0
    step = batch
    while math.gcd(step, total) != 1:
        step += 1
    return (slot * step) % total

from pathlib import Path
from html import unescape
from collections import Counter
from talabat_price_capture import capture_price_observation

base = "https://www.talabat.com"
seeds = json.loads(Path("reports/talabat_branch_seeds.json").read_text())

# DYNAMIC_ALL_EGYPT_BRANCHES_V1
catalog_path = Path('reports/talabat_discovered_branches.json')
if catalog_path.is_file():
    discovered = json.loads(catalog_path.read_text(encoding='utf-8'))
    if not isinstance(discovered, list):
        raise ValueError('INVALID_DYNAMIC_BRANCH_CATALOG')
    by_id = {str(b['branch_id']): b for b in seeds}
    for b in discovered:
        if not isinstance(b, dict) or not str(b.get('branch_id', '')).isdigit():
            continue
        if not isinstance(b.get('source'), str) or not b['source'].startswith('https://www.talabat.com/egypt/grocery/'):
            continue
        by_id[str(b['branch_id'])] = b
    seeds = sorted(by_id.values(), key=lambda b: int(b['branch_id']))

all_branch_count = len(seeds)
# FAST_REAL_TMART_FIRST_V1: keep tKiosk in catalog for discovery/deep scan,
# but use real tMart storefronts for the frequent, time-limited watch.
if os.getenv('TALABAT_FAST') == '1' and seeds:
    real_mart = [
        b for b in seeds
        if 'kiosk' not in str(b.get('branch_name') or '').lower()
        and re.search(r'\b(?:talabat\s*mart|tmart)\b',
                      str(b.get('branch_name') or ''), re.I)
    ]
    print('FAST_REAL_TMART_BRANCHES:', len(real_mart),
          'SKIPPED_KIOSK_OR_OTHER:', len(seeds) - len(real_mart), flush=True)
    if not real_mart:
        raise RuntimeError('NO_REAL_TMART_BRANCHES_IN_CATALOG')
    seeds = real_mart

if os.getenv('TALABAT_FAST') == '1' and seeds:
    # Three different branches per five-minute slot; all discovered branches rotate.
    size = min(3, len(seeds))
    offset = fair_start(int(time.time() // 300), len(seeds), size)
    seeds = [seeds[(offset+i) % len(seeds)] for i in range(size)]
elif len(seeds) > 3:
    # Deep scan is sharded too; don't overload a single Actions job.
    size = min(2, len(seeds))
    offset = fair_start(int(time.time() // 21600), len(seeds), size)
    seeds = [seeds[(offset+i) % len(seeds)] for i in range(size)]
print('BRANCH_CATALOG_TOTAL:', all_branch_count, 'THIS_RUN:', len(seeds), flush=True)

results = []
stock_unverified = {}  # >=40% price evidence; NOT verified stock
summary = []
# PRICE_HISTORY_STATE_V1
price_observations = {}
history_stats = Counter()


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-EG,en;q=0.9"
    })
    with urllib.request.urlopen(req, timeout=18) as r:
        final = urllib.parse.urlsplit(r.geturl())
        if final.scheme != "https" or final.hostname != "www.talabat.com":
            raise ValueError("UNEXPECTED_REDIRECT")
        return r.read(2500000).decode("utf-8", "replace")

def state_of(html):
    m = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.I | re.S
    )
    if not m:
        raise ValueError("NEXT_DATA_MISSING")
    return json.loads(m.group(1))["props"]["pageProps"]["initialState"]

for branch in seeds:
    bid = str(branch["branch_id"])
    root = branch["source"]
    parsed = urllib.parse.urlsplit(root)
    prefix = parsed.path.rstrip("/") + "/"
    aid = urllib.parse.parse_qs(parsed.query).get("aid", [""])[0]

    print("\nBRANCH:", branch["area"], bid, flush=True)

    try:
        landing = fetch(root)
        links = []

        for raw in re.findall(r'href=["\']([^"\']+)["\']', landing, re.I):
            u = urllib.parse.urlsplit(
                urllib.parse.urljoin(root, unescape(raw))
            )
            if u.hostname != "www.talabat.com":
                continue
            if not u.path.startswith(prefix):
                continue
            if "/p/" in u.path:
                continue

            url = base + u.path
            if aid:
                url += "?aid=" + urllib.parse.quote(aid)
            if url not in links:
                links.append(url)

        priority = (
            "electronics", "stationery", "household",
            "cleaning", "beauty", "snacks", "appliances"
        )
        links.sort(key=lambda u: not any(k in u.lower() for k in priority))
        # Scan all discovered category links


        # FULL_CATALOG_SCAN_V2
        catalog = state_of(landing).get("categories") or []
        extra_links = set()

        def walk_category(node, parents=()):
            if not isinstance(node, dict):
                return

            slug = node.get("slug")
            if not isinstance(slug, str):
                return
            if not re.fullmatch(r"[a-zA-Z0-9_-]+", slug):
                return

            parts = parents + (slug,)
            u = base + prefix + "/".join(parts)

            if aid:
                u += "?aid=" + urllib.parse.quote(aid)

            extra_links.add(u)

            for child in node.get("subCategories") or []:
                walk_category(child, parts)

        for category in catalog:
            walk_category(category)

        before = len(links)
        existing = set(links)
        links.extend(sorted(extra_links - existing))
        added_category_links = len(links) - before

        # FAST_ROTATING_WINDOW_V1
        if os.getenv("TALABAT_FAST") == "1" and links:
            # Broaden rolling category window without changing branch rotation.
            size = 12
            cursor = fair_start(int(time.time() // 300), len(links), size)
            links = [
                links[(cursor + i) % len(links)]
                for i in range(min(size, len(links)))
            ]
            print("FAST_WINDOW:", len(links), "START:", cursor)

        print("MAIN_CATEGORIES:", len(catalog))
        print("NEW_CATEGORY_LINKS:", added_category_links)
        print("TOTAL_PAGES_TO_SCAN:", len(links))
        count = 0
        checked = 0
        matches = 0
        local = {}

        for url in links:
            try:
                state = state_of(fetch(url))
                store = state.get("groceryStore", {})
                actual_id = str(store.get("branchId", ""))

                if actual_id != bid:
                    print("BRANCH_MISMATCH:", actual_id, bid)
                    continue

                matches += 1

                # PAGINATION_WORKING_V3
                meta = state.get("itemsData") or {}
                items = list(meta.get("items") or [])

                try:
                    total_pages = int(meta.get("pageCount") or 1)
                except (TypeError, ValueError):
                    total_pages = 1

                if total_pages > 100:
                    print("PAGE_LIMIT_WARNING:", total_pages)

                for page_number in range(2, min(total_pages, 2 if os.getenv("TALABAT_FAST") == "1" else 100) + 1):
                    parsed_page = urllib.parse.urlsplit(url)
                    params = urllib.parse.parse_qsl(
                        parsed_page.query, keep_blank_values=True
                    )
                    params = [(k, v) for k, v in params if k != "page"]
                    params.append(("page", str(page_number)))

                    next_url = urllib.parse.urlunsplit(
                        parsed_page._replace(
                            query=urllib.parse.urlencode(params)
                        )
                    )

                    try:
                        next_state = state_of(fetch(next_url))
                        next_store = next_state.get("groceryStore") or {}
                        next_meta = next_state.get("itemsData") or {}

                        if (
                            str(next_store.get("branchId")) != bid
                            or str(next_meta.get("currentPage")) != str(page_number)
                        ):
                            print("PAGE_MISMATCH:", page_number)
                            continue

                        items.extend(next_meta.get("items") or [])
                        checked += 1
                        time.sleep(0.3)

                    except Exception as e:
                        print("PAGE_ERROR:", page_number, type(e).__name__)
                checked += 1
                count += len(items)

                for item in items:
                    # PRICE_HISTORY_CAPTURE_V2: displayed prices are separate
                    # from confirmed availability and 40%-discount filtering.
                    observation = capture_price_observation(
                        item, bid, int(time.time()), history_stats)
                    if observation is not None:
                        price_observations[(bid, observation['sku'])] = observation
                    try:
                        old = float(item.get("originalPrice") or 0)
                        price = float(item.get("price") or 0)
                        raw_stock = item.get("stockAmount")
                        stock = None if raw_stock is None or raw_stock == "" else float(raw_stock)
                        if not (old > price > 0):
                            continue
                        discount = round((1 - price / old) * 100, 2)
                        if not 40 <= discount <= 99:
                            continue
                        sku = str(item.get("sku") or "")
                        if not sku:
                            continue
                        if stock is None:
                            # Keep as a diagnostic candidate; never send to Telegram as confirmed.
                            key = (bid, sku)
                            if (key not in stock_unverified or
                                stock_unverified[key]["discount"] < discount):
                                stock_unverified[key] = {
                                    "branch_id": bid,
                                    "area": branch["area"],
                                    "sku": sku,
                                    "title": item.get("title"),
                                    "price": price,
                                    "original_price": old,
                                    "discount": discount,
                                    "stock_status": "unknown",
                                    "source": url,
                                    "observed_at": int(time.time()),
                                }
                            continue
                        if stock <= 0:
                            continue
                        # KEEP_HIGHEST_DISCOUNT_V1
                        if sku in local and local[sku]["discount"] >= discount:
                            continue
                        local[sku] = {
                            "branch_id": bid,
                            "branch_name": store.get("branchName"),
                            "area": branch["area"],
                            "sku": sku,
                            "product_id": item.get("id"),
                            "slug": item.get("slug"),
                            "category_id": item.get("categoryId"),
                            "title": item.get("title"),
                            "price": price,
                            "original_price": old,
                            "discount": discount,
                            "stock": stock,
                            "source": url,
                            "branch_matched": True,
                            "delivery_verified": False,
                            "observed_at": int(time.time())
                        }
                    except (TypeError, ValueError, AttributeError):
                        continue
            except Exception as e:
                print("PAGE_ERROR:", type(e).__name__, str(e)[:65])
            time.sleep(0.3)

        results.extend(local.values())
        summary.append({
            "area": branch["area"],
            "branch_id": bid,
            "links_found": len(links),
            "pages_checked": checked,
            "branch_matches": matches,
            "products": count,
            "offers": len(local)
        })
        print("PAGES:", checked, "PRODUCTS:", count, "OFFERS:", len(local))

    except Exception as e:
        print("BRANCH_ERROR:", type(e).__name__, str(e)[:100])

# PRICE_HISTORY_REPORT_V1: observations remain separate from candidate deals.
Path("reports/talabat_price_observations.json").write_text(
    json.dumps({"observations": list(price_observations.values()),
                "captured_at": int(time.time()),
                "data_source": "observed_catalog_prices_not_claimed_originals"},
               ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
)
print("PRICE_HISTORY_OBSERVATIONS:", len(price_observations), flush=True)
print("PRICE_HISTORY_CAPTURE_DIAGNOSTICS:", dict(history_stats), flush=True)
if history_stats["items_seen"] and not price_observations:
    print("PRICE_HISTORY_CAPTURE_WARNING: all displayed products missing recognizable ID or price", flush=True)

Path("reports/talabat_multi_branch.json").write_text(
    json.dumps(
        {"branches": summary, "offers": results,
         "stock_unverified": list(stock_unverified.values())},
        ensure_ascii=False, indent=2
    )
)

print("\nTOTAL_BRANCHES:", len(summary))
print("TOTAL_OFFERS_40_PLUS:", len(results))
print("TOTAL_40_PLUS_STOCK_UNVERIFIED:", len(stock_unverified))
print("REPORT: reports/talabat_multi_branch.json")
for x in sorted(results, key=lambda a: -a["discount"])[:12]:
    print("OFFER:", x["area"], x["discount"], "%", x["title"])
print("DELIVERY_ADDRESS_VERIFICATION: PENDING")
