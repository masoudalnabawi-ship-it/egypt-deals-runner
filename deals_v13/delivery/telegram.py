from __future__ import annotations

import asyncio
import html
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

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

    @staticmethod
    def _friendly_reasons(meta: dict) -> list[str]:
        raw = meta.get("decision_reasons") or []
        if not isinstance(raw, list):
            raw = []

        labels = {
            "product_page_verified": "تم التحقق من صفحة المنتج",
            "multi_signal_price": "السعر مؤكد بأكثر من إشارة",
            "live_old_price": "السعر السابق ظاهر حاليًا",
            "price_history_support": "تاريخ السعر يدعم الخصم",
            "cross_store_advantage": "أفضل من المتجر المقارن",
            "flash": "عرض سريع/محدود",
            "verified": "تم التحقق المباشر",
            "price_anomaly": "انخفاض سعر غير معتاد",
        }

        out: list[str] = []
        for item in raw:
            key = str(item)
            if key.startswith("coupon_"):
                pct = key.split("_", 1)[1]
                label = f"كوبون {pct}%"
            else:
                label = labels.get(key, key.replace("_", " "))
            if label not in out:
                out.append(label)
        return out[:3]

    def _caption(self, row: dict) -> str:
        is_amazon = row["store"] == "amazon"
        store = "Amazon Egypt" if is_amazon else "Noon Egypt"
        lane = str(row.get("lane") or "normal")
        icon = "🚨" if lane == "ultra" else "🔥"
        lane_ar = "ألترا" if lane == "ultra" else "عادي"

        title = html.escape((row.get("title") or "منتج بدون اسم")[:180])
        current = float(row.get("current_price") or 0)
        old = float(row.get("old_price") or 0)
        real_discount = float(row.get("real_discount") or 0)
        confidence = float(row.get("confidence") or 0)
        score = float(row.get("score") or 0)
        effective = float(row.get("effective_price") or current)
        external_id = html.escape(str(row.get("external_id") or ""))
        category = html.escape(str(row.get("category") or ""))[:70]
        reviewed_at = datetime.now(ZoneInfo("Africa/Cairo")).strftime("%H:%M")

        meta = self._read_meta(row)
        reasons = self._friendly_reasons(meta)
        cross = meta.get("cross_store")

        lines = [
            f"{icon} <b>V13 {lane_ar} • {store}</b>",
            "",
            f"🛒 <b>{title}</b>",
            "",
            f"💰 <b>السعر الآن:</b> {current:,.2f} ج.م",
        ]

        if old > current:
            lines.append(f"🏷 <b>السعر السابق:</b> <s>{old:,.2f}</s> ج.م")
        if effective > 0 and effective < current * 0.999:
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

        if isinstance(cross, dict) and cross.get("price"):
            cross_store = html.escape(str(cross.get("store") or "المتجر الآخر").title())
            lines.append(
                f"🔎 <b>مقارنة السوق:</b> {cross_store} — {float(cross['price']):,.2f} ج.م"
            )

        if reasons:
            lines.append("")
            lines.append("✅ <b>التحقق:</b>")
            lines.extend(f"• {html.escape(reason)}" for reason in reasons)

        lines.extend([
            "",
            f"🕒 <b>وقت المراجعة:</b> {reviewed_at}",
            "📸 <i>المرفق لقطة فعلية من صفحة المنتج وقت المراجعة.</i>",
        ])

        return "\n".join(lines)

    def _keyboard(self, row: dict) -> dict:
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
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            raise RuntimeError(f"playwright_unavailable:{type(exc).__name__}") from exc

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
            viewport={"width": 1280, "height": 1100},
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

                # Keep store header + product hero/price visible.
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(300)

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
            # First choice: genuine screenshot of the live product page.
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

            # Second choice: product image from the store.
            image = (row.get("image_url") or "").strip()
            if image:
                fallback_caption = caption.replace(
                    "📸 <i>المرفق لقطة فعلية من صفحة المنتج وقت المراجعة.</i>",
                    "🖼 <i>تعذر التقاط الصفحة؛ المرفق صورة المنتج من المتجر.</i>",
                )
                try:
                    r = await client.post(
                        photo_api,
                        json={
                            "chat_id": chat_id,
                            "photo": image,
                            "caption": fallback_caption,
                            "parse_mode": "HTML",
                            "reply_markup": keyboard,
                        },
                    )
                    data = r.json()
                    if data.get("ok"):
                        return data["result"]
                except Exception:
                    pass

            # Final fallback: verified text, so media can never lose a deal.
            text_api = f"https://api.telegram.org/bot{token}/sendMessage"
            text = caption.replace(
                "📸 <i>المرفق لقطة فعلية من صفحة المنتج وقت المراجعة.</i>",
                "⚠️ <i>تعذر إرفاق صورة؛ بيانات العرض ما زالت متحققة.</i>",
            ) + "\n\n🔗 " + html.escape(row["url"])
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
