from __future__ import annotations

import asyncio
import html
import json
import os
import re
import signal
import time
import uuid
from urllib.parse import quote

import httpx
from playwright.async_api import async_playwright


API_BASE = os.getenv(
    "V14_WORKER_URL",
    "https://egypt-deals-v14.masoudalnabawi.workers.dev",
).rstrip("/")

ADMIN_KEY = os.getenv(
    "V14_ADMIN_KEY",
    "",
).strip()

BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "",
).strip()

NORMAL_CHAT = (
    os.getenv(
        "AMAZON_NORMAL_REVIEW_CHAT_ID",
        "",
    ).strip()
    or os.getenv(
        "REVIEW_CHAT_ID",
        "",
    ).strip()
)

ULTRA_CHAT = os.getenv(
    "AMAZON_REVIEW_GROUP_ID",
    "",
).strip()

RUN_SECONDS = int(
    os.getenv(
        "V14_SCREENSHOT_WORKER_SECONDS",
        "13200",
    )
)

MIN_GAP = float(
    os.getenv(
        "V14_SCREENSHOT_MIN_GAP",
        "1.5",
    )
)

NOON_SCAN_SECONDS = max(
    180,
    int(
        os.getenv(
            "V14_NOON_SCAN_SECONDS",
            "240",
        )
    ),
)

NOON_MAX_PRODUCTS = max(
    4,
    min(
        20,
        int(
            os.getenv(
                "V14_NOON_MAX_PRODUCTS",
                "12",
            )
        ),
    ),
)

# One rendered Noon search every few minutes.
# Full category rotation completes without burst traffic.
NOON_SURFACES = [
    ("mobiles", "mobiles", "mobile phones"),
    ("laptops", "computers", "laptops"),
    ("appliances", "appliances", "home appliances"),
    ("tablets", "computers", "tablets"),
    ("tvs", "electronics", "televisions"),
    ("audio", "electronics", "headphones earbuds speakers"),
    ("gaming", "electronics", "gaming"),
    ("smartwatches", "electronics", "smart watches"),
    ("mobile_accessories", "mobiles", "mobile accessories"),
    ("computer_accessories", "computers", "computer accessories"),
    ("kitchen", "kitchen", "kitchen appliances"),
    ("beauty", "beauty", "beauty"),
    ("personal_care", "beauty", "personal care"),
    ("fashion", "fashion", "fashion"),
    ("shoes", "fashion", "shoes"),
    ("sports", "sports", "sports fitness"),
    ("toys", "toys", "toys"),
    ("baby", "baby", "baby"),
    ("grocery", "grocery", "grocery"),
    ("automotive", "automotive", "car accessories"),
]



def required() -> None:
    missing = []

    for name, value in (
        ("V14_ADMIN_KEY", ADMIN_KEY),
        ("TELEGRAM_BOT_TOKEN", BOT_TOKEN),
        ("AMAZON_NORMAL_REVIEW_CHAT_ID", NORMAL_CHAT),
        ("AMAZON_REVIEW_GROUP_ID", ULTRA_CHAT),
    ):
        if not value:
            missing.append(name)

    if missing:
        raise RuntimeError(
            "missing:" + ",".join(missing)
        )

    if NORMAL_CHAT == ULTRA_CHAT:
        raise RuntimeError(
            "normal_and_ultra_chat_ids_are_identical"
        )


def caption(job: dict) -> str:
    lane = str(job.get("lane") or "normal")

    icon = "🚨" if lane == "ultra" else "🔥"
    lane_ar = "ألترا" if lane == "ultra" else "مراجعة"

    title = html.escape(
        str(
            job.get("title")
            or "منتج بدون اسم"
        )[:190]
    )

    current = float(
        job.get("current_price") or 0
    )

    old = float(
        job.get("old_price") or 0
    )

    real = float(
        job.get("real_discount") or 0
    )

    score = float(
        job.get("score") or 0
    )

    confidence = float(
        job.get("confidence") or 0
    )

    effective = float(
        job.get("effective_price")
        or current
    )

    external = html.escape(
        str(job.get("external_id") or "")
    )

    category = html.escape(
        str(job.get("category") or "")
    )[:70]

    lines = [
        f"{icon} <b>V14 {lane_ar} • Amazon Egypt</b>",
        "",
        f"🛒 <b>{title}</b>",
        "",
        f"💰 <b>السعر الآن:</b> {current:,.2f} ج.م",
    ]

    if old > current:
        lines.append(
            f"🏷 <b>السعر السابق:</b> "
            f"<s>{old:,.2f}</s> ج.م"
        )

    if (
        effective > 0
        and effective < current * 0.999
    ):
        implied = (
            ((current - effective) / current) * 100
            if current
            else 0
        )

        if 0 < implied <= 60:
            lines.append(
                f"🎟 <b>بعد الكوبون/العرض:</b> "
                f"{effective:,.2f} ج.م"
            )

    lines.extend([
        f"📉 <b>الخصم الحقيقي:</b> {real:.1f}%",
        f"🧠 <b>التقييم:</b> {score:.1f}/100",
        f"🛡 <b>الثقة:</b> {confidence * 100:.0f}%",
    ])

    if external:
        lines.append(
            f"🆔 <b>ASIN:</b> <code>{external}</code>"
        )

    if category:
        lines.append(
            f"📂 <b>القسم:</b> {category}"
        )

    return "\n".join(lines)


def keyboard(job: dict) -> dict:
    short = str(
        job.get("deal_key") or ""
    )[:16]

    return {
        "inline_keyboard": [
            [
                {
                    "text": "🚀 نشر عاجل",
                    "callback_data": f"v14:u:{short}",
                },
                {
                    "text": "✅ نشر عادي",
                    "callback_data": f"v14:p:{short}",
                },
            ],
            [
                {
                    "text": "🔗 فتح المنتج",
                    "url": str(job["url"]),
                },
                {
                    "text": "❌ رفض",
                    "callback_data": f"v14:r:{short}",
                },
            ],
        ]
    }


async def api_post(
    client: httpx.AsyncClient,
    path: str,
    payload: dict,
) -> dict:
    response = await client.post(
        API_BASE + path,
        headers={
            "authorization":
                f"Bearer {ADMIN_KEY}",
        },
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(
            f"api_failed:{path}:{data}"
        )

    return data


async def claim(
    client: httpx.AsyncClient,
    lane: str,
    worker_id: str,
) -> dict | None:
    data = await api_post(
        client,
        "/admin/screenshot/claim",
        {
            "lane": lane,
            "worker_id": worker_id,
        },
    )

    return data.get("job")


async def complete(
    client: httpx.AsyncClient,
    job: dict,
    status: str,
    reason: str = "",
    proof: dict | None = None,
    live_discount: float = 0.0,
) -> None:
    payload = {
        "deal_key":
            job["deal_key"],
        "status":
            status,
        "reason":
            reason[:350],
        "live_discount":
            round(
                float(live_discount or 0),
                2,
            ),
    }

    if proof:
        payload["proof"] = proof

    await api_post(
        client,
        "/admin/screenshot/complete",
        payload,
    )



async def claim_verify(
    client: httpx.AsyncClient,
    worker_id: str,
) -> dict | None:
    data = await api_post(
        client,
        "/admin/playwright-verify/claim",
        {"worker_id": worker_id},
    )
    return data.get("job")


async def complete_verify(
    client: httpx.AsyncClient,
    job: dict,
    status: str,
    proof: dict | None = None,
    reason: str = "",
) -> dict:
    payload = {
        "deal_key": job["deal_key"],
        "status": status,
        "reason": reason[:350],
    }

    if proof:
        payload.update(proof)

    return await api_post(
        client,
        "/admin/playwright-verify/complete",
        payload,
    )


def _num(value: str) -> float:
    text = (
        str(value or "")
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
        .translate(
            str.maketrans(
                "٠١٢٣٤٥٦٧٨٩٫٬",
                "0123456789.,",
            )
        )
    )

    m = re.search(
        r"([0-9][0-9,]*(?:\.[0-9]+)?)",
        text,
    )

    if not m:
        return 0.0

    try:
        return float(
            m.group(1).replace(",", "")
        )
    except Exception:
        return 0.0


def _pct(value: str) -> float:
    text = (
        str(value or "")
        .translate(
            str.maketrans(
                "٠١٢٣٤٥٦٧٨٩٫٬",
                "0123456789.,",
            )
        )
    )

    m = re.search(
        r"-?\s*(\d+(?:\.\d+)?)\s*%",
        text,
    )

    if not m:
        return 0.0

    value = float(m.group(1))
    return value if 0 < value <= 99 else 0.0


def _coupon_equivalent(
    text: str,
    current: float,
) -> float:
    raw = (
        str(text or "")
        .translate(
            str.maketrans(
                "٠١٢٣٤٥٦٧٨٩٫٬",
                "0123456789.,",
            )
        )
    )

    best = _pct(raw)

    if not current or current <= 0:
        return best

    low = raw.lower()

    coupon_words = (
        "coupon",
        "voucher",
        "كوبون",
        "قسيمة",
        "خصم فوري",
    )

    bank_words = (
        "bank",
        "credit card",
        "debit card",
        "visa",
        "mastercard",
        "master card",
        "installment",
        "instalment",
        "nbe",
        "enbd",
        "cib",
        "qnb",
        "بنك",
        "بطاقة",
        "كارت",
        "تقسيط",
        "أقساط",
        "اقساط",
    )

    patterns = (
        r"(?:EGP|جنيه(?:\s+مصري)?|ج\.?\s*م\.?)\s*"
        r"([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*"
        r"(?:EGP|جنيه(?:\s+مصري)?|ج\.?\s*م\.?)",
    )

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            raw,
            re.IGNORECASE,
        ):
            start = max(
                0,
                match.start() - 100,
            )

            end = min(
                len(raw),
                match.end() + 100,
            )

            context = (
                raw[start:end]
                .lower()
            )

            if not any(
                word in context
                for word in coupon_words
            ):
                continue

            if any(
                word in context
                for word in bank_words
            ):
                continue

            try:
                amount = float(
                    match.group(1)
                    .replace(",", "")
                )
            except Exception:
                continue

            if (
                amount <= 0
                or amount >= current * 0.95
            ):
                continue

            pct = (
                amount
                / current
                * 100
            )

            if 0 < pct <= 80:
                best = max(
                    best,
                    pct,
                )

    return round(
        min(99.0, best),
        2,
    )


async def verify_rendered(
    context,
    job: dict,
) -> dict:
    page = await context.new_page()

    try:
        response = await page.goto(
            str(job["url"]),
            wait_until="domcontentloaded",
            timeout=20000,
        )

        if (
            response is not None
            and response.status >= 400
        ):
            raise RuntimeError(
                f"amazon_http_{response.status}"
            )

        await page.wait_for_timeout(1800)

        body = await page.locator(
            "body"
        ).inner_text(timeout=7000)

        low = body.lower()

        if any(
            x in low
            for x in (
                "enter the characters you see below",
                "robot check",
                "captcha",
                "access denied",
                "unusual traffic",
            )
        ):
            raise RuntimeError(
                "amazon_page_protected"
            )

        raw = await page.evaluate(
            """
            () => {
              const isRenderedPriceEvidence = (el) => {
                /*
                 * Amazon frequently keeps stale/alternate prices
                 * in the DOM. An .a-offscreen node is legitimate
                 * only when its visible price container is rendered.
                 */
                const anchor =
                  el.closest(
                    '.a-price, .basisPrice, .priceToPay, ' +
                    '#price_inside_buybox, #newBuyBoxPrice, ' +
                    '#coupon_feature_div, #couponFeature'
                  ) || el;

                if (
                  anchor.hidden ||
                  anchor.getAttribute('aria-hidden') === 'true'
                ) {
                  return false;
                }

                const style =
                  window.getComputedStyle(anchor);

                if (
                  style.display === 'none' ||
                  style.visibility === 'hidden' ||
                  Number(style.opacity || 1) === 0
                ) {
                  return false;
                }

                const rect =
                  anchor.getBoundingClientRect();

                return (
                  rect.width > 0 &&
                  rect.height > 0
                );
              };

              const texts = (selectors) => {
                const out = [];

                for (const selector of selectors) {
                  for (
                    const el
                    of document.querySelectorAll(selector)
                  ) {
                    if (!isRenderedPriceEvidence(el)) {
                      continue;
                    }

                    const text =
                      (el.textContent || '').trim();

                    if (text) out.push(text);
                  }
                }

                return out;
              };

              const image = document.querySelector('#landingImage');

              return {
                title:
                  (document.querySelector('#productTitle')?.textContent || '')
                  .trim(),

                current: texts([
                  '#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen',
                  '#corePrice_feature_div .priceToPay .a-offscreen',
                  '.apexPriceToPay .a-offscreen',
                  '#buybox .priceToPay .a-offscreen',
                  '#price_inside_buybox',
                  '#newBuyBoxPrice',
                  '#corePriceDisplay_desktop_feature_div .a-price .a-offscreen',
                  '#corePrice_feature_div .a-price .a-offscreen',
                  '#ppd .priceToPay .a-offscreen',
                  '#ppd [data-a-color="price"] .a-offscreen',
                  '#ppd .a-price .a-offscreen',
                  '#tmmSwatches .a-color-price',
                  '.swatchElement .a-color-price'
                ]),

                old: texts([
                  '#corePriceDisplay_desktop_feature_div .basisPrice .a-offscreen',
                  '#corePrice_feature_div .basisPrice .a-offscreen',
                  '#corePriceDisplay_desktop_feature_div .a-text-price .a-offscreen',
                  '#corePrice_feature_div .a-text-price .a-offscreen'
                ]),

                savings: texts([
                  '#corePriceDisplay_desktop_feature_div .savingsPercentage',
                  '#corePrice_feature_div .savingsPercentage',
                  '.savingsPercentage'
                ]),

                coupon: texts([
                  '#couponText',
                  '#couponFeature',
                  '#coupon_feature_div'
                ]),

                image_url:
                  image?.getAttribute('data-old-hires')
                  || image?.getAttribute('src')
                  || ''
              };
            }
            """
        )

        price_candidates = []

        for value in raw.get("current", []):
            n = _num(value)

            if n > 0:
                price_candidates.append(n)

        # Remove duplicates while preserving DOM priority.
        unique_candidates = []

        for n in price_candidates:
            if not any(
                abs(n - x) <= 0.01
                for x in unique_candidates
            ):
                unique_candidates.append(n)

        if not unique_candidates:
            raise RuntimeError(
                "amazon_live_current_price_missing"
            )

        discovered_current = float(
            job.get("current_price") or 0
        )

        current = unique_candidates[0]
        discovery_current_match = False

        if discovered_current > 0:
            closest = min(
                unique_candidates,
                key=lambda x:
                    abs(x - discovered_current)
            )

            gap = (
                abs(
                    closest - discovered_current
                )
                / discovered_current
            )

            if gap <= 0.015:
                current = closest
                discovery_current_match = True

        old = 0.0

        for value in raw.get("old", []):
            n = _num(value)

            if n > current:
                old = max(old, n)

        savings = 0.0

        for value in raw.get("savings", []):
            savings = max(
                savings,
                _pct(value),
            )

        coupon = 0.0

        for value in raw.get("coupon", []):
            lower = str(value).lower()

            if any(
                x in lower
                for x in (
                    "bank",
                    "credit card",
                    "debit card",
                    "installment",
                    "instalment",
                    "بنك",
                    "تقسيط",
                    "أقساط",
                    "اقساط",
                )
            ):
                continue

            if any(
                x in lower
                for x in (
                    "coupon",
                    "voucher",
                    "كوبون",
                    "قسيمة",
                )
            ):
                coupon = max(
                    coupon,
                    _coupon_equivalent(
                        value,
                        current,
                    ),
                )

        return {
            "title":
                str(raw.get("title") or "").strip(),

            "current_price":
                round(current, 2),

            "discovery_current_match":
                discovery_current_match,

            "price_candidates":
                [
                    round(x, 2)
                    for x in unique_candidates[:12]
                ],

            "old_price":
                round(old, 2)
                if old > current
                else 0,

            "savings_percent":
                round(savings, 2),

            "coupon_percent":
                round(coupon, 2),

            "image_url":
                str(raw.get("image_url") or "").strip(),
        }

    finally:
        await page.close()


def live_effective_discount(
    proof: dict,
) -> float:
    current = float(
        proof.get("current_price") or 0
    )

    old = float(
        proof.get("old_price") or 0
    )

    savings = float(
        proof.get("savings_percent") or 0
    )

    coupon = float(
        proof.get("coupon_percent") or 0
    )

    base = 0.0

    if old > current > 0:
        base = (
            (old - current)
            / old
            * 100
        )

    if 0 < savings <= 99:
        base = max(
            base,
            savings,
        )

    if 0 < coupon <= 99:
        base = (
            100
            * (
                1
                - (1 - base / 100)
                * (1 - coupon / 100)
            )
        )

    return round(
        max(
            0.0,
            min(99.0, base),
        ),
        2,
    )


async def capture(
    context,
    job: dict,
) -> bytes:
    page = await context.new_page()

    try:
        response = await page.goto(
            str(job["url"]),
            wait_until="domcontentloaded",
            timeout=18000,
        )

        if (
            response is not None
            and response.status >= 400
        ):
            raise RuntimeError(
                f"amazon_http_{response.status}"
            )

        await page.wait_for_timeout(1700)

        body = await page.locator(
            "body"
        ).inner_text(
            timeout=6000
        )

        low = body.lower()

        protected = (
            "enter the characters you see below",
            "robot check",
            "captcha",
            "access denied",
            "unusual traffic",
        )

        if any(
            marker in low
            for marker in protected
        ):
            raise RuntimeError(
                "amazon_page_protected"
            )

        # A genuine product page must have a visible product title.
        title = page.locator(
            "#productTitle"
        ).first

        if (
            await title.count() == 0
            or not await title.is_visible()
        ):
            raise RuntimeError(
                "amazon_product_title_missing"
            )

        # Same clean page style that V13 used.
        hide = [
            "header",
            "#navbar",
            "#nav-belt",
            "#nav-main",
            "#nav-subnav",
            "#nav-progressive-subnav",
            ".navLeftFooter",
            "#rhf",
            "footer",
            ".cookie-banner",
            "[class*='Cookie']",
        ]

        for selector in hide:
            try:
                await page.locator(
                    selector
                ).evaluate_all(
                    "(els) => "
                    "els.forEach("
                    "e => e.style.display='none'"
                    ")"
                )
            except Exception:
                pass

        anchors = [
            "#ppd",
            "#title_feature_div",
            "#centerCol",
            "#dp-container",
        ]

        anchored = False

        for selector in anchors:
            try:
                loc = page.locator(
                    selector
                ).first

                if (
                    await loc.count()
                    and await loc.is_visible()
                ):
                    await loc.evaluate(
                        """
                        el => {
                          const y =
                            el.getBoundingClientRect().top
                            + window.scrollY;

                          window.scrollTo(
                            0,
                            Math.max(0, y - 8)
                          );
                        }
                        """
                    )

                    anchored = True
                    break

            except Exception:
                continue

        if not anchored:
            await page.evaluate(
                "window.scrollTo(0,0)"
            )

        await page.wait_for_timeout(500)

        return await page.screenshot(
            type="png",
            full_page=False,
            animations="disabled",
        )

    finally:
        await page.close()


async def send_telegram(
    client: httpx.AsyncClient,
    job: dict,
    screenshot: bytes,
) -> None:
    lane = str(
        job.get("lane") or "normal"
    )

    if lane == "ultra":
        if float(
            job.get("real_discount") or 0
        ) < 65:
            raise RuntimeError(
                "ultra_below_65_blocked"
            )

        chat_id = ULTRA_CHAT
    else:
        chat_id = NORMAL_CHAT

    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendPhoto"
    )

    response = await client.post(
        url,
        data={
            "chat_id": chat_id,
            "caption": caption(job),
            "parse_mode": "HTML",
            "reply_markup": json.dumps(
                keyboard(job),
                ensure_ascii=False,
            ),
        },
        files={
            "photo": (
                "amazon-product-page.png",
                screenshot,
                "image/png",
            )
        },
        timeout=30,
    )

    data = response.json()

    if (
        not response.is_success
        or not data.get("ok")
    ):
        raise RuntimeError(
            "telegram_send_failed:"
            + str(
                data.get("description")
                or response.status_code
            )
        )


def _noon_currency_values(
    text: str,
) -> list[float]:
    raw = (
        str(text or "")
        .translate(
            str.maketrans(
                "٠١٢٣٤٥٦٧٨٩٫٬",
                "0123456789.,",
            )
        )
    )

    values = []

    patterns = (
        r"(?:EGP|جنيه(?:\s+مصري)?|ج\.?\s*م\.?)\s*"
        r"([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*"
        r"(?:EGP|جنيه(?:\s+مصري)?|ج\.?\s*م\.?)",
    )

    skip_words = (
        "month",
        "monthly",
        "installment",
        "instalment",
        "credit card",
        "debit card",
        "visa",
        "mastercard",
        "bank",
        "شهر",
        "شهريا",
        "شهرياً",
        "تقسيط",
        "قسط",
        "بطاقة",
        "بنك",
    )

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            raw,
            re.IGNORECASE,
        ):
            start = max(
                0,
                match.start() - 60,
            )

            end = min(
                len(raw),
                match.end() + 60,
            )

            context = (
                raw[start:end]
                .lower()
            )

            if any(
                word in context
                for word in skip_words
            ):
                continue

            try:
                value = float(
                    match.group(1)
                    .replace(",", "")
                )
            except Exception:
                continue

            if value > 0:
                values.append(value)

    unique = []

    for value in values:
        if not any(
            abs(value - old) <= 0.01
            for old in unique
        ):
            unique.append(value)

    return unique


def _noon_card_candidate(
    ref: dict,
    source: str,
    category: str,
) -> dict | None:
    values = _noon_currency_values(
        str(ref.get("text") or "")
    )

    if len(values) < 2:
        return None

    current = min(values)
    old = max(values)

    if not (
        old > current * 1.05
    ):
        return None

    discount = (
        (old - current)
        / old
        * 100
    )

    if discount < 10:
        return None

    title = str(
        ref.get("title") or ""
    ).strip()

    if len(title) < 5:
        return None

    return {
        "external_id":
            str(ref.get("sku") or ""),
        "title":
            title[:300],
        "url":
            str(ref.get("url") or ""),
        "current_price":
            round(current, 2),
        "old_price":
            round(old, 2),
        "image_url":
            str(
                ref.get("image_url")
                or ""
            ),
        "source":
            source,
        "category":
            category,
    }


async def _noon_product_candidate(
    client: httpx.AsyncClient,
    ref: dict,
    source: str,
    category: str,
) -> dict | None:
    sku = str(
        ref.get("sku") or ""
    ).strip()

    if not sku:
        return None

    api = (
        "https://www.noon.com/"
        "_vs/nc/mp-customer-catalog-api/"
        "api/v3/product/"
        + sku
    )

    response = await client.get(
        api,
        headers={
            "accept":
                "application/json,text/plain,*/*",
            "x-locale":
                "en-eg",
            "x-mp-country":
                "eg",
            "referer":
                "https://www.noon.com/egypt-en/",
        },
        timeout=15,
    )

    if not response.is_success:
        raise RuntimeError(
            f"noon_product_http_"
            f"{response.status_code}"
          )

    data = response.json()

    product = data.get("product")

    if not isinstance(product, dict):
        raise RuntimeError(
            "noon_product_missing"
        )

    market = json.dumps(
        {
            "meta": data.get("meta"),
            "currency":
                product.get("currency"),
            "country":
                product.get("country"),
        },
        ensure_ascii=False,
    ).lower()

    if any(
        x in market
        for x in (
            '"currency": "aed"',
            '"country": "ae"',
            "united arab emirates",
            "dubai",
            "abu dhabi",
        )
    ):
        raise RuntimeError(
            "noon_wrong_market"
        )

    variants = [
        x
        for x in (
            product.get("variants")
            if isinstance(
                product.get("variants"),
                list,
            )
            else []
        )
        if isinstance(x, dict)
    ]

    requested = sku.upper()

    chosen = None

    for variant in variants:
        variant_sku = str(
            variant.get("sku")
            or variant.get("catalog_sku")
            or ""
        ).upper()

        if variant_sku == requested:
            chosen = variant
            break

    if chosen is None and variants:
        chosen = variants[0]

    offers = []

    if isinstance(chosen, dict):
        offers = [
            x
            for x in (
                chosen.get("offers")
                if isinstance(
                    chosen.get("offers"),
                    list,
                )
                else []
            )
            if isinstance(x, dict)
        ]

    if not offers:
        offers = [
            x
            for x in (
                product.get("offers")
                if isinstance(
                    product.get("offers"),
                    list,
                )
                else []
            )
            if isinstance(x, dict)
        ]

    def price_now(offer: dict) -> float:
        for key in (
            "sale_price",
            "salePrice",
            "offer_price",
            "offerPrice",
            "price",
        ):
            value = _num(
                str(offer.get(key) or "")
            )

            if value > 0:
                return value

        return 0.0

    pool = [
        offer
        for offer in offers
        if (
            offer.get("is_buyable")
            is not False
            and price_now(offer) > 0
        )
    ]

    if not pool:
        pool = [
            offer
            for offer in offers
            if price_now(offer) > 0
        ]

    if not pool:
        raise RuntimeError(
            "noon_offer_missing"
        )

    pool.sort(
        key=price_now
    )

    offer = pool[0]

    current = price_now(offer)

    old = _num(
        str(
            offer.get("price")
            or offer.get("regular_price")
            or offer.get("regularPrice")
            or ""
        )
    )

    if not (
        old > current
    ):
        old = 0.0

    if not old:
        return None

    discount = (
        (old - current)
        / old
        * 100
    )

    if discount < 10:
        return None

    title = str(
        product.get("product_title")
        or product.get("name")
        or product.get("title")
        or ref.get("title")
        or ""
    ).strip()

    if len(title) < 5:
        return None

    image = str(
        ref.get("image_url")
        or ""
    )

    images = product.get(
        "image_urls"
    )

    if (
        isinstance(images, list)
        and images
    ):
        first = images[0]

        if isinstance(first, str):
            image = first

        elif isinstance(first, dict):
            image = str(
                first.get("url")
                or first.get("src")
                or image
            )

    return {
        "external_id":
            sku,
        "title":
            title[:300],
        "url":
            str(ref.get("url") or ""),
        "current_price":
            round(current, 2),
        "old_price":
            round(old, 2),
        "image_url":
            image,
        "source":
            source,
        "category":
            category,
    }


def _noon_api_refs(
    data,
) -> list[dict]:
    out = []
    seen = set()

    def walk(value, depth=0):
        if depth > 14 or len(out) >= 40:
            return

        if isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
            return

        if not isinstance(value, dict):
            return

        sku = str(
            value.get("sku")
            or value.get("catalog_sku")
            or value.get("product_sku")
            or value.get("id")
            or ""
        ).strip()

        title = str(
            value.get("name")
            or value.get("title")
            or value.get("product_name")
            or value.get("productName")
            or value.get("product_title")
            or ""
        ).strip()

        if (
            sku
            and len(sku) >= 5
            and title
            and sku not in seen
        ):
            raw_url = str(
                value.get("url")
                or value.get("canonical_url")
                or value.get("url_slug")
                or value.get("urlKey")
                or ""
            ).strip()

            if raw_url.startswith("http"):
                url = raw_url
            else:
                slug = raw_url.strip("/")

                if "/" in slug:
                    slug = (
                        slug.split("/")[-1]
                        or slug
                    )

                if slug:
                    url = (
                        "https://www.noon.com/"
                        f"egypt-en/{slug}/{sku}/p/"
                    )
                else:
                    url = (
                        "https://www.noon.com/"
                        f"egypt-en/{sku}/p/"
                    )

            current = 0.0
            old = 0.0

            for key in (
                "sale_price",
                "salePrice",
                "offer_price",
                "offerPrice",
            ):
                current = _num(
                    str(value.get(key) or "")
                )

                if current > 0:
                    break

            for key in (
                "price",
                "old_price",
                "oldPrice",
                "regular_price",
                "regularPrice",
            ):
                old = _num(
                    str(value.get(key) or "")
                )

                if old > 0:
                    break

            if current <= 0:
                current = old

            if old <= current:
                old = 0.0

            image = (
                value.get("image_url")
                or value.get("imageUrl")
                or value.get("thumbnailUrl")
                or value.get("image")
                or ""
            )

            if isinstance(image, dict):
                image = (
                    image.get("url")
                    or image.get("src")
                    or ""
                )

            elif (
                isinstance(image, list)
                and image
            ):
                first = image[0]

                if isinstance(first, dict):
                    image = (
                        first.get("url")
                        or first.get("src")
                        or ""
                    )
                else:
                    image = first

            seen.add(sku)

            out.append({
                "sku": sku,
                "title": title,
                "url": url,
                "image_url": str(image or ""),
                "api_current": current,
                "api_old": old,
            })

        for child in value.values():
            walk(child, depth + 1)

    walk(data)

    return out


async def discover_noon_api(
    client: httpx.AsyncClient,
    cursor: int,
) -> dict:
    source, category, query = (
        NOON_SURFACES[
            cursor
            % len(NOON_SURFACES)
        ]
    )

    encoded = quote(query)

    endpoints = [
        (
            "https://www.noon.com/"
            "_vs/nc/mp-customer-catalog-api/"
            "api/v3/search?q="
            + encoded
            + "&limit=50"
        ),
        (
            "https://www.noon.com/"
            "_vs/nc/mp-customer-catalog-api/"
            "api/v3/u/search?q="
            + encoded
            + "&limit=50"
        ),
    ]

    headers = {
        "accept":
            "application/json,text/plain,*/*",
        "x-locale":
            "en-eg",
        "x-platform":
            "web",
        "x-mp":
            "noon",
        "x-mp-country":
            "eg",
        "x-country-code":
            "eg",
        "referer":
            "https://www.noon.com/egypt-en/",
    }

    started = time.monotonic()

    last_error = "noon_api_no_endpoint"

    refs = []

    for endpoint in endpoints:
        try:
            response = await client.get(
                endpoint,
                headers=headers,
                timeout=18,
            )

            if not response.is_success:
                last_error = (
                    "noon_search_api_http_"
                    + str(response.status_code)
                )
                continue

            data = response.json()

            blob = json.dumps(
                data.get("meta", {})
                if isinstance(data, dict)
                else {},
                ensure_ascii=False,
            ).lower()

            if any(
                x in blob
                for x in (
                    "dubai",
                    "abu dhabi",
                    "united arab emirates",
                    '"country": "ae"',
                )
            ):
                last_error = (
                    "noon_search_api_wrong_market"
                )
                continue

            refs = _noon_api_refs(data)

            if refs:
                break

            last_error = (
                "noon_search_api_zero_refs"
            )

        except Exception as exc:
            last_error = (
                f"{type(exc).__name__}:"
                f"{str(exc)}"
            )

    if not refs:
        raise RuntimeError(last_error)

    deals = []

    for ref in refs[:NOON_MAX_PRODUCTS]:
        candidate = None

        try:
            candidate = (
                await _noon_product_candidate(
                    client,
                    ref,
                    source,
                    category,
                )
            )
        except Exception:
            candidate = None

        if candidate is None:
            current = float(
                ref.get("api_current") or 0
            )

            old = float(
                ref.get("api_old") or 0
            )

            if (
                old > current > 0
                and (
                    (old - current)
                    / old
                    * 100
                ) >= 10
            ):
                candidate = {
                    "external_id":
                        str(ref.get("sku") or ""),
                    "title":
                        str(ref.get("title") or "")[:300],
                    "url":
                        str(ref.get("url") or ""),
                    "current_price":
                        round(current, 2),
                    "old_price":
                        round(old, 2),
                    "image_url":
                        str(ref.get("image_url") or ""),
                    "source":
                        source,
                    "category":
                        category,
                }

        if candidate is not None:
            deals.append(candidate)

        await asyncio.sleep(0.10)

    latency_ms = int(
        (
            time.monotonic()
            - started
        )
        * 1000
    )

    result = await api_post(
        client,
        "/admin/noon-ingest",
        {
            "source":
                source,
            "category":
                category,
            "seen":
                len(refs),
            "latency_ms":
                latency_ms,
            "deals":
                deals,
            "error":
                "",
        },
    )

    return {
        "mode":
            "api",
        "source":
            source,
        "seen":
            len(refs),
        "deals":
            len(deals),
        "queued":
            result.get("queued", 0),
    }


async def discover_noon_rendered(
    context,
    client: httpx.AsyncClient,
    cursor: int,
) -> dict:
    source, category, query = (
        NOON_SURFACES[
            cursor
            % len(NOON_SURFACES)
        ]
    )

    url = (
        "https://www.noon.com/"
        "egypt-en/search/?q="
        + quote(query)
        + "&isCarouselView=false"
        + "&limit=50"
    )

    page = await context.new_page()

    await page.set_extra_http_headers({
        "Accept-Language":
            "en-EG,en;q=0.9,ar-EG;q=0.8",
        "x-locale":
            "en-eg",
        "x-mp-country":
            "eg",
        "x-country-code":
            "eg",
    })

    started = time.monotonic()

    try:
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=22000,
        )

        if (
            response is not None
            and response.status >= 400
        ):
            raise RuntimeError(
                f"noon_search_http_"
                f"{response.status}"
            )

        await page.wait_for_timeout(
            1800
        )

        body = await page.locator(
            "body"
        ).inner_text(
            timeout=7000
        )

        low = body.lower()

        if any(
            x in low
            for x in (
                "access denied",
                "captcha",
                "unusual traffic",
                "robot check",
            )
        ):
            raise RuntimeError(
                "noon_search_protected"
            )

        refs = await page.evaluate(
            """
            () => {
              const out = [];
              const seen = new Set();

              const links =
                document.querySelectorAll(
                  'a[href*="/p/"]'
                );

              for (const a of links) {
                let href = '';

                try {
                  href =
                    new URL(
                      a.getAttribute('href') || '',
                      location.href
                    ).href;
                } catch {
                  continue;
                }

                if (
                  !(
                    href.includes(
                      'noon.com/egypt-en/'
                    )
                    ||
                    href.includes(
                      'noon.com/egypt-ar/'
                    )
                  )
                ) {
                  continue;
                }

                const m =
                  href.match(
                    /\\/([A-Z0-9-]{5,})\\/p\\/?(?:[?#]|$)/i
                  );

                if (!m) continue;

                const sku =
                  m[1].toUpperCase();

                if (seen.has(sku)) {
                  continue;
                }

                seen.add(sku);

                let node = a;
                let card = a;

                for (
                  let i = 0;
                  i < 8;
                  i++
                ) {
                  node =
                    node.parentElement;

                  if (!node) break;

                  const text =
                    (
                      node.innerText
                      || ''
                    ).trim();

                  if (
                    text.length >= 20
                    && text.length <= 1800
                    && /EGP|جنيه|%|off|خصم/i.test(
                      text
                    )
                  ) {
                    card = node;
                  }
                }

                const img =
                  card.querySelector(
                    'img'
                  );

                const title =
                  (
                    a.getAttribute(
                      'aria-label'
                    )
                    || img?.getAttribute(
                      'alt'
                    )
                    || a.getAttribute(
                      'title'
                    )
                    || (
                      card.innerText
                      || ''
                    )
                      .split('\\n')
                      .map(
                        x => x.trim()
                      )
                      .find(
                        x =>
                          x.length >= 5
                          && !/^EGP\\b/i.test(x)
                      )
                    || ''
                  ).trim();

                out.push({
                  sku,
                  url: href,
                  title,
                  text:
                    (
                      card.innerText
                      || ''
                    ).trim(),
                  image_url:
                    img?.getAttribute(
                      'src'
                    )
                    || img?.getAttribute(
                      'data-src'
                    )
                    || ''
                });

                if (out.length >= 30) {
                  break;
                }
              }

              return out;
            }
            """
        )

    finally:
        await page.close()

    refs = (
        refs
        if isinstance(refs, list)
        else []
    )

    deals = []

    for ref in refs[
        :NOON_MAX_PRODUCTS
    ]:
        if not isinstance(ref, dict):
            continue

        candidate = None

        try:
            candidate = (
                await _noon_product_candidate(
                    client,
                    ref,
                    source,
                    category,
                )
            )
        except Exception:
            candidate = None

        if candidate is None:
            candidate = (
                _noon_card_candidate(
                    ref,
                    source,
                    category,
                )
            )

        if candidate is not None:
            deals.append(candidate)

        await asyncio.sleep(0.12)

    latency_ms = int(
        (
            time.monotonic()
            - started
        )
        * 1000
    )

    result = await api_post(
        client,
        "/admin/noon-ingest",
        {
            "source":
                source,
            "category":
                category,
            "seen":
                len(refs),
            "latency_ms":
                latency_ms,
            "deals":
                deals,
        },
    )

    return {
        "source":
            source,
        "seen":
            len(refs),
        "deals":
            len(deals),
        "queued":
            result.get(
                "queued",
                0,
            ),
    }


async def main() -> None:
    required()

    stop = asyncio.Event()

    loop = asyncio.get_running_loop()

    for sig in (
        signal.SIGTERM,
        signal.SIGINT,
    ):
        try:
            loop.add_signal_handler(
                sig,
                stop.set,
            )
        except NotImplementedError:
            pass

    worker_id = (
        "gha-v14-shot-"
        + uuid.uuid4().hex[:10]
    )

    started = time.monotonic()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = await browser.new_context(
            locale="ar-EG",
            timezone_id="Africa/Cairo",
            viewport={
                "width": 1280,
                "height": 900,
            },
            device_scale_factor=1,
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0 Safari/537.36"
            ),
        )

        await context.add_init_script(
            """
            Object.defineProperty(
              navigator,
              'webdriver',
              {get: () => undefined}
            );
            """
        )

        async with httpx.AsyncClient(
            follow_redirects=True
        ) as client:

            noon_cursor = 0
            next_noon_scan = 0.0

            while (
                not stop.is_set()
                and time.monotonic() - started
                    < RUN_SECONDS
            ):
                # NOON RENDERED DISCOVERY
                if (
                    time.monotonic()
                    >= next_noon_scan
                ):
                    try:
                        try:
                            noon_result = (
                                await discover_noon_api(
                                    client,
                                    noon_cursor,
                                )
                            )
                        except Exception:
                            noon_result = (
                                await discover_noon_rendered(
                                    context,
                                    client,
                                    noon_cursor,
                                )
                            )

                        print(
                            "NOON_SCAN",
                            json.dumps(
                                noon_result,
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )

                    except Exception as exc:
                        reason = (
                            f"{type(exc).__name__}:"
                            f"{str(exc)}"
                        )

                        print(
                            "NOON_SCAN_ERROR",
                            reason,
                            flush=True,
                        )

                        try:
                            source, category, _ = (
                                NOON_SURFACES[
                                    noon_cursor
                                    % len(NOON_SURFACES)
                                ]
                            )

                            await api_post(
                                client,
                                "/admin/noon-ingest",
                                {
                                    "source":
                                        source,
                                    "category":
                                        category,
                                    "seen":
                                        0,
                                    "latency_ms":
                                        0,
                                    "deals":
                                        [],
                                    "error":
                                        reason[:350],
                                },
                            )

                        except Exception as report_exc:
                            print(
                                "NOON_REPORT_ERROR",
                                type(report_exc).__name__,
                                str(report_exc),
                                flush=True,
                            )

                    noon_cursor += 1

                    next_noon_scan = (
                        time.monotonic()
                        + NOON_SCAN_SECONDS
                    )

                # Stage 1:
                # Render and verify the strongest Ultra lead.
                verify_job = None

                try:
                    verify_job = await claim_verify(
                        client,
                        worker_id,
                    )

                    if verify_job is not None:
                        try:
                            proof = await verify_rendered(
                                context,
                                verify_job,
                            )

                            result = await complete_verify(
                                client,
                                verify_job,
                                "verified",
                                proof=proof,
                            )

                            print(
                                "VERIFIED",
                                verify_job.get("external_id"),
                                result.get("lane"),
                                result.get("discount"),
                                flush=True,
                            )

                        except Exception as exc:
                            reason = (
                                f"{type(exc).__name__}:"
                                f"{str(exc)}"
                            )

                            print(
                                "VERIFY_RETRY",
                                verify_job.get("external_id"),
                                reason,
                                flush=True,
                            )

                            try:
                                await complete_verify(
                                    client,
                                    verify_job,
                                    "retry",
                                    reason=reason,
                                )
                            except Exception as ack_exc:
                                print(
                                    "VERIFY_ACK_ERROR",
                                    type(ack_exc).__name__,
                                    str(ack_exc),
                                    flush=True,
                                )

                except Exception as exc:
                    print(
                        "VERIFY_CLAIM_ERROR",
                        type(exc).__name__,
                        str(exc),
                        flush=True,
                    )

                # Stage 2:
                # Send real Amazon screenshot.
                # Ultra first, then Normal.
                job = None

                try:
                    job = await claim(
                        client,
                        "ultra",
                        worker_id,
                    )

                    if job is None:
                        job = await claim(
                            client,
                            "normal",
                            worker_id,
                        )

                except Exception as exc:
                    print(
                        "CLAIM_ERROR",
                        type(exc).__name__,
                        str(exc),
                        flush=True,
                    )

                    await asyncio.sleep(5)
                    continue

                if job is None:
                    await asyncio.sleep(2)
                    continue

                try:
                    delivery_proof = None
                    delivery_discount = 0.0

                    if str(
                        job.get("lane") or ""
                    ) == "ultra":
                        # SECOND LIVE VERIFICATION:
                        # immediately before Telegram send.
                        delivery_proof = await verify_rendered(
                            context,
                            job,
                        )

                        delivery_discount = (
                            live_effective_discount(
                                delivery_proof
                            )
                        )

                        if delivery_discount < 65:
                            await complete(
                                client,
                                job,
                                "invalid_ultra",
                                reason=(
                                    "live_delivery_discount_"
                                    f"{delivery_discount:.2f}"
                                ),
                                proof=delivery_proof,
                                live_discount=delivery_discount,
                            )

                            print(
                                "ULTRA_BLOCKED_LIVE",
                                job.get("external_id"),
                                delivery_discount,
                                flush=True,
                            )

                            await asyncio.sleep(
                                MIN_GAP
                            )
                            continue

                        job = {
                            **job,
                            "current_price":
                                delivery_proof.get(
                                    "current_price"
                                )
                                or job.get(
                                    "current_price"
                                ),
                            "old_price":
                                delivery_proof.get(
                                    "old_price"
                                )
                                or 0,
                            "real_discount":
                                delivery_discount,
                        }

                        coupon = float(
                            delivery_proof.get(
                                "coupon_percent"
                            )
                            or 0
                        )

                        if coupon > 0:
                            job["effective_price"] = round(
                                float(
                                    job.get(
                                        "current_price"
                                    )
                                    or 0
                                )
                                * (
                                    1
                                    - coupon / 100
                                ),
                                2,
                            )
                        else:
                            job["effective_price"] = (
                                job.get(
                                    "current_price"
                                )
                            )

                    shot = await capture(
                        context,
                        job,
                    )

                    await send_telegram(
                        client,
                        job,
                        shot,
                    )

                    await complete(
                        client,
                        job,
                        "sent",
                        proof=delivery_proof,
                        live_discount=delivery_discount,
                    )

                    print(
                        "SENT",
                        job.get("lane"),
                        job.get("external_id"),
                        job.get("real_discount"),
                        flush=True,
                    )

                except Exception as exc:
                    reason = (
                        f"{type(exc).__name__}:"
                        f"{str(exc)}"
                    )

                    print(
                        "RETRY",
                        job.get("lane"),
                        job.get("external_id"),
                        reason,
                        flush=True,
                    )

                    try:
                        await complete(
                            client,
                            job,
                            "retry",
                            reason,
                        )
                    except Exception as ack_exc:
                        print(
                            "ACK_ERROR",
                            type(ack_exc).__name__,
                            str(ack_exc),
                            flush=True,
                        )

                await asyncio.sleep(
                    MIN_GAP
                )

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
