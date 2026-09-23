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

        self.normal_chat_id = (
            os.getenv("REVIEW_CHAT_ID", "").strip()
            or os.getenv(
                "AMAZON_NORMAL_REVIEW_CHAT_ID",
                "",
            ).strip()
        )

        self.ultra_chat_id = os.getenv(
            "AMAZON_REVIEW_GROUP_ID",
            "",
        ).strip()

        self.chat_id = self.normal_chat_id

        if not self.token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN missing"
            )

        if not self.normal_chat_id:
            raise RuntimeError(
                "AMAZON_NORMAL_REVIEW_CHAT_ID missing"
            )

    def _brand_and_details(self, deal: DealCandidate):
        meta = deal.metadata or {}

        brand = str(
            meta.get("brand")
            or meta.get("brand_name")
            or meta.get("manufacturer")
            or ""
        ).strip()

        title = " ".join(str(deal.title or "").split())

        if not brand and title:
            first = title.split()[0].strip(
                " -–—,:،|()[]{}"
            )

            generic_words = {
                "تيشيرت", "قميص", "بنطلون", "حذاء",
                "هاتف", "موبايل", "سماعة", "شاحن",
                "ماكينة", "جهاز", "طقم", "عبوة",
                "كابل", "شنطة", "ساعة", "منتج",
            }

            if first and first.lower() not in generic_words:
                brand = first

        if not brand:
            brand = "غير محددة"

        details_source = title

        if (
            brand != "غير محددة"
            and details_source.lower().startswith(brand.lower())
        ):
            details_source = details_source[len(brand):].lstrip(
                " -–—,:،|"
            )

        normalized = (
            details_source
            .replace("،", ",")
            .replace("|", ",")
            .replace(" - ", ",")
            .replace(" – ", ",")
            .replace(" — ", ",")
        )

        parts = [
            part.strip()
            for part in normalized.split(",")
            if part.strip()
        ]

        details = " • ".join(parts[:3]).strip()

        if not details:
            details = details_source.strip()

        if not details:
            details = "تفاصيل المنتج متاحة داخل صفحة المتجر"

        return brand[:60], details[:180]


    def _alert_banner(self, deal: DealCandidate):
        if bool((deal.metadata or {}).get("price_anomaly")):
            category = str(
                (deal.metadata or {}).get("anomaly_category")
                or "منتج مرتفع القيمة"
            )

            return (
                "◆◆ سعر غير منطقي — مراجعة فورية ◆◆\n"
                f"الفئة: {html.escape(category)} "
                f"| السعر المرصود: {deal.current_price:,.2f} جنيه\n\n"
            )

        old_price = float(deal.old_price or 0)
        current_price = float(deal.current_price or 0)
        discount = float(deal.discount_percent or 0)

        ratio = (
            current_price / old_price
            if old_price > 0 and current_price > 0
            else 1.0
        )

        # Expensive product collapsing to an extremely tiny price.
        # Example: 10,000 -> 131 EGP.
        if (
            old_price >= 1000
            and (
                ratio <= 0.05
                or (
                    discount >= 95
                    and current_price <= 500
                )
            )
        ):
            return (
                "◆◆ سعر غير منطقي — مراجعة فورية ◆◆\n"
                f"انخفاض حاد: {old_price:,.2f} ← {current_price:,.2f} جنيه "
                f"({discount:.1f}%)\n\n"
            )

        if discount >= 90:
            return (
                f"◆◆ خصم استثنائي — {discount:.1f}% ◆◆\n\n"
            )

        if discount >= 70:
            return (
                f"◆ خصم قوي — {discount:.1f}% ◆\n\n"
            )

        return ""


    def _caption(self, deal: DealCandidate):
        saving = deal.saving
        discount = deal.discount_percent

        store_key = str(deal.store or "").lower()
        store_name = {
            "amazon": "Amazon",
            "btech": "BTECH",
            "noon": "Noon",
            "2b": "2B",
            "twob": "2B",
        }.get(store_key, str(deal.store).upper())

        id_label = (
            "ASIN"
            if store_key == "amazon"
            else "معرف المنتج"
        )

        brand, _details = self._brand_and_details(deal)
        banner = self._alert_banner(deal)

        promo_text = str(
            (deal.metadata or {}).get("promo_text") or ""
        ).strip()

        promo_line = (
            f"◇ <b>العرض:</b> {html.escape(promo_text)}\n"
            if promo_text
            else ""
        )

        old_price_line = (
            f"| بدلًا من <s>{deal.old_price:,.2f} جنيه</s>"
            if deal.old_price
            else ""
        )

        verified_text = (
            "تم التحقق من السعر من صفحة المنتج مباشرة."
            if deal.metadata.get("verification")
            else "تم رصد العرض مباشرة من المتجر."
        )

        price_block = (
            f"▰ <b>السعر:</b> "
            f"<b>{deal.current_price:,.2f} جنيه</b> "
            f"{old_price_line}\n"
        )

        if promo_line:
            price_block += promo_line

        if deal.old_price and discount > 0:
            price_block += (
                f"◇ <b>خصم {discount:.1f}%</b> "
                f"• توفير <b>{saving:,.2f} جنيه</b>\n"
            )

        return (
            f"{banner}"
            f"◆ <b>عرض {store_name} للمراجعة</b>\n\n"

            f"◈ <b>المنتج</b>\n"
            f"{html.escape(deal.title[:260])}\n\n"

            f"▣ <b>الماركة:</b> "
            f"{html.escape(brand)}\n\n"

            f"{price_block}\n"

            f"• {id_label}: "
            f"<code>{html.escape(deal.external_id)}</code>\n"

            f"✓ {verified_text}"
        )


    def _keyboard(self, deal: DealCandidate):
        short_fp = deal.fingerprint[:16]

        return {
            "inline_keyboard": [
                [
                    {
                        "text": "◆ نشر عاجل",
                        "callback_data": f"v12:u:{short_fp}",
                    },
                    {
                        "text": "▣ نشر عادي",
                        "callback_data": f"v12:p:{short_fp}",
                    },
                ],
                [
                    {
                        "text": "✎ تعديل الرسالة",
                        "callback_data": f"v12:e:{short_fp}",
                    },
                    {
                        "text": "↗ فتح المنتج",
                        "url": deal.url,
                    },
                ],
                [
                    {
                        "text": "× رفض",
                        "callback_data": f"v12:r:{short_fp}",
                    },
                ],
            ]
        }


    def _route_chat(self, deal: DealCandidate):
        store_is_amazon = (
            str(deal.store).lower() == "amazon"
        )

        meta = deal.metadata or {}

        visible_discount = float(
            deal.discount_percent or 0
        )

        try:
            effective_discount = float(
                meta.get("effective_discount") or 0
            )
        except (TypeError, ValueError):
            effective_discount = 0.0

        # Use the strongest real discount, including coupons/promos.
        best_discount = max(
            visible_discount,
            effective_discount,
        )

        is_ultra_discount = best_discount >= 50

        is_verified_anomaly = bool(
            meta.get("price_anomaly")
        )

        if (
            store_is_amazon
            and (
                is_ultra_discount
                or is_verified_anomaly
            )
        ):
            if not self.ultra_chat_id:
                raise RuntimeError(
                    "AMAZON_REVIEW_GROUP_ID missing for Ultra deal"
                )

            return self.ultra_chat_id, "ultra"

        return self.normal_chat_id, "normal"

    async def send_review(self, deal: DealCandidate):
        local_path = str(
            deal.metadata.get("review_media_path") or ""
        ).strip()

        if not local_path and not deal.image_url:
            raise RuntimeError("deal_image_missing")

        route_chat_id, route_name = self._route_chat(deal)

        print(
            "📨 V12 REVIEW ROUTE",
            deal.external_id,
            f"{deal.discount_percent:.1f}%",
            "->",
            route_name,
            flush=True,
        )

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
                    "chat_id": route_chat_id,
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
                "chat_id": route_chat_id,
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
                "chat_id": route_chat_id,
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
