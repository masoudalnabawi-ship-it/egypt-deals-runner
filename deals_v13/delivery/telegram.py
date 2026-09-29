from __future__ import annotations

import html
import json

import httpx

from ..config import Settings
from ..models import Lane


class TelegramDelivery:
    def __init__(self, settings: Settings):
        self.settings = settings
        if not settings.telegram_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN missing")

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

    def _caption(self, row: dict) -> str:
        store = "Amazon" if row["store"] == "amazon" else "Noon"
        lane = row.get("lane") or "normal"
        icon = "🚨" if lane == "ultra" else "🔥"
        title = html.escape((row.get("title") or "")[:300])
        current = float(row.get("current_price") or 0)
        old = float(row.get("old_price") or 0)
        real_discount = float(row.get("real_discount") or 0)
        confidence = float(row.get("confidence") or 0)
        score = float(row.get("score") or 0)
        effective = float(row.get("effective_price") or current)

        try:
            meta = json.loads(row.get("metadata_json") or "{}")
        except Exception:
            meta = {}

        reasons = meta.get("decision_reasons") or []
        reason_text = " • ".join(str(x) for x in reasons[:4])
        cross = meta.get("cross_store")
        cross_line = ""
        if isinstance(cross, dict) and cross.get("price"):
            cross_line = (
                f"\\n🔎 <b>مقارنة السوق:</b> {html.escape(str(cross.get('store') or ''))} "
                f"{float(cross['price']):,.2f} جنيه"
            )

        old_line = f" بدلًا من <s>{old:,.2f}</s>" if old > current else ""
        effective_line = (
            f"\\n🎟 <b>بعد الكوبون/العرض:</b> {effective:,.2f} جنيه"
            if effective > 0 and effective < current * 0.999 else ""
        )

        return (
            f"{icon} <b>V13 {lane.upper()} · {store}</b>\\n\\n"
            f"<b>{title}</b>\\n\\n"
            f"💰 <b>{current:,.2f} جنيه</b>{old_line}"
            f"{effective_line}\\n"
            f"📉 خصم حقيقي: <b>{real_discount:.1f}%</b>\\n"
            f"🧠 Score: <b>{score:.1f}/100</b> · ثقة: <b>{confidence*100:.0f}%</b>"
            f"{cross_line}\\n\\n"
            f"✓ {html.escape(reason_text or 'verified')}"
        )

    def _keyboard(self, row: dict) -> dict:
        short = row["deal_key"][:16]
        return {
            "inline_keyboard": [
                [
                    {"text": "🚀 نشر عاجل", "callback_data": f"v13:u:{short}"},
                    {"text": "✅ نشر عادي", "callback_data": f"v13:p:{short}"},
                ],
                [
                    {"text": "↗ فتح المنتج", "url": row["url"]},
                    {"text": "✖ رفض", "callback_data": f"v13:r:{short}"},
                ],
            ]
        }

    async def send(self, row: dict) -> dict:
        token = self.settings.telegram_token
        chat_id = self._chat_id(row["store"], row["lane"])
        caption = self._caption(row)
        keyboard = self._keyboard(row)

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            # Media is optional in V13. A broken image must never block a verified deal.
            image = (row.get("image_url") or "").strip()
            if image:
                photo_api = f"https://api.telegram.org/bot{token}/sendPhoto"
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
            text = caption + "\\n\\n" + html.escape(row["url"])
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
