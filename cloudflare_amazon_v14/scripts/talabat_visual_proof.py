import json, os, re
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, parse_qsl, urlencode, urlunsplit

import requests
from playwright.sync_api import sync_playwright

root = Path("cloudflare_amazon_v14")
x = json.loads(
    (root / "talabat_alerts/first_offer.json").read_text(encoding="utf-8")
)

price = float(x["price"])
price_text = f"{price:.2f}"
source = urlsplit(x["category_link"])
aid = parse_qs(source.query).get("aid", [""])[0]

sku_match = re.search(r"/s/([A-Za-z0-9]+)", x["product_link"])
slug_match = re.search(r"/product/([^/]+)/s/", x["product_link"])

if not sku_match or not slug_match or not aid:
    raise SystemExit("INVALID_PRODUCT_DATA")

if source.hostname != "www.talabat.com":
    raise SystemExit("INVALID_SOURCE")

sku = sku_match.group(1)
slug = slug_match.group(1)

product_url = (
    f"https://www.talabat.com/egypt/talabat-mart/"
    f"product/{slug}/s/{sku}?aid={aid}"
)

out = root / "talabat_alerts/talabat_live_proof.png"
out.parent.mkdir(parents=True, exist_ok=True)

name_pattern = re.compile(r"De\s+Cecco\s+Mezzi\s+Rigatoni", re.I)
price_pattern = re.compile(
    r"(?<!\d)" + re.escape(price_text).replace(r"\.", r"[.,]") + r"(?!\d)"
)

def capture_card(page):
    candidates = []

    for hit in page.get_by_text(name_pattern).all()[:10]:
        node = hit

        for _ in range(10):
            try:
                box = node.bounding_box(timeout=1300)
                content = node.inner_text(timeout=1300)

                if box and name_pattern.search(content) and price_pattern.search(content):
                    w, h = box["width"], box["height"]

                    if 190 <= w <= 1450 and 110 <= h <= 1550:
                        candidates.append((w * h, node))
            except Exception:
                pass

            node = node.locator("xpath=..")

    for _, node in sorted(candidates, key=lambda v: v[0]):
        try:
            node.screenshot(
                path=str(out),
                timeout=10000,
                animations="disabled"
            )
            return True
        except Exception:
            continue

    return False

urls = [("PRODUCT", product_url)]

for n in range(1, 6):
    query = [(k, v) for k, v in parse_qsl(source.query) if k != "page"]

    if n > 1:
        query.append(("page", str(n)))

    url = urlunsplit(source._replace(query=urlencode(query)))
    urls.append((f"CATEGORY_PAGE_{n}", url))

mode_used = None

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox"]
    )

    page = browser.new_page(
        viewport={"width": 1080, "height": 900},
        device_scale_factor=1.2
    )

    for mode, url in urls:
        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000
            )

            if response and response.status >= 400:
                print("PAGE_HTTP_ERROR:", mode, response.status)
                continue

            page.wait_for_timeout(1700)

            if capture_card(page):
                mode_used = mode
                break

            print("NO_MATCH:", mode)

        except Exception as e:
            print("PAGE_ERROR:", mode, type(e).__name__)

    browser.close()

if not mode_used or not out.exists() or out.stat().st_size < 4000:
    raise SystemExit("NO_REAL_SCREENSHOT: NOTHING_SENT")

print("SCREENSHOT_CAPTURED:", mode_used)
print("MATCHED_PAGE_PRICE:", price_text)

if os.getenv("TALABAT_PROOF_ONLY") == "1":
    print("TALABAT_SCREENSHOT_ONLY: READY")
    raise SystemExit(0)

token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

if not token:
    raise SystemExit("TELEGRAM_TOKEN_MISSING")

caption = (
    f"🛒 طلبات مارت | {x['area']}\n"
    f"📦 De Cecco Mezzi Rigatoni + Tomato\n"
    f"💰 {price_text} جنيه | 🔥 {x['discount']}%\n"
    f"📸 لقطة فعلية من صفحة طلبات\n"
    f"⚠️ السعر النهائي والتوصيل يحتاجان تأكيدًا في السلة\n"
    f"🔎 SKU: {sku}"
)

with out.open("rb") as photo:
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data={
            "chat_id": "-1004375874566",
            "caption": caption
        },
        files={
            "photo": ("talabat_proof.png", photo, "image/png")
        },
        timeout=35
    )

response.raise_for_status()

if not response.json().get("ok"):
    raise SystemExit("TELEGRAM_SEND_FAILED")

print("TALABAT_REAL_SCREENSHOT: SUCCESS")
