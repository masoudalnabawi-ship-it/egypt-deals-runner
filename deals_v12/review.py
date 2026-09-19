import html
import os

import httpx

from .models import DealCandidate


class TelegramReviewer:
    def __init__(self):
        self.token = os.getenv(
            "TELEGRAM_BOT_TOKEN",
            "",
        ).strip()

        self.chat_id = (
            os.getenv("REVIEW_CHAT_ID", "").strip()
            or os.getenv(
                "AMAZON_NORMAL_REVIEW_CHAT_ID",
                "",
            ).strip()
        )

        if not self.token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN missing"
            )

        if not self.chat_id:
            raise RuntimeError(
                "REVIEW_CHAT_ID missing"
            )

    def _caption(self, deal: DealCandidate):
        saving = deal.saving
        discount = deal.discount_percent

        return (
            "🔥 <b>عرض Amazon مؤكد — V12</b>\n\n"
            f"📦 <b>{html.escape(deal.title[:260])}</b>\n\n"
            f"💰 السعر الحالي: <b>{deal.current_price:,.2f} جنيه</b>\n"
            f"📊 السعر السابق: <s>{deal.old_price:,.2f} جنيه</s>\n"
            f"📉 الخصم المؤكد: <b>{discount:.1f}%</b>\n"
            f"💵 التوفير: <b>{saving:,.2f} جنيه</b>\n\n"
            f"🔎 ASIN: <code>{html.escape(deal.external_id)}</code>\n"
            "✅ تم التحقق من صفحة المنتج مباشرة."
        )

    def _keyboard(self, deal: DealCandidate):
        short_fp = deal.fingerprint[:16]

        return {
            "inline_keyboard": [
                [
                    {
                        "text": "🚀 نشر عاجل",
                        "callback_data": f"v12:u:{short_fp}",
                    },
                    {
                        "text": "📢 نشر عادي",
                        "callback_data": f"v12:p:{short_fp}",
                    },
                ],
                [
                    {
                        "text": "✏️ تعديل الرسالة",
                        "callback_data": f"v12:e:{short_fp}",
                    },
                    {
                        "text": "🔗 فتح المنتج",
                        "url": deal.url,
                    },
                ],
                [
                    {
                        "text": "❌ رفض",
                        "callback_data": f"v12:r:{short_fp}",
                    },
                ],
            ]
        }

    async def send_review(self, deal: DealCandidate):
        local_path = str(
            deal.metadata.get("review_media_path") or ""
        ).strip()

        if not local_path and not deal.image_url:
            raise RuntimeError("deal_image_missing")

        api = (
            f"https://api.telegram.org/"
            f"bot{self.token}/sendPhoto"
        )

        caption = self._caption(deal)
        keyboard = self._keyboard(deal)

        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
        ) as client:
            # Preferred V12 media:
            # real screenshot captured from Amazon product page.
            if local_path and os.path.isfile(local_path):
                form = {
                    "chat_id": self.chat_id,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "reply_markup": __import__("json").dumps(
                        keyboard,
                        ensure_ascii=False,
                    ),
                }

                with open(local_path, "rb") as fh:
                    files = {
                        "photo": (
                            "amazon-page.jpg",
                            fh,
                            "image/jpeg",
                        )
                    }

                    response = await client.post(
                        api,
                        data=form,
                        files=files,
                    )

                data = response.json()

                if not data.get("ok"):
                    raise RuntimeError(
                        "telegram_screenshot_send_failed: "
                        + str(data.get("description") or data)
                    )

                return data["result"]


            # First try: let Telegram fetch the image URL.
            payload = {
                "chat_id": self.chat_id,
                "photo": deal.image_url,
                "caption": caption,
                "parse_mode": "HTML",
                "reply_markup": keyboard,
            }

            response = await client.post(
                api,
                json=payload,
            )

            data = response.json()

            if data.get("ok"):
                return data["result"]

            # Fallback: download the image ourselves,
            # then upload it to Telegram in the SAME message.
            image_response = await client.get(
                deal.image_url,
                timeout=20,
            )
            image_response.raise_for_status()

            files = {
                "photo": (
                    "amazon.jpg",
                    image_response.content,
                    image_response.headers.get(
                        "content-type",
                        "image/jpeg",
                    ),
                )
            }

            form = {
                "chat_id": self.chat_id,
                "caption": caption,
                "parse_mode": "HTML",
                "reply_markup": __import__("json").dumps(
                    keyboard,
                    ensure_ascii=False,
                ),
            }

            response = await client.post(
                api,
                data=form,
                files=files,
            )

            data = response.json()

            if not data.get("ok"):
                raise RuntimeError(
                    "telegram_send_photo_failed: "
                    + str(data.get("description") or data)
                )

            return data["result"]
