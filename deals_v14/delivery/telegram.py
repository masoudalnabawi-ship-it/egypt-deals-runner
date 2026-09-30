from __future__ import annotations

import asyncio
import html
import json
import os
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..config import Settings
from ..models import Lane


class TelegramDelivery:
    def __init__(self, settings: Settings):
        self.settings = settings
        if not settings.telegram_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN missing")

        self._pw = None
        self._browser = None
        self._context = None
        self._noon_context = None
        self._noon_warmed = False
        self._browser_lock = asyncio.Lock()

    def _chat_id(self, store: str, lane: str) -> str:
        # STRICT50:
        # normal (<50%) -> private/review chat
        # ultra (>=50% or exceptional) -> ultra group
        if store == "noon":
            chat = (
                self.settings.noon_ultra_chat_id if lane == Lane.ULTRA.value
                else self.settings.noon_normal_chat_id
            )
        else:
            chat = (
                self.settings.ultra_chat_id if lane == Lane.ULTRA.value
                else self.settings.normal_chat_id
            )
        if not chat:
            raise RuntimeError(f"telegram_chat_missing:{store}:{lane}")
        return chat

    @staticmethod
    def _read_meta(row: dict) -> dict:
        try:
            value = json.loads(row.get("metadata_json") or "{}")
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _caption(self, row: dict) -> str:
        is_amazon = row["store"] == "amazon"
        store = "Amazon Egypt" if is_amazon else "Noon Egypt"
        lane = str(row.get("lane") or "normal")
        icon = "🚨" if lane == Lane.ULTRA.value else "🔥"
        lane_ar = "ألترا" if lane == Lane.ULTRA.value else "مراجعة"

        title = html.escape((row.get("title") or "منتج بدون اسم")[:190])
        current = float(row.get("current_price") or 0)
        old = float(row.get("old_price") or 0)
        real_discount = float(row.get("real_discount") or 0)
        confidence = float(row.get("confidence") or 0)
        score = float(row.get("score") or 0)
        effective = float(row.get("effective_price") or current)
        external_id = html.escape(str(row.get("external_id") or ""))
        category = html.escape(str(row.get("category") or ""))[:70]

        lines = [
            f"{icon} <b>V13 {lane_ar} • {store}</b>",
            "",
            f"🛒 <b>{title}</b>",
            "",
            f"💰 <b>السعر الآن:</b> {current:,.2f} ج.م",
        ]

        if old > current:
            lines.append(f"🏷 <b>السعر السابق:</b> <s>{old:,.2f}</s> ج.م")

        # Only show the effective price when it is plausible.
        # Never display impossible coupon math such as 6549 -> 654 from a fake 90% parse.
        if effective > 0 and effective < current * 0.999:
            implied = (current - effective) / current * 100 if current else 0
            if 0 < implied <= 60:
                lines.append(f"🎟 <b>بعد الكوبون/العرض:</b> {effective:,.2f} ج.م")

        lines.extend([
            f"📉 <b>الخصم الحقيقي:</b> {real_discount:.1f}%",
            f"🧠 <b>التقييم:</b> {score:.1f}/100",
            f"🛡 <b>الثقة:</b> {confidence * 100:.0f}%",
        ])

        if external_id:
            label = "ASIN" if is_amazon else "SKU"
            lines.append(f"🆔 <b>{label}:</b> <code>{external_id}</code>")
        if category:
            lines.append(f"📂 <b>القسم:</b> {category}")

        # Deliberately removed:
        # - verification block
        # - review time
        # - screenshot explanatory line
        return "\n".join(lines)

    def _keyboard(self, row: dict) -> dict:
        # Every deal inside a review chat, including Ultra/HOT Ultra,
        # must keep manual publish/reject controls.
        # Public-channel posts use send_public() and only show Open Product.
        short = row["deal_key"][:16]
        return {
            "inline_keyboard": [
                [
                    {"text": "🚀 نشر عاجل", "callback_data": f"v14:u:{short}"},
                    {"text": "✅ نشر عادي", "callback_data": f"v14:p:{short}"},
                ],
                [
                    {"text": "🔗 فتح المنتج", "url": row["url"]},
                    {"text": "❌ رفض", "callback_data": f"v14:r:{short}"},
                ],
            ]
        }

    async def _ensure_browser(self) -> None:
        if self._context is not None and self._noon_context is not None:
            return

        from playwright.async_api import async_playwright

        if self._pw is None:
            self._pw = await async_playwright().start()

        if self._browser is None:
            self._browser = await self._pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

        if self._context is None:
            self._context = await self._browser.new_context(
                locale="ar-EG",
                timezone_id="Africa/Cairo",
                viewport={"width": 1280, "height": 900},
                device_scale_factor=1,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/140.0 Safari/537.36"
                ),
            )

        if self._noon_context is None:
            # Use a compact desktop viewport for Telegram captures.
            # 520px mobile rendering caused Noon desktop widgets to be
            # squeezed and clipped horizontally.
            self._noon_context = await self._browser.new_context(
                locale="en-EG",
                timezone_id="Africa/Cairo",
                viewport={
                    "width": 840,
                    "height": 1000,
                },
                device_scale_factor=1,
                is_mobile=False,
                has_touch=False,
                user_agent=(
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0 Safari/537.36"
                ),
                extra_http_headers={
                    "Accept-Language":
                        "en-EG,en;q=0.9,ar-EG;q=0.8,ar;q=0.7",
                },
            )

            await self._noon_context.add_init_script(
                """
                Object.defineProperty(
                    navigator,
                    'webdriver',
                    {get: () => undefined}
                );
                """
            )

    @staticmethod
    def _protected_page(text: str) -> bool:
        low = (text or "").lower()
        return any(
            marker in low
            for marker in (
                "enter the characters you see below",
                "robot check",
                "captcha",
                "access denied",
                "unusual traffic",
            )
        )

    @staticmethod
    def _clean_noon_url(url: str) -> str:
        try:
            parts = urlsplit(str(url or ""))
            return urlunsplit(
                (
                    parts.scheme or "https",
                    parts.netloc,
                    parts.path,
                    "",
                    "",
                )
            )
        except Exception:
            return str(url or "")

    @staticmethod
    def _currency_values(text: str) -> list[float]:
        """Extract only explicitly Egyptian-currency prices.

        Supported examples:
          EGP 390.75
          390.75 EGP
          390.75 ج.م
          390.75 جنيه
          390.75 جنيه مصري
          L.E. 390.75

        Percentages such as 6% are never treated as prices.
        """
        import re

        normalized = (
            str(text or "")
            .replace("\u00a0", " ")
            .replace("\u202f", " ")
            .translate(
                str.maketrans(
                    "٠١٢٣٤٥٦٧٨٩٫٬",
                    "0123456789.,",
                )
            )
        )

        currency = (
            r"(?:"
            r"EGP|E£|"
            r"L\.?\s*E\.?|"
            r"ج\.?\s*م\.?|"
            r"جنيه(?:\s+مصري)?"
            r")"
        )

        number = (
            r"([0-9]"
            r"(?:[0-9,\s]*[0-9])?"
            r"(?:\.[0-9]+)?)"
        )

        patterns = (
            currency + r"\s*" + number,
            number + r"\s*" + currency,
        )

        out = []

        for pattern in patterns:
            for match in re.finditer(
                pattern,
                normalized,
                re.I,
            ):
                try:
                    raw = (
                        match.group(1)
                        .replace(",", "")
                        .replace(" ", "")
                    )
                    value = float(raw)
                except Exception:
                    continue

                if value > 0:
                    out.append(round(value, 2))

        return list(dict.fromkeys(out))

    @staticmethod
    def _plain_price_numbers(text: str) -> list[float]:
        """Numbers from a DOM element already identified as a price.

        A number immediately followed by % is explicitly ignored.
        """
        import re

        normalized = (
            str(text or "")
            .replace("\u00a0", " ")
            .replace("\u202f", " ")
            .translate(
                str.maketrans(
                    "٠١٢٣٤٥٦٧٨٩٫٬",
                    "0123456789.,",
                )
            )
        )

        out = []

        pattern = (
            r"(?<![0-9])"
            r"([0-9][0-9,]*(?:\.[0-9]+)?)"
            r"(?![0-9])"
        )

        for match in re.finditer(pattern, normalized):
            tail = normalized[match.end():]

            if __import__("re").match(
                r"\s*%",
                tail,
            ):
                continue

            try:
                value = float(
                    match.group(1).replace(",", "")
                )
            except Exception:
                continue

            if value > 0:
                out.append(round(value, 2))

        return list(dict.fromkeys(out))

    async def _visible_noon_price_values(
        self,
        page,
    ) -> list[float]:
        """Read only visible DOM nodes that look like price widgets."""
        selectors = (
            '[data-qa*="price" i]',
            '[data-testid*="price" i]',
            '[class*="price" i]',
            '[aria-label*="EGP" i]',
            '[aria-label*="جنيه"]',
            '[itemprop="price"]',
        )

        values = []

        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = min(
                    await locator.count(),
                    60,
                )
            except Exception:
                continue

            for index in range(count):
                item = locator.nth(index)

                try:
                    if not await item.is_visible():
                        continue

                    parts = []

                    try:
                        parts.append(
                            await item.inner_text(
                                timeout=800
                            )
                        )
                    except Exception:
                        pass

                    for attr in (
                        "aria-label",
                        "content",
                        "data-price",
                        "value",
                    ):
                        try:
                            value = await item.get_attribute(
                                attr
                            )
                            if value:
                                parts.append(value)
                        except Exception:
                            pass

                    text = " ".join(
                        str(v)
                        for v in parts
                        if v
                    )

                    values.extend(
                        self._currency_values(text)
                    )

                    values.extend(
                        self._plain_price_numbers(text)
                    )

                except Exception:
                    continue

        return list(dict.fromkeys(values))

    @staticmethod
    def _fetch_noon_html_sync(url: str) -> str:
        """Fetch the real Noon HTML using a Chrome TLS fingerprint.

        Used only as a rendering fallback when cloud Chromium itself
        cannot navigate to the storefront URL.
        """
        try:
            from curl_cffi import requests as cffi_requests

            response = cffi_requests.get(
                url,
                headers={
                    "accept": (
                        "text/html,application/xhtml+xml,"
                        "application/xml;q=0.9,*/*;q=0.8"
                    ),
                    "accept-language":
                        "en-EG,en;q=0.9,ar-EG;q=0.8",
                    "referer":
                        "https://www.noon.com/egypt-en/",
                    "x-locale": "en-eg",
                    "x-platform": "web",
                    "x-mp": "noon",
                    "x-mp-country": "eg",
                    "x-country-code": "eg",
                },
                impersonate="chrome",
                timeout=22,
                allow_redirects=True,
            )

            text = response.text or ""
            low = text.lower()

            if response.status_code != 200:
                return ""

            if len(text) < 800:
                return ""

            if any(
                marker in low
                for marker in (
                    "access denied",
                    "captcha",
                    "robot check",
                    "unusual traffic",
                )
            ):
                return ""

            return text

        except Exception:
            return ""

    async def _open_noon_product(self, page, url: str) -> None:
        clean_url = self._clean_noon_url(url)

        if not self._noon_warmed:
            warm = await self._noon_context.new_page()
            try:
                await warm.goto(
                    "https://www.noon.com/egypt-en/",
                    wait_until="domcontentloaded",
                    timeout=15000,
                )
                await warm.wait_for_timeout(700)
            except Exception:
                pass
            finally:
                await warm.close()

            self._noon_warmed = True

        targets = []

        for item in (clean_url, str(url or "")):
            if item and item not in targets:
                targets.append(item)

        last_error = None

        for target in targets:
            try:
                response = await page.goto(
                    target,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )

                if response is not None and response.status >= 400:
                    last_error = RuntimeError(
                        f"noon_browser_http_{response.status}"
                    )
                    continue

                await page.wait_for_timeout(2200)
                return

            except Exception as exc:
                last_error = exc

        # Fallback: fetch the actual Noon HTML live with curl_cffi,
        # then render that exact response at the genuine Noon URL.
        html_text = await asyncio.to_thread(
            self._fetch_noon_html_sync,
            clean_url,
        )

        if not html_text:
            raise RuntimeError(
                "noon_live_page_unavailable"
            ) from last_error

        async def fulfill_noon(route):
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=html_text,
            )

        await page.route(clean_url, fulfill_noon)

        response = await page.goto(
            clean_url,
            wait_until="domcontentloaded",
            timeout=18000,
        )

        if response is not None and response.status >= 400:
            raise RuntimeError(
                f"noon_render_http_{response.status}"
            )

        await page.wait_for_timeout(2500)

    async def _capture_product_screenshot(self, row: dict) -> bytes | None:
        if os.getenv(
            "V13_PRODUCT_SCREENSHOTS",
            "1",
        ).strip().lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return None

        async with self._browser_lock:
            await self._ensure_browser()

            is_noon = row["store"] == "noon"

            context = (
                self._noon_context
                if is_noon
                else self._context
            )

            page = await context.new_page()

            try:
                if is_noon:
                    await self._open_noon_product(
                        page,
                        row["url"],
                    )
                else:
                    response = await page.goto(
                        row["url"],
                        wait_until="domcontentloaded",
                        timeout=18000,
                    )

                    if (
                        response is not None
                        and response.status >= 400
                    ):
                        return None

                    await page.wait_for_timeout(1700)

                body_text = await page.locator(
                    "body"
                ).inner_text(timeout=6000)

                if self._protected_page(body_text):
                    if is_noon:
                        raise RuntimeError(
                            "noon_page_protected"
                        )
                    return None

                # FINAL NOON PRICE GATE.
                #
                # The exact price in our DB must physically appear on the
                # live Noon product page with EGP/ج.م next to it.
                # If API/parser says EGP 6 but page says EGP 390.75,
                # the offer is NOT allowed to reach Telegram.
                if is_noon:
                    expected = float(
                        row.get("current_price") or 0
                    )

                    if expected <= 0:
                        raise RuntimeError(
                            "noon_expected_price_invalid"
                        )

                    visible_prices = self._currency_values(
                        body_text
                    )

                    visible_prices.extend(
                        await self._visible_noon_price_values(
                            page
                        )
                    )

                    visible_prices = list(
                        dict.fromkeys(visible_prices)
                    )

                    if not visible_prices:
                        # Give React/lazy content one final chance.
                        await page.wait_for_timeout(2200)
                        body_text = await page.locator(
                            "body"
                        ).inner_text(timeout=6000)
                        visible_prices = (
                            self._currency_values(
                                body_text
                            )
                        )

                        visible_prices.extend(
                            await self._visible_noon_price_values(
                                page
                            )
                        )

                        visible_prices = list(
                            dict.fromkeys(
                                visible_prices
                            )
                        )

                    if not visible_prices:
                        raise RuntimeError(
                            "noon_visible_price_missing"
                        )

                    nearest = min(
                        visible_prices,
                        key=lambda value:
                            abs(value - expected),
                    )

                    tolerance = max(
                        1.50,
                        expected * 0.015,
                    )

                    if abs(nearest - expected) > tolerance:
                        sample = ",".join(
                            f"{v:.2f}"
                            for v in visible_prices[:8]
                        )

                        raise RuntimeError(
                            "noon_visible_price_mismatch:"
                            f"expected={expected:.2f}:"
                            f"visible={sample}"
                        )

                # Remove only navigation/chrome around the product.
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
                    "[class*='BottomNav']",
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

                if is_noon:
                    # Professional Noon hero capture:
                    # image + product name + current/old price.
                    # Stop BEFORE delivery/payment/variants so Telegram
                    # receives a compact screenshot similar to Amazon.
                    try:
                        await page.evaluate(
                            """
                            () => {
                              window.scrollTo(0, 0);
                              document.documentElement.style
                                .overflowX = 'hidden';
                              document.body.style
                                .overflowX = 'hidden';
                            }
                            """
                        )

                        main = page.locator("main").first

                        if (
                            await main.count()
                            and await main.is_visible()
                        ):
                            await main.evaluate(
                                """
                                el => {
                                  const y =
                                    el.getBoundingClientRect().top
                                    + window.scrollY;
                                  window.scrollTo(
                                    0,
                                    Math.max(0, y)
                                  );
                                }
                                """
                            )

                    except Exception:
                        await page.evaluate(
                            "window.scrollTo(0, 0)"
                        )

                    await page.wait_for_timeout(500)

                    try:
                        delivery_y = await page.evaluate(
                            """
                            () => {
                              const nodes =
                                Array.from(
                                  document.querySelectorAll(
                                    'main *'
                                  )
                                );

                              const found = nodes.find(el => {
                                const text =
                                  (el.innerText || '')
                                    .trim();

                                if (
                                  !/delivery information/i
                                    .test(text)
                                ) {
                                  return false;
                                }

                                const r =
                                  el.getBoundingClientRect();

                                return (
                                  r.width > 20
                                  && r.height > 5
                                  && r.top > 280
                                );
                              });

                              if (!found) return null;

                              return found
                                .getBoundingClientRect()
                                .top;
                            }
                            """
                        )
                    except Exception:
                        delivery_y = None

                    if not isinstance(
                        delivery_y,
                        (int, float),
                    ) or delivery_y < 320:
                        delivery_y = 760

                    viewport = (
                        page.viewport_size
                        or {
                            "width": 840,
                            "height": 1000,
                        }
                    )

                    scroll_y = float(
                        await page.evaluate(
                            "window.scrollY"
                        )
                        or 0
                    )

                    hero_height = max(
                        420,
                        min(
                            900,
                            int(delivery_y - 10),
                        ),
                    )

                    return await page.screenshot(
                        type="png",
                        full_page=False,
                        animations="disabled",
                        clip={
                            "x": 0,
                            "y":                                 scroll_y,
                            "width": int(
                                viewport["width"]
                            ),
                            "height": hero_height,
                        },
                    )

                else:
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
                            "window.scrollTo(0, 0)"
                        )

                await page.wait_for_timeout(500)

                return await page.screenshot(
                    type="png",
                    full_page=False,
                    animations="disabled",
                )

            except Exception:
                if is_noon:
                    raise
                return None

            finally:
                await page.close()

    async def aclose(self) -> None:
        if self._noon_context is not None:
            try:
                await self._noon_context.close()
            except Exception:
                pass
            self._noon_context = None

        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

    async def send(self, row: dict) -> dict:
        token = self.settings.telegram_token
        chat_id = self._chat_id(row["store"], row["lane"])
        caption = self._caption(row)
        keyboard = self._keyboard(row)
        photo_api = f"https://api.telegram.org/bot{token}/sendPhoto"

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            screenshot = None
            try:
                screenshot = await asyncio.wait_for(
                    self._capture_product_screenshot(row),
                    timeout=60 if row["store"] == "noon" else 24,
                )
            except Exception as exc:
                if row["store"] == "noon":
                    raise RuntimeError(
                        "noon_live_screenshot_failed:"
                        + str(exc)
                    ) from exc
                screenshot = None

            if screenshot:
                try:
                    r = await client.post(
                        photo_api,
                        data={
                            "chat_id": chat_id,
                            "caption": caption,
                            "parse_mode": "HTML",
                            "reply_markup": json.dumps(keyboard, ensure_ascii=False),
                        },
                        files={"photo": ("product-page.png", screenshot, "image/png")},
                    )
                    data = r.json()
                    if data.get("ok"):
                        return data["result"]
                except Exception:
                    pass

            if row["store"] == "noon":
                raise RuntimeError(
                    "noon_real_product_screenshot_required"
                )

            image = (row.get("image_url") or "").strip()
            if image:
                try:
                    r = await client.post(
                        photo_api,
                        json={
                            "chat_id": chat_id,
                            "photo": image,
                            "caption": caption,
                            "parse_mode": "HTML",
                            "reply_markup": keyboard,
                        },
                    )
                    data = r.json()
                    if data.get("ok"):
                        return data["result"]
                except Exception:
                    pass

            text_api = f"https://api.telegram.org/bot{token}/sendMessage"
            text = caption + "\n\n🔗 " + html.escape(row["url"])
            r = await client.post(
                text_api,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                    "reply_markup": keyboard,
                },
            )
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError("telegram_send_failed:" + str(data.get("description") or data))
            return data["result"]

    def _public_chat_id(self, store: str) -> str:
        if store == "noon":
            chat = (
                os.getenv("NOON_CHANNEL_ID", "").strip()
                or os.getenv("AMAZON_CHANNEL_ID", "").strip()
                or os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
                or self.settings.noon_ultra_chat_id
            )
        else:
            chat = (
                os.getenv("AMAZON_CHANNEL_ID", "").strip()
                or os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
                or self.settings.ultra_chat_id
            )
        if not chat:
            raise RuntimeError(f"telegram_public_chat_missing:{store}")
        return chat

    async def send_public(self, row: dict, urgent: bool = False) -> dict:
        token = self.settings.telegram_token
        chat_id = self._public_chat_id(row["store"])
        caption = self._caption(row)
        prefix = "🚀 <b>نشر عاجل</b>\n\n" if urgent else "✅ <b>عرض معتمد</b>\n\n"
        caption = prefix + caption
        keyboard = {
            "inline_keyboard": [
                [{"text": "🔗 فتح المنتج", "url": row["url"]}]
            ]
        }
        photo_api = f"https://api.telegram.org/bot{token}/sendPhoto"

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            screenshot = None
            try:
                screenshot = await asyncio.wait_for(
                    self._capture_product_screenshot(row),
                    timeout=60 if row["store"] == "noon" else 24,
                )
            except Exception as exc:
                if row["store"] == "noon":
                    raise RuntimeError(
                        "noon_live_screenshot_failed:"
                        + str(exc)
                    ) from exc
                screenshot = None

            if screenshot:
                try:
                    r = await client.post(
                        photo_api,
                        data={
                            "chat_id": chat_id,
                            "caption": caption[:1024],
                            "parse_mode": "HTML",
                            "reply_markup": json.dumps(keyboard, ensure_ascii=False),
                        },
                        files={"photo": ("product-hero.png", screenshot, "image/png")},
                    )
                    data = r.json()
                    if data.get("ok"):
                        return data["result"]
                except Exception:
                    pass

            if row["store"] == "noon":
                raise RuntimeError(
                    "noon_real_product_screenshot_required"
                )

            image = (row.get("image_url") or "").strip()
            if image:
                try:
                    r = await client.post(
                        photo_api,
                        json={
                            "chat_id": chat_id,
                            "photo": image,
                            "caption": caption[:1024],
                            "parse_mode": "HTML",
                            "reply_markup": keyboard,
                        },
                    )
                    data = r.json()
                    if data.get("ok"):
                        return data["result"]
                except Exception:
                    pass

            text_api = f"https://api.telegram.org/bot{token}/sendMessage"
            text = caption + "\n\n🔗 " + html.escape(str(row["url"]))
            r = await client.post(
                text_api,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                    "reply_markup": keyboard,
                },
            )
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(
                    "telegram_public_send_failed:"
                    + str(data.get("description") or data)
                )
            return data["result"]

    async def delete_webhook(self) -> None:
        url = f"https://api.telegram.org/bot{self.settings.telegram_token}/deleteWebhook"
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                await client.post(url, json={"drop_pending_updates": False})
            except Exception:
                pass

    async def get_updates(self, offset: int | None, timeout: int = 20) -> list[dict]:
        url = f"https://api.telegram.org/bot{self.settings.telegram_token}/getUpdates"
        payload = {
            "timeout": timeout,
            "allowed_updates": ["callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        async with httpx.AsyncClient(timeout=timeout + 10) as client:
            r = await client.post(url, json=payload)
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(
                    "telegram_get_updates_failed:"
                    + str(data.get("description") or data)
                )
            return data.get("result") or []

    async def answer_callback(
        self,
        callback_id: str,
        text: str,
        alert: bool = False,
    ) -> None:
        url = (
            f"https://api.telegram.org/bot{self.settings.telegram_token}"
            "/answerCallbackQuery"
        )
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                url,
                json={
                    "callback_query_id": callback_id,
                    "text": text[:190],
                    "show_alert": alert,
                },
            )

    async def clear_buttons(self, chat_id: int | str, message_id: int) -> None:
        url = (
            f"https://api.telegram.org/bot{self.settings.telegram_token}"
            "/editMessageReplyMarkup"
        )
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "reply_markup": {"inline_keyboard": []},
                },
            )

