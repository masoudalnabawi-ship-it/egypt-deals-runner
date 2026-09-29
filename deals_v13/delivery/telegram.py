from __future__ import annotations

import asyncio
import html
import json
import os

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
        # Ultra deals already arrive directly in the group; no misleading
        # publish/reject actions are shown there.
        if str(row.get("lane") or "") == Lane.ULTRA.value:
            return {
                "inline_keyboard": [
                    [{"text": "🔗 فتح المنتج", "url": row["url"]}]
                ]
            }

        # Normal deals are review-only. Keep review controls until the callback
        # service is migrated fully to V13.
        short = row["deal_key"][:16]
        return {
            "inline_keyboard": [
                [
                    {"text": "🚀 نشر عاجل", "callback_data": f"v13:u:{short}"},
                    {"text": "✅ نشر عادي", "callback_data": f"v13:p:{short}"},
                ],
                [
                    {"text": "🔗 فتح المنتج", "url": row["url"]},
                    {"text": "❌ رفض", "callback_data": f"v13:r:{short}"},
                ],
            ]
        }

    async def _ensure_browser(self) -> None:
        if self._context is not None:
            return
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-quic",
                "--disable-http2",
            ],
        )
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

    async def _capture_product_screenshot(self, row: dict) -> bytes | None:
        if os.getenv("V13_PRODUCT_SCREENSHOTS", "1").strip().lower() not in {
            "1", "true", "yes", "on"
        }:
            return None

        async with self._browser_lock:
            await self._ensure_browser()
            page = await self._context.new_page()
            try:
                response = await page.goto(
                    row["url"],
                    wait_until="domcontentloaded",
                    timeout=18000,
                )
                if response is not None and response.status >= 400:
                    return None

                await page.wait_for_timeout(1700)
                body_text = await page.locator("body").inner_text(timeout=4000)
                if self._protected_page(body_text):
                    return None

                # Hide navigation/header elements so the Telegram screenshot is
                # focused on the product, price and offer area.
                hide = [
                    "header",
                    "#navbar",
                    "#nav-belt",
                    "#nav-main",
                    "#nav-subnav",
                    "#nav-progressive-subnav",
                    ".navLeftFooter",
                    "#rhf",
                    ".cookie-banner",
                ]
                for selector in hide:
                    try:
                        await page.locator(selector).evaluate_all(
                            "(els) => els.forEach(e => e.style.display='none')"
                        )
                    except Exception:
                        pass

                # Never screenshot the whole #dp-container/#ppd element:
                # it is very tall and can make Playwright jump into specs/reviews.
                anchors = (
                    ["#ppd", "#title_feature_div", "#centerCol", "#dp-container"]
                    if row["store"] == "amazon"
                    else ["[data-qa='product-page']", "main", "#__next"]
                )

                anchored = False
                for selector in anchors:
                    try:
                        loc = page.locator(selector).first
                        if await loc.count() and await loc.is_visible():
                            await loc.evaluate(
                                "el => { const y = el.getBoundingClientRect().top + window.scrollY; "
                                "window.scrollTo(0, Math.max(0, y - 8)); }"
                            )
                            anchored = True
                            break
                    except Exception:
                        continue

                if not anchored:
                    await page.evaluate("window.scrollTo(0, 0)")

                await page.wait_for_timeout(350)
                return await page.screenshot(
                    type="png",
                    full_page=False,
                    animations="disabled",
                )
            except Exception:
                return None
            finally:
                await page.close()

    async def aclose(self) -> None:
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
                    timeout=24,
                )
            except Exception:
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
                    timeout=24,
                )
            except Exception:
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

