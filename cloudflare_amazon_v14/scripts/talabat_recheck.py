import json, time, re
import urllib.request, urllib.parse
from pathlib import Path
from collections import defaultdict

data = json.loads(
    Path("reports/talabat_multi_branch.json").read_text(encoding="utf-8")
)

groups = defaultdict(list)

for x in data["offers"]:
    path = urllib.parse.urlsplit(x["source"]).path.split("/")
    category = path[5] if len(path) > 5 else "unknown"
    groups[(x["branch_id"], category)].append(x)

shortlist = [
    max(v, key=lambda x: float(x["discount"]))
    for v in groups.values()
]

def fetch(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.hostname != "www.talabat.com":
        raise ValueError("INVALID_HOST")

    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-EG,en;q=0.9"
    })

    with urllib.request.urlopen(req, timeout=18) as r:
        final = urllib.parse.urlsplit(r.geturl())
        if final.scheme != "https" or final.hostname != "www.talabat.com":
            raise ValueError("BAD_REDIRECT")
        html = r.read(2500000).decode("utf-8", "replace")

    m = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.I | re.S
    )
    if not m:
        raise ValueError("NO_STATE")

    return json.loads(m.group(1))["props"]["pageProps"]["initialState"]

results = []
cache = {}

for x in shortlist:
    record = dict(x)
    record["recheck_status"] = "NOT_FOUND"
    record["delivery_verified"] = False
    record["checked_at"] = int(time.time())

    try:
        source = x["source"]

        if source not in cache:
            cache[source] = fetch(source)

        first = cache[source]
        store = first.get("groceryStore") or {}

        if str(store.get("branchId")) != str(x["branch_id"]):
            record["recheck_status"] = "BRANCH_MISMATCH"
            results.append(record)
            continue

        meta = first.get("itemsData") or {}
        total = min(max(int(meta.get("pageCount") or 1), 1), 100)

        for page in range(1, total + 1):
            if page == 1:
                state = first
            else:
                p = urllib.parse.urlsplit(source)
                q = urllib.parse.parse_qsl(p.query)
                q = [(k,v) for k,v in q if k != "page"]
                q.append(("page",str(page)))
                url = urllib.parse.urlunsplit(
                    p._replace(query=urllib.parse.urlencode(q))
                )
                state = fetch(url)
                if str((state.get("groceryStore") or {}).get("branchId")) != str(x["branch_id"]):
                    raise ValueError("BRANCH_MISMATCH")
                if str((state.get("itemsData") or {}).get("currentPage")) != str(page):
                    raise ValueError("PAGE_MISMATCH")

            items = (state.get("itemsData") or {}).get("items") or []

            item = next(
                (i for i in items if str(i.get("sku")) == str(x["sku"])),
                None
            )

            if item:
                price = float(item.get("price") or 0)
                old = float(item.get("originalPrice") or 0)
                stock = float(item.get("stockAmount") or 0)

                record["live_price"] = price
                record["live_stock"] = stock
                record["live_discount"] = round(
                    (1-price/old)*100,2
                ) if old > price > 0 else 0

                record["recheck_status"] = (
                    "PRICE_STOCK_CONFIRMED"
                    if price > 0 and stock > 0
                    and abs(price-float(x["price"])) < 0.01
                    else "CHANGED_OR_UNAVAILABLE"
                )
                break

            if page > 1:
                time.sleep(0.3)

    except Exception as e:
        record["recheck_status"] = "ERROR"
        record["error"] = type(e).__name__

    results.append(record)

out = Path("reports/talabat_rechecked.json")
out.write_text(
    json.dumps(results, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

from collections import Counter
print("SHORTLIST:", len(shortlist))
print("RESULTS:", dict(Counter(
    x["recheck_status"] for x in results
)))
print("DELIVERY_VERIFIED:", 0)
print("REPORT:", out)
