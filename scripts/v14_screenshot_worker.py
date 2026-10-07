from __future__ import annotations

import asyncio
import html
import json
import os
import re
import signal
import time
import uuid

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
) -> None:
    await api_post(
        client,
        "/admin/screenshot/complete",
        {
            "deal_key":
                job["deal_key"],
            "status":
                status,
            "reason":
                reason[:350],
        },
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
                    _pct(value),
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

            while (
                not stop.is_set()
                and time.monotonic() - started
                    < RUN_SECONDS
            ):
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
