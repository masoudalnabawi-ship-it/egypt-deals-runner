#!/usr/bin/env python3
import argparse
import html
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import sync_playwright

WORKER = os.environ.get(
    "V14_WORKER_URL",
    "",
).rstrip("/")
ADMIN_KEY = os.environ.get("V14_GITHUB_PIPELINE_KEY", "").strip()
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
REVIEW_CHAT = os.environ.get("AMAZON_REVIEW_GROUP_ID", "").strip()

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)

HEADERS = {
    "Authorization": f"Bearer {ADMIN_KEY}",
    "Content-Type": "application/json",
    "User-Agent": "V14-GitHub-Playwright/1.0",
}

ARABIC_DIGITS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩٫٬",
    "0123456789.,",
)

PRICE_SELECTORS = [
    "#corePrice_feature_div .priceToPay .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen",
    "#corePrice_feature_div .a-price .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
    ".reinventPricePriceToPayMargin .a-offscreen",
    "span.a-price[data-a-color='price'] .a-offscreen",
    ".apexPriceToPay .a-offscreen",
    "#priceblock_ourprice",
    "#priceblock_dealprice",
    "#priceblock_saleprice",
    "#price_inside_buybox",
    "#newBuyBoxPrice",
    "#tp_price_block_total_price_ww .a-offscreen",
    "#corePrice_desktop .a-price .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-price-whole",
]

OLD_PRICE_SELECTORS = [
    "#corePrice_feature_div .a-price.a-text-price .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-price.a-text-price .a-offscreen",
    ".basisPrice .a-offscreen",
    "span.a-price.a-text-price .a-offscreen",
]

SAVING_SELECTORS = [
    "#corePrice_feature_div .savingsPercentage",
    "#corePriceDisplay_desktop_feature_div .savingsPercentage",
    ".savingsPercentage",
]

def die(message: str) -> None:
    print(f"❌ {message}", flush=True)
    raise SystemExit(2)

def api_post(path: str, payload: dict[str, Any], retries: int = 5) -> dict[str, Any]:
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(
                WORKER + path,
                headers=HEADERS,
                json=payload,
                timeout=35,
            )
            last = (r.status_code, r.text[:1000])
            if r.ok:
                data = r.json()
                if isinstance(data, dict):
                    return data
            if r.status_code in (401, 403):
                raise RuntimeError(f"auth_failed:{r.status_code}:{r.text[:300]}")
        except Exception as exc:
            last = repr(exc)
        if attempt < retries:
            time.sleep(min(8, attempt * 2))
    raise RuntimeError(f"api_post_failed:{path}:{last}")

def worker_policy() -> dict[str, Any]:
    try:
        r = requests.get(WORKER + "/", timeout=20)
        if r.ok:
            data = r.json()
            if isinstance(data, dict):
                return data.get("policy") or {}
    except Exception:
        pass
    return {}

def parse_number(text: str) -> float:
    if not text:
        return 0.0
    t = str(text).translate(ARABIC_DIGITS)
    t = t.replace("\u00a0", " ").replace("EGP", " ").replace("ج.م", " ")
    matches = re.findall(r"\d[\d,]*(?:\.\d+)?", t)
    if not matches:
        return 0.0
    raw = matches[0].replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    return value if value > 0 else 0.0

def parse_percent(text: str) -> float:
    if not text:
        return 0.0
    t = str(text).translate(ARABIC_DIGITS)
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", t)
    if not m:
        return 0.0
    try:
        return max(0.0, min(99.0, abs(float(m.group(1)))))
    except ValueError:
        return 0.0

def first_text(page, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                value = (loc.text_content(timeout=1200) or "").strip()
                if value:
                    return value
        except Exception:
            continue
    return ""

def first_price_text(page, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 8)):
                value = (loc.nth(i).text_content(timeout=1200) or "").strip()
                if parse_number(value) > 0:
                    return value
        except Exception:
            continue
    return ""


def first_attr(page, selector: str, attr: str) -> str:
    try:
        loc = page.locator(selector).first
        if loc.count() > 0:
            return (loc.get_attribute(attr, timeout=1200) or "").strip()
    except Exception:
        pass
    return ""

def page_blocked(page) -> bool:
    try:
        text = (page.locator("body").inner_text(timeout=2500) or "")[:6000].lower()
    except Exception:
        return True
    markers = [
        "robot check",
        "enter the characters you see below",
        "sorry! something went wrong",
        "أدخل الأحرف",
    ]
    return any(x in text for x in markers)

def asin_from_page(page, expected: str = "") -> str:
    expected = (expected or "").strip().upper()
    candidates = [
        first_attr(page, "input#ASIN", "value"),
        first_attr(page, "input[name='ASIN']", "value"),
        page.url,
        first_attr(page, "link[rel='canonical']", "href"),
    ]
    for value in candidates:
        if not value:
            continue
        m = re.search(r"(?:/dp/|/gp/product/)?([A-Z0-9]{10})(?:[/?&#]|$)", value.upper())
        if m:
            return m.group(1)
        if re.fullmatch(r"[A-Z0-9]{10}", value.upper()):
            return value.upper()
    return ""

def coupon_percent(page) -> float:
    selectors = [
        "#couponTextpctch",
        "#couponText",
        "#couponBadge",
    ]
    blocked = (
        "bank", "credit card", "debit card",
        "visa", "mastercard", "cashback",
        "بنك", "بنكي", "بطاقة ائتمان",
        "بطاقة خصم", "كاش باك", "تقسيط",
        "prime", "برايم",
    )
    best = 0.0
    for selector in selectors:
        try:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 4)):
                text = (loc.nth(i).inner_text(timeout=1000) or "").strip()
                low = text.lower()
                if any(word in low for word in blocked):
                    continue
                if not any(word in low for word in ("coupon", "كوبون", "قسيمة", "خصم")):
                    continue
                matches = re.findall(
                    r"(\\d{1,2}(?:\\.\\d+)?)\\s*%",
                    text.translate(ARABIC_DIGITS),
                )
                if len(matches) == 1:
                    value = float(matches[0])
                    if 0 < value <= 60:
                        best = max(best, value)
        except Exception:
            continue
    return best

def inspect_amazon(page, url: str, expected_asin: str = "") -> dict[str, Any]:
    response = page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.wait_for_timeout(1600)

    status = response.status if response else 0
    if status >= 400:
        raise RuntimeError(f"http_{status}")
    if page_blocked(page):
        raise RuntimeError("amazon_blocked")

    current_text = first_price_text(page, PRICE_SELECTORS)
    if not parse_number(current_text):
        for _ in range(3):
            page.wait_for_timeout(1500)
            current_text = first_price_text(page, PRICE_SELECTORS)
            if parse_number(current_text):
                break
    old_text = first_text(page, OLD_PRICE_SELECTORS)
    saving_text = first_text(page, SAVING_SELECTORS)

    if not parse_number(current_text):
        try:
            price_counts = {
                selector: page.locator(selector).count()
                for selector in PRICE_SELECTORS
            }
            size_count = page.locator(
                "#native_dropdown_selected_size_name, "
                "#variation_size_name, "
                "#inline-twister-expander-content-size_name"
            ).count()
            print(
                "AMAZON_PRICE_DIAGNOSTIC",
                {
                    "url": page.url,
                    "title": page.title()[:120],
                    "price_counts": price_counts,
                    "size_selectors": size_count,
                },
                flush=True,
            )
        except Exception as exc:
            print("AMAZON_DIAGNOSTIC_ERROR", repr(exc), flush=True)

    current = parse_number(current_text)
    old = parse_number(old_text)
    savings = parse_percent(saving_text)
    coupon = coupon_percent(page)

    canonical = first_attr(page, "link[rel='canonical']", "href") or page.url
    page_asin = asin_from_page(page, expected_asin)
    if expected_asin and page_asin != expected_asin.strip().upper():
        raise RuntimeError(f"asin_mismatch:expected={expected_asin}:actual={page_asin}")
    title = first_text(page, ["#productTitle", "h1#title", "h1"])
    image_url = (
        first_attr(page, "#landingImage", "src")
        or first_attr(page, "#imgBlkFront", "src")
        or first_attr(page, "img[data-old-hires]", "data-old-hires")
    )

    if not current:
        raise RuntimeError("no_live_price")

    return {
        "current_price": round(current, 2),
        "old_price": round(old, 2) if old > current else 0,
        "savings_percent": round(savings, 2),
        "coupon_percent": round(coupon, 2),
        "page_asin": page_asin,
        "canonical_url": canonical[:1000],
        "title": title[:300],
        "image_url": image_url[:1400],
    }

def effective_discount(obs: dict[str, Any]) -> float:
    current = float(obs.get("current_price") or 0)
    old = float(obs.get("old_price") or 0)
    savings = float(obs.get("savings_percent") or 0)
    coupon = float(obs.get("coupon_percent") or 0)

    old_discount = 0.0
    if old > current > 0:
        old_discount = ((old - current) / old) * 100.0

    base = old_discount  # Only a verified old/current price pair establishes the base discount
    combined = 100.0 - ((100.0 - base) * (100.0 - coupon) / 100.0)
    return round(max(0.0, min(99.0, combined)), 2)

def verify_one(page) -> bool:
    claim = api_post(
        "/admin/playwright-verify/claim",
        {"worker_id": f"gha-v14-{int(time.time())}"},
    )
    job = claim.get("job")
    if not job:
        return False

    key = str(job.get("deal_key") or "")
    try:
        obs = inspect_amazon(
            page,
            str(job.get("url") or ""),
            str(job.get("external_id") or ""),
        )
        payload = {
            "deal_key": key,
            "status": "verified",
            **obs,
        }
        result = api_post(
            "/admin/playwright-verify/complete",
            payload,
            retries=10,
        )
        print(
            "✅ VERIFIED",
            key[:12],
            "lane=",
            result.get("lane"),
            "discount=",
            result.get("discount"),
            "strike=",
            result.get("strike_score"),
            flush=True,
        )
        return True
    except Exception as exc:
        reason = str(exc)[:300]
        print("⚠️ VERIFY FAIL", key[:12], reason, flush=True)
        try:
            api_post(
                "/admin/playwright-verify/complete",
                {
                    "deal_key": key,
                    "status": "failed",
                    "reason": reason,
                },
                retries=10,
            )
        except Exception as complete_exc:
            print("❌ VERIFY COMPLETE FAIL", repr(complete_exc), flush=True)
        return True

def build_caption(job: dict[str, Any], live_discount: float) -> str:
    title = html.escape(str(job.get("title") or "Amazon Deal")[:180])
    current = float(job.get("current_price") or 0)
    old = float(job.get("old_price") or 0)
    confidence = float(job.get("confidence") or 0) * 100
    score = float(job.get("score") or 0)
    lane = str(job.get("lane") or "normal")
    category = html.escape(str(job.get("category") or "")[:70])

    lines = [
        "🚨 <b>V14 Amazon Review</b>" if lane == "ultra" else "🔥 <b>V14 Amazon Review</b>",
        "",
        f"🛒 <b>{title}</b>",
        "",
        f"💰 <b>السعر الآن:</b> {current:,.2f} ج.م",
    ]
    if old > current > 0:
        lines.append(f"🏷 <b>السعر السابق:</b> <s>{old:,.2f}</s> ج.م")
    lines.extend([
        f"📉 <b>الخصم الحي:</b> {live_discount:.1f}%",
        f"🧠 <b>التقييم:</b> {score:.1f}/100",
        f"🛡 <b>الثقة:</b> {confidence:.0f}%",
    ])
    if lane == "ultra" and live_discount >= 75:
        lines.append("🚀 <b>الأولوية:</b> Tier-1")
    if category:
        lines.append(f"📂 <b>القسم:</b> {category}")
    return "\n".join(lines)[:1000]

NORMAL_REVIEW_CHAT = os.environ.get("AMAZON_NORMAL_REVIEW_CHAT_ID", "").strip()


def capture_product_screenshot(page, path: Path) -> None:
    top = page.evaluate("""() => { const e = document.querySelector("#dp-container") || document.querySelector("#ppd"); return e ? Math.max(0, e.getBoundingClientRect().top + scrollY) : 0; }""")
    bottom = page.evaluate("""() => { const selectors = ["#detailBullets_feature_div", "#productDetails_feature_div", "#prodDetails", "#productDetails_db_sections", "#detailBulletsWrapper_feature_div"]; const positions = selectors.map(s => document.querySelector(s)).filter(Boolean).map(e => e.getBoundingClientRect().top + scrollY).filter(y => y > 350); return positions.length ? Math.min(...positions) : 1050; }""")
    height = max(500, min(900, int(bottom - top)))
    page.screenshot(path=str(path), type="jpeg", quality=85, clip={"x": 0, "y": int(top), "width": 1440, "height": height})


def send_review_photo(job: dict[str, Any], photo: Path, live_discount: float) -> int:
    if not (REVIEW_CHAT if str(job.get("lane") or "normal").lower() == "ultra" else NORMAL_REVIEW_CHAT):
        raise RuntimeError("telegram_review_chat_missing")
    short = str(job.get("deal_key") or "")[:16]
    url = str(job.get("url") or "")
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🚀 نشر عاجل", "callback_data": f"v14:u:{short}"},
                {"text": "✅ نشر عادي", "callback_data": f"v14:p:{short}"},
            ],
            [
                {"text": "🔗 فتح المنتج", "url": url},
                {"text": "❌ رفض", "callback_data": f"v14:r:{short}"},
            ],
        ]
    }

    with photo.open("rb") as fh:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={
                "chat_id": (REVIEW_CHAT if str(job.get("lane") or "normal").lower() == "ultra" else NORMAL_REVIEW_CHAT),
                "caption": build_caption(job, live_discount),
                "parse_mode": "HTML",
                "reply_markup": json.dumps(keyboard, ensure_ascii=False),
            },
            files={"photo": ("amazon-v14.jpg", fh, "image/jpeg")},
            timeout=45,
        )
    if not r.ok:
        raise RuntimeError(f"telegram_http_{r.status_code}:{r.text[:400]}")
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"telegram_not_ok:{str(data)[:400]}")
    return int((data.get("result") or {}).get("message_id") or 0)

def deliver_one(page, lane: str, ultra_min: float) -> bool:
    claim = api_post(
        "/admin/screenshot/claim",
        {
            "worker_id": f"gha-shot-{int(time.time())}",
            "lane": lane,
        },
    )
    job = claim.get("job")
    if not job:
        return False

    key = str(job.get("deal_key") or "")
    try:
        obs = inspect_amazon(
            page,
            str(job.get("url") or ""),
            str(job.get("external_id") or ""),
        )
        live_discount = effective_discount(obs)

        if lane == "normal" and not (10 <= live_discount < ultra_min):
            api_post("/admin/screenshot/complete", {"deal_key": key, "status": "invalid_normal", "reason": f"live_discount_{live_discount}_outside_normal_range", "live_discount": live_discount, "proof": obs}, retries=10)
            print("NORMAL DISCOUNT OUT OF RANGE", key[:12], live_discount, flush=True)
            return True

        if lane == "ultra" and live_discount < ultra_min:
            api_post(
                "/admin/screenshot/complete",
                {
                    "deal_key": key,
                    "status": "invalid_ultra",
                    "reason": f"live_discount_{live_discount}_below_{ultra_min}",
                    "live_discount": live_discount,
                    "proof": obs,
                },
                retries=10,
            )
            print("🛑 ULTRA EXPIRED", key[:12], live_discount, flush=True)
            return True

        with tempfile.TemporaryDirectory(prefix="v14-shot-") as td:
            shot = Path(td) / "deal.jpg"
            capture_product_screenshot(page, shot)
            live_job = {**job, "current_price": obs["current_price"], "old_price": obs["old_price"]}
            message_id = send_review_photo(live_job, shot, live_discount)

        proof = {
            **obs,
            "telegram_message_id": message_id,
            "review_chat": (REVIEW_CHAT if lane == "ultra" else NORMAL_REVIEW_CHAT),
            "via": "github_playwright_v14",
        }
        api_post(
            "/admin/screenshot/complete",
            {
                "deal_key": key,
                "status": "sent",
                "live_discount": live_discount,
                "proof": proof,
            },
            retries=10,
        )
        print(
            "📤 REVIEW SENT",
            key[:12],
            "lane=",
            lane,
            "live_discount=",
            live_discount,
            flush=True,
        )
        return True
    except Exception as exc:
        reason = str(exc)[:300]
        print("⚠️ DELIVERY FAIL", key[:12], reason, flush=True)
        try:
            api_post(
                "/admin/screenshot/complete",
                {
                    "deal_key": key,
                    "status": "retry",
                    "reason": reason,
                    "live_discount": 0,
                    "proof": {"via": "github_playwright_v14"},
                },
                retries=10,
            )
        except Exception as complete_exc:
            print("❌ DELIVERY COMPLETE FAIL", repr(complete_exc), flush=True)
        return True

def screenshot_test() -> int:
    import json
    target = "https://www.amazon.eg/dp/B0DK4Z4GPJ"
    output = Path("/tmp/amazon-v14-screenshot-test")
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium")
        options = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        if chrome:
            options["executable_path"] = chrome
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(locale="ar-EG", timezone_id="Africa/Cairo", user_agent=UA, viewport={"width": 1440, "height": 1800}, device_scale_factor=1)
        page = context.new_page()
        try:
            observation = inspect_amazon(page, target, "B0DK4Z4GPJ")
            observation["effective_discount"] = effective_discount(observation)
            capture_product_screenshot(page, output / "amazon-product.jpg")
            (output / "observation.json").write_text(json.dumps(observation, ensure_ascii=False, indent=2), encoding="utf-8")
            print("SCREENSHOT_TEST_OK", output, flush=True)
        finally:
            browser.close()
    return 0


def send_test_message() -> int:
    if not BOT_TOKEN or not NORMAL_REVIEW_CHAT:
        die("normal_review_test_credentials_missing")
    image = Path("/tmp/amazon-v14-screenshot-test/amazon-product.jpg")
    if not image.is_file():
        die("test_screenshot_missing")
    job = {"lane": "normal", "title": "اختبار V14 - أديداس باريدا شوز", "current_price": 2309.0, "old_price": 5455.0, "confidence": 0, "score": 0, "category": "أحذية", "url": "https://www.amazon.eg/dp/B0DK4Z4GPJ", "deal_key": "test-b0dk4z4gpj"}
    caption = "🧪 <b>رسالة اختبار فقط - غير مخصصة للنشر</b>\n\n🛒 <b>أديداس باريدا شوز</b>\n\n💰 <b>السعر الآن:</b> 2,309.00 ج.م\n🏷 <b>السعر السابق:</b> <s>5,455.00</s> ج.م\n📉 <b>الخصم:</b> 57.67%"
    with image.open("rb") as fh:
        response = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", data={"chat_id": NORMAL_REVIEW_CHAT, "caption": caption, "parse_mode": "HTML", "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🔗 فتح المنتج", "url": job["url"]}]]}, ensure_ascii=False)}, files={"photo": ("amazon-v14-test.jpg", fh, "image/jpeg")}, timeout=45)
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("telegram_test_rejected")
    print("ONE_NORMAL_REVIEW_TEST_SENT", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot-test", action="store_true")
    parser.add_argument("--send-test", action="store_true")
    parser.add_argument("--max-verify", type=int, default=4)
    parser.add_argument("--max-deliver", type=int, default=8)
    args = parser.parse_args()
    if args.screenshot_test:
        return screenshot_test()
    if args.send_test:
        return send_test_message()

    if not ADMIN_KEY:
        die("V14_GITHUB_PIPELINE_KEY missing")
    if not BOT_TOKEN:
        die("TELEGRAM_BOT_TOKEN missing")
    if not REVIEW_CHAT:
        die("AMAZON_REVIEW_GROUP_ID missing")

    policy = worker_policy()
    ultra_min = float(policy.get("amazon_ultra_min") or policy.get("ultra_min_discount") or 65)

    print(
        f"V14_PIPELINE_START ultra_min={ultra_min} "
        f"verify_limit={args.max_verify} delivery_limit={args.max_deliver}",
        flush=True,
    )

    worked = 0

    with sync_playwright() as p:
        chrome_path = (
            shutil.which("google-chrome")
            or shutil.which("google-chrome-stable")
            or shutil.which("chromium")
        )

        launch_args = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        }

        if chrome_path:
            launch_args["executable_path"] = chrome_path
            print(
                f"✅ USING_SYSTEM_CHROME={chrome_path}",
                flush=True,
            )
        else:
            print(
                "⚠️ USING_PLAYWRIGHT_BUNDLED_CHROMIUM",
                flush=True,
            )

        browser = p.chromium.launch(
            **launch_args
        )
        context = browser.new_context(
            locale="ar-EG",
            timezone_id="Africa/Cairo",
            user_agent=UA,
            viewport={"width": 1440, "height": 1800},
            device_scale_factor=1,
            extra_http_headers={
                "Accept-Language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )

        for _ in range(max(0, args.max_verify)):
            page = context.new_page()
            try:
                if not verify_one(page):
                    break
                worked += 1
            finally:
                page.close()

        remaining = max(0, args.max_deliver)
        while remaining > 0:
            progressed = False
            for lane in ("ultra", "normal"):
                if remaining <= 0:
                    break
                page = context.new_page()
                try:
                    if deliver_one(page, lane, ultra_min):
                        worked += 1
                        remaining -= 1
                        progressed = True
                finally:
                    page.close()
            if not progressed:
                break

        context.close()
        browser.close()

    print(f"V14_PIPELINE_DONE worked={worked}", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
