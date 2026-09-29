from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
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
        result = await self.http.fetch(incoming.url, incoming.store)
        if incoming.store == "amazon":
            return self._amazon(incoming, result.text, result.via)
        if incoming.store == "noon":
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
        )
        old_selectors = (
            ".basisPrice .a-offscreen",
            "#corePrice_feature_div .a-text-price .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-text-price .a-offscreen",
            ".a-price[data-a-strike='true'] .a-offscreen",
        )

        current = 0.0
        signal_count = 0
        for sel in current_selectors:
            node = soup.select_one(sel)
            if node:
                v = _price(node.get_text(" ", strip=True))
                if v > 0:
                    if current == 0:
                        current = v
                    if abs(v - current) <= max(1, current * 0.01):
                        signal_count += 1

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
            "verification_signals": signal_count,
        }
        return verified, meta

    def _noon(self, incoming: DealCandidate, html: str, via: str):
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[tuple[float, float, str, str]] = []

        # JSON-LD and Next data are the most stable Noon sources.
        def walk(obj):
            if isinstance(obj, dict):
                name = obj.get("name") or obj.get("title") or ""
                offers = obj.get("offers")
                if isinstance(offers, dict):
                    cur = _price(offers.get("price") or offers.get("lowPrice"))
                    old = _price(offers.get("highPrice") or offers.get("priceBefore"))
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

        # Visible-price fallback.
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

        # Prefer the same product, not merely the closest price from a large embedded JSON payload.
        target = incoming.current_price
        in_title = (incoming.title or "").lower()
        def rank(item):
            cur, _old, title, _source = item
            title_sim = SequenceMatcher(None, in_title, (title or "").lower()).ratio() if title else 0.0
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
