import json, re, urllib.request, urllib.parse, time, os
from pathlib import Path
from html import unescape

base = "https://www.talabat.com"
seeds = json.loads(Path("reports/talabat_branch_seeds.json").read_text())
results = []
summary = []

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

        # FAST_ROTATING_WINDOW_V1
        if os.getenv("TALABAT_FAST") == "1" and links:
            size = 6
            cursor = (int(time.time() // 300) * size) % len(links)
            links = [
                links[(cursor + i) % len(links)]
                for i in range(min(size, len(links)))
            ]
            print("FAST_WINDOW:", len(links), "START:", cursor)

        print("MAIN_CATEGORIES:", len(catalog))
        print("NEW_CATEGORY_LINKS:", len(links) - before)
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
                    try:
                        old = float(item.get("originalPrice") or 0)
                        price = float(item.get("price") or 0)
                        stock = float(item.get("stockAmount") or 0)
                        if not (old > price > 0 and stock > 0):
                            continue
                        discount = round((1 - price / old) * 100, 2)
                        if not 40 <= discount <= 99:
                            continue
                        sku = str(item.get("sku") or "")
                        if not sku:
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

Path("reports/talabat_multi_branch.json").write_text(
    json.dumps(
        {"branches": summary, "offers": results},
        ensure_ascii=False, indent=2
    )
)

print("\nTOTAL_BRANCHES:", len(summary))
print("TOTAL_OFFERS_40_PLUS:", len(results))
print("REPORT: reports/talabat_multi_branch.json")
for x in sorted(results, key=lambda a: -a["discount"])[:12]:
    print("OFFER:", x["area"], x["discount"], "%", x["title"])
print("DELIVERY_ADDRESS_VERIFICATION: PENDING")
