from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..models import DealCandidate
from ..infra.http import StoreHttpClient


class VerificationRejected(RuntimeError):
    pass


def _price(text) -> float:
    text = str(text or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,"))
    text = text.replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    try:
        return float(m.group(1)) if m else 0.0
    except Exception:
        return 0.0


def _coupon_percent(text: str) -> float:
    patterns = (
        r"(\d+(?:\.\d+)?)\s*%\s*(?:off)?\s*(?:coupon|خصم|كوبون)?",
        r"(?:coupon|كوبون|خصم)[^%]{0,50}(\d+(?:\.\d+)?)\s*%",
        r"(?:save|وفر)[^%]{0,40}(\d+(?:\.\d+)?)\s*%",
    )
    for pat in patterns:
        m = re.search(pat, text or "", re.I)
        if m:
            try:
                v = float(m.group(1))
                if 0 < v <= 90:
                    return v
            except Exception:
                pass
    return 0.0


class StoreVerifier:
    def __init__(self, http: StoreHttpClient):
        self.http = http

    async def verify(self, incoming: DealCandidate) -> tuple[DealCandidate, dict]:
        if incoming.store == "amazon":
            result = await self.http.fetch(incoming.url, "amazon")
            return self._amazon(incoming, result.text, result.via)

        if incoming.store == "noon":
            # Fast, stable path: resolve Noon SKU through its JSON catalog API,
            # avoiding the JS storefront entirely.
            if incoming.external_id:
                sku = quote(incoming.external_id, safe="")
                api_url = (
                    "https://www.noon.com/_svc/catalog/api/v3/u/"
                    f"{sku}/p"
                )
                try:
                    result = await self.http.fetch(api_url, "noon", prefer_proxy=False)
                    return self._noon_api(incoming, result.text, result.via)
                except VerificationRejected:
                    raise
                except Exception:
                    # Keep storefront fallback so a temporary API/CDN issue does
                    # not permanently remove Noon from V13.
                    pass

            result = await self.http.fetch(incoming.url, "noon")
            return self._noon(incoming, result.text, result.via)

        raise VerificationRejected("unsupported_store")

    def _amazon(self, incoming: DealCandidate, html: str, via: str):
        soup = BeautifulSoup(html, "html.parser")
        current_selectors = (
            "#corePrice_feature_div .a-price .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
            ".apexPriceToPay .a-offscreen",
            ".priceToPay .a-offscreen",
            "#price_inside_buybox",
            "#tp_price_block_total_price_ww .a-offscreen",
            "#newBuyBoxPrice",
        )
        old_selectors = (
            ".basisPrice .a-offscreen",
            "#corePrice_feature_div .a-text-price .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-text-price .a-offscreen",
            ".a-price[data-a-strike='true'] .a-offscreen",
        )

        current = 0.0
        signal_count = 0
        values = []
        for sel in current_selectors:
            for node in soup.select(sel):
                v = _price(node.get_text(" ", strip=True))
                if v > 0:
                    values.append(v)

        # Amazon occasionally exposes price only in JSON-ish attributes/scripts.
        if not values:
            for pattern in (
                r'"priceAmount"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
                r'"price"\s*:\s*"([0-9]+(?:\.[0-9]+)?)"',
                r'"displayPrice"\s*:\s*"[^0-9]*([0-9][0-9,]*(?:\.[0-9]+)?)',
            ):
                for m in re.finditer(pattern, html or "", re.I):
                    v = _price(m.group(1))
                    if v > 0:
                        values.append(v)

        if values:
            # Use the most frequent rounded price; this is safer than min(),
            # which can accidentally pick instalment values.
            rounded = [round(v, 2) for v in values]
            current = max(set(rounded), key=rounded.count)
            signal_count = sum(
                1 for v in rounded if abs(v - current) <= max(1.0, current * 0.01)
            )

        if current <= 0:
            raise VerificationRejected("amazon_no_live_price")

        old = 0.0
        for sel in old_selectors:
            for node in soup.select(sel):
                v = _price(node.get_text(" ", strip=True))
                if v > current:
                    old = max(old, v)

        page = soup.get_text(" ", strip=True)
        low = page.lower()
        coupon = _coupon_percent(page)
        flash = any(x in low for x in (
            "limited time deal", "lightning deal", "deal of the day",
            "عرض لفترة محدودة", "صفقة لفترة محدودة", "عرض محدود"
        ))

        title = incoming.title
        title_node = soup.select_one("#productTitle")
        if title_node:
            title = title_node.get_text(" ", strip=True) or title

        image = incoming.image_url
        image_node = soup.select_one("#landingImage, #imgBlkFront")
        if image_node:
            image = image_node.get("data-old-hires") or image_node.get("src") or image

        verified = DealCandidate(
            store="amazon",
            external_id=incoming.external_id,
            title=title,
            url=incoming.url,
            current_price=current,
            old_price=old or incoming.old_price,
            image_url=image,
            category=incoming.category,
            source=incoming.source,
            metadata=dict(incoming.metadata or {}),
        )
        meta = {
            "http_via": via,
            "coupon_percent": coupon,
            "flash": flash,
            "verification_signals": max(1, signal_count),
        }
        return verified, meta

    def _noon_api(self, incoming: DealCandidate, raw: str, via: str):
        try:
            data = json.loads(raw or "{}")
        except Exception as exc:
            raise VerificationRejected("noon_api_invalid_json") from exc

        product = data.get("product") if isinstance(data, dict) else None
        if not isinstance(product, dict):
            raise VerificationRejected("noon_api_product_missing")

        requested_sku = (incoming.external_id or "").upper()
        variants = product.get("variants")
        if not isinstance(variants, list):
            variants = []

        chosen_variant = None
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            if str(variant.get("sku") or "").upper() == requested_sku:
                chosen_variant = variant
                break
        if chosen_variant is None and variants:
            chosen_variant = next((v for v in variants if isinstance(v, dict)), None)

        offers = []
        if isinstance(chosen_variant, dict) and isinstance(chosen_variant.get("offers"), list):
            offers = [o for o in chosen_variant.get("offers") if isinstance(o, dict)]

        # Prefer buyable offers, then the lowest current price.
        def offer_current(o: dict) -> float:
            sale = _price(o.get("sale_price") or o.get("salePrice"))
            listed = _price(o.get("price"))
            return sale or listed

        buyable = [o for o in offers if o.get("is_buyable") is not False and offer_current(o) > 0]
        pool = buyable or [o for o in offers if offer_current(o) > 0]
        if not pool:
            raise VerificationRejected("noon_no_live_price")

        offer = min(pool, key=offer_current)
        current = offer_current(offer)
        listed = _price(offer.get("price"))
        old = listed if listed > current else 0.0

        title = str(
            product.get("product_title")
            or product.get("name")
            or product.get("title")
            or incoming.title
        ).strip()

        images = product.get("image_urls")
        image = incoming.image_url
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, str) and first:
                image = first

        brand = product.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name") or brand.get("title") or ""

        rating = product.get("product_rating")
        rating_value = 0.0
        rating_count = 0
        if isinstance(rating, dict):
            rating_value = _price(rating.get("value"))
            try:
                rating_count = int(rating.get("count") or 0)
            except Exception:
                rating_count = 0

        verified = DealCandidate(
            store="noon",
            external_id=str(product.get("sku") or incoming.external_id),
            title=title,
            url=incoming.url,
            current_price=current,
            old_price=old or incoming.old_price,
            image_url=image,
            category=incoming.category,
            source=incoming.source,
            metadata={
                **dict(incoming.metadata or {}),
                "brand": str(brand or ""),
                "seller": str(offer.get("store_name") or ""),
                "offer_code": str(offer.get("offer_code") or product.get("offer_code") or ""),
                "in_stock": offer.get("is_buyable") is not False,
                "stock": offer.get("stock"),
                "rating": rating_value,
                "review_count": rating_count,
                "locale": "en-eg",
                "currency": "EGP",
                "noon_catalog_api": True,
            },
        )

        signal_count = 1
        if old > current > 0:
            signal_count += 1
        if str(chosen_variant.get("sku") if isinstance(chosen_variant, dict) else "").upper() == requested_sku:
            signal_count += 1

        text = json.dumps(product, ensure_ascii=False)
        low = text.lower()
        flash = any(x in low for x in ("flash", "limited time", "deal of the day"))

        return verified, {
            "http_via": f"{via}:noon_catalog_api",
            "coupon_percent": 0.0,
            "flash": flash,
            "verification_signals": min(signal_count, 3),
        }

    def _noon(self, incoming: DealCandidate, html: str, via: str):
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[tuple[float, float, str, str]] = []

        def walk(obj):
            if isinstance(obj, dict):
                name = obj.get("name") or obj.get("title") or ""
                offers = obj.get("offers")
                if isinstance(offers, dict):
                    cur = _price(offers.get("sale_price") or offers.get("price") or offers.get("lowPrice"))
                    old = _price(offers.get("price") or offers.get("highPrice") or offers.get("priceBefore"))
                    if cur > 0:
                        candidates.append((cur, old if old > cur else 0.0, str(name), "json_offer"))

                cur = _price(
                    obj.get("sale_price") or obj.get("salePrice")
                    or obj.get("offer_price") or obj.get("offerPrice")
                    or obj.get("priceNow") or obj.get("price")
                )
                old = _price(
                    obj.get("old_price") or obj.get("oldPrice")
                    or obj.get("priceWas") or obj.get("regularPrice")
                    or obj.get("originalPrice")
                )
                if cur > 0 and name:
                    candidates.append((cur, old if old > cur else 0.0, str(name), "json"))

                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)

        for script in soup.select("script"):
            raw = script.string or script.get_text("", strip=True)
            typ = script.get("type") or ""
            sid = script.get("id") or ""
            if raw and (typ in {"application/json", "application/ld+json"} or "__NEXT_DATA__" in sid):
                try:
                    walk(json.loads(raw))
                except Exception:
                    pass

        visible = []
        for node in soup.select(
            "[class*='priceNow'], [class*='salePrice'], [class*='priceWas'], "
            "[class*='oldPrice'], [data-qa*='price']"
        ):
            v = _price(node.get_text(" ", strip=True))
            if v > 0:
                visible.append(v)
        if visible:
            cur = min(visible)
            old = max(visible)
            candidates.append((cur, old if old > cur else 0.0, incoming.title, "visible"))

        if not candidates:
            raise VerificationRejected("noon_no_live_price")

        target = incoming.current_price
        in_title = (incoming.title or "").lower()

        def rank(item):
            cur, _old, title, _source = item
            title_sim = SequenceMatcher(
                None, in_title, (title or "").lower()
            ).ratio() if title else 0.0
            price_gap = abs(cur - target) / max(target, 1)
            return (1.0 - title_sim) * 0.72 + price_gap * 0.28

        candidates.sort(key=rank)
        current, old, title, source = candidates[0]
        if target > 0 and abs(current - target) / target > 0.45 and len(candidates) == 1:
            raise VerificationRejected("noon_price_identity_uncertain")

        page = soup.get_text(" ", strip=True)
        low = page.lower()
        coupon = _coupon_percent(page)
        flash = any(x in low for x in (
            "limited time", "deal", "flash", "عرض محدود", "لفترة محدودة"
        ))

        verified = DealCandidate(
            store="noon",
            external_id=incoming.external_id,
            title=title or incoming.title,
            url=incoming.url,
            current_price=current,
            old_price=old or incoming.old_price,
            image_url=incoming.image_url,
            category=incoming.category,
            source=incoming.source,
            metadata=dict(incoming.metadata or {}),
        )
        meta = {
            "http_via": via,
            "coupon_percent": coupon,
            "flash": flash,
            "verification_signals": 2 if source.startswith("json") and visible else 1,
        }
        return verified, meta
