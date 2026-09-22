import re
import asyncio

import httpx
from bs4 import BeautifulSoup

from .models import DealCandidate
from .sources.amazon import HEADERS


def _price(text):
    text = str(text or "").replace(",", "")

    m = re.search(
        r"(\d+(?:\.\d+)?)",
        text,
    )

    if not m:
        return 0.0

    try:
        return float(m.group(1))
    except Exception:
        return 0.0


def _coupon_percent(text):
    """
    Extract an explicitly stated percentage coupon.
    Examples:
      15% off coupon
      save 20%
      خصم 30%
    """
    text = str(text or "")

    patterns = (
        r"(\d+(?:\.\d+)?)\s*%\s*(?:off)?\s*(?:coupon|خصم|كوبون)?",
        r"(?:coupon|كوبون|خصم)[^%]{0,40}(\d+(?:\.\d+)?)\s*%",
        r"(?:save|وفر)[^%]{0,30}(\d+(?:\.\d+)?)\s*%",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        try:
            value = float(match.group(1))

            if 0 < value <= 100:
                return value
        except Exception:
            pass

    return 0.0


class AmazonVerifier:
    def __init__(self):
        self.min_gap = 2.0
        self._lock = asyncio.Lock()

    async def verify(
        self,
        client: httpx.AsyncClient,
        deal: DealCandidate,
    ):
        async with self._lock:
            await asyncio.sleep(self.min_gap)

        r = await client.get(
            deal.url,
            headers=HEADERS,
            timeout=20,
            follow_redirects=True,
        )

        body = r.text or ""
        low = body.lower()

        if r.status_code in (403, 429):
            raise RuntimeError(
                f"amazon_verify_http_{r.status_code}"
            )

        if (
            "captcha" in low
            or "robot check" in low
            or "enter the characters you see below" in low
        ):
            raise RuntimeError(
                "amazon_verify_protection"
            )

        if r.status_code != 200:
            raise RuntimeError(
                f"amazon_verify_http_{r.status_code}"
            )

        soup = BeautifulSoup(
            body,
            "html.parser",
        )

        current_selectors = [
            "#corePrice_feature_div .a-price .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
            ".apexPriceToPay .a-offscreen",
            ".priceToPay .a-offscreen",
        ]

        old_selectors = [
            ".basisPrice .a-offscreen",
            "#corePrice_feature_div .a-text-price .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-text-price .a-offscreen",
        ]

        current = 0.0

        for selector in current_selectors:
            node = soup.select_one(selector)

            if not node:
                continue

            current = _price(
                node.get_text(" ", strip=True)
            )

            if current > 0:
                break

        old = 0.0

        for selector in old_selectors:
            node = soup.select_one(selector)

            if not node:
                continue

            value = _price(
                node.get_text(" ", strip=True)
            )

            if value > current:
                old = value
                break

        if current <= 0:
            return {
                "verified": False,
                "reason": "no_live_price",
            }

        incoming_anomaly = bool(
            (deal.metadata or {}).get("price_anomaly")
        )

        # Defense-in-depth:
        # obvious accessories/replacement parts must not be verified
        # as catastrophic price anomalies merely from a crossed-out price.
        # They can still continue through normal discount verification.
        accessory_terms = (
            "remote control",
            "replacement remote",
            "replacement for",
            "ريموت",
            "ريموت كنترول",
            "بديل لـ",
            "بديل ل",
            "case for",
            "cover for",
            "حافظة",
            "جراب",
            "screen protector",
            "واقي شاشة",
            "cable for",
            "كابل",
            "adapter for",
            "محول",
            "charger for",
            "شاحن",
            "stand for",
            "حامل",
            "strap for",
            "replacement part",
            "spare part",
        )

        title_lower = str(deal.title or "").lower()
        accessory_like = any(
            term in title_lower
            for term in accessory_terms
        )

        if accessory_like:
            incoming_anomaly = False

        anomaly_threshold = float(
            (deal.metadata or {}).get("anomaly_threshold")
            or 0
        )

        anomaly_category = str(
            (deal.metadata or {}).get("anomaly_category")
            or ""
        ).strip()

        incoming_promo = str(
            (deal.metadata or {}).get("promo_text") or ""
        ).strip()

        page_text = soup.get_text(" ", strip=True).lower()

        promo_patterns = (
            "احصل على 2 بسعر 1",
            "اشتر 1 واحصل على 1",
            "اشترِ 1 واحصل على 1",
            "2 بسعر 1",
            "اشتر أكثر ووفر",
            "اشترِ أكثر ووفر",
            "اشتر 2",
            "اشترِ 2",
            "عند شراء 2",
            "عند شراء 3",
            "خصم عند شراء",
            "خصم إضافي",
            "خصم 5%",
            "خصم 10%",
            "خصم 15%",
            "خصم 20%",
            "خصم 25%",
            "خصم 30%",
            "buy 1 get 1",
            "buy one get one",
            "buy more save more",
            "buy more & save",
            "2 for 1",
            "buy 2",
            "coupon",
            "coupon available",
            "clip coupon",
            "extra discount",
            "additional discount",
            "كوبون",
            "كوبون خصم",
            "خصم إضافي",
            "استخدم الكوبون",
            "احصل على خصم",
            "بحد أقصى",
        )

        # Coupon/promotion discovery is allowed even when the
        # search result did not explicitly expose promo_text.
        live_promo = ""

        for pattern in promo_patterns:
            if pattern.lower() in page_text:
                live_promo = pattern
                break

        coupon_percent = _coupon_percent(page_text)

        effective_price = (
            round(
                current * (1 - coupon_percent / 100),
                2,
            )
            if coupon_percent > 0 and current > 0
            else current
        )

        effective_discount = 0.0

        if old > 0 and effective_price < old:
            effective_discount = round(
                ((old - effective_price) / old) * 100,
                2,
            )

        flash_patterns = (
            "lightning deal",
            "limited time deal",
            "limited time",
            "deal of the day",
            "عرض لفترة محدودة",
            "عرض محدود",
            "لفترة محدودة",
            "صفقة لفترة محدودة",
            "ينتهي خلال",
        )

        live_flash = ""

        for pattern in flash_patterns:
            if pattern.lower() in page_text:
                live_flash = pattern
                break

        # Confirm that the suspicious live price is really present
        # on the Amazon product page.
        if (
            incoming_anomaly
            and anomaly_threshold > 0
            and current > 0
            and current <= anomaly_threshold
        ):
            verified_old = (
                old
                if old > current
                else None
            )

            verified_discount = (
                round(
                    ((old - current) / old) * 100,
                    2,
                )
                if verified_old
                else 0.0
            )

            return {
                "verified": True,
                "reason": "amazon_live_price_anomaly_verified",
                "current_price": current,
                "old_price": verified_old,
                "discount_percent": verified_discount,
                "saving": (
                    round(old - current, 2)
                    if verified_old
                    else 0.0
                ),
                "price_anomaly": True,
                "anomaly_category": anomaly_category,
                "anomaly_threshold": anomaly_threshold,
            }

        if live_promo or live_flash:
            verified_old = (
                old
                if old > current
                else None
            )

            verified_discount = (
                round(
                    ((old - current) / old) * 100,
                    2,
                )
                if verified_old
                else 0.0
            )

            return {
                "verified": True,
                "reason": "amazon_live_promo_verified",
                "current_price": current,
                "old_price": verified_old,
                "discount_percent": verified_discount,
                "saving": (
                    round(old - current, 2)
                    if verified_old
                    else 0.0
                ),
                "promo_text": live_promo or live_flash,
                "flash_deal": bool(live_flash),
                "flash_text": live_flash,
                "coupon_percent": coupon_percent,
                "effective_price": effective_price,
                "effective_discount": effective_discount,
            }

        if old <= current:
            return {
                "verified": False,
                "reason": "no_verified_old_price",
                "current_price": current,
            }

        discount = round(
            ((old - current) / old) * 100,
            2,
        )

        if discount < 5:
            return {
                "verified": False,
                "reason": "discount_below_5",
                "current_price": current,
                "old_price": old,
                "discount_percent": discount,
            }

        return {
            "verified": True,
            "reason": "amazon_product_page_verified",
            "current_price": current,
            "old_price": old,
            "discount_percent": discount,
            "saving": round(
                old - current,
                2,
            ),
            "coupon_percent": coupon_percent,
            "effective_price": effective_price,
            "effective_discount": effective_discount,
        }
