from __future__ import annotations

from urllib.parse import quote_plus, urljoin
import json
import re

from bs4 import BeautifulSoup

from ..models import DealCandidate
from .scheduler import Surface


BASE = "https://www.noon.com"
CATALOG_SEARCH = f"{BASE}/_svc/catalog/api/v3/u/search/"


def _surface(name: str, category: str, query: str, priority: float = 1.0) -> Surface:
    # Public read-only catalog endpoint used by Noon's own storefront.
    return Surface(
        name,
        category,
        f"{CATALOG_SEARCH}?q={quote_plus(query)}",
        priority,
    )


# Start with high-yield concrete product categories so the live probe and
# production scheduler discover real products immediately, then rotate widely.
NOON_SURFACES = [
    _surface("mobiles", "mobiles", "mobile phones", 1.7),
    _surface("laptops", "computers", "laptops", 1.7),
    _surface("appliances", "appliances", "home appliances", 1.6),
    _surface("tablets", "computers", "tablets", 1.35),
    _surface("tvs", "electronics", "televisions", 1.35),
    _surface("audio", "electronics", "headphones earbuds speakers", 1.25),
    _surface("gaming", "electronics", "gaming", 1.2),
    _surface("smartwatches", "electronics", "smart watches", 1.15),
    _surface("mobile_accessories", "mobiles", "mobile accessories", 1.0),
    _surface("computer_accessories", "computers", "computer accessories", 1.0),
    _surface("kitchen", "kitchen", "kitchen appliances", 1.25),
    _surface("small_appliances", "appliances", "small appliances", 1.15),
    _surface("home", "home", "home decor", 1.0),
    _surface("tools", "tools", "tools home improvement", 1.0),
    _surface("beauty", "beauty", "beauty", 1.0),
    _surface("personal_care", "beauty", "personal care", 1.0),
    _surface("men_fashion", "fashion", "men fashion", 1.05),
    _surface("women_fashion", "fashion", "women fashion", 1.05),
    _surface("kids_fashion", "fashion", "kids fashion", 1.0),
    _surface("shoes", "fashion", "shoes", 1.0),
    _surface("bags", "fashion", "bags", 0.95),
    _surface("watches", "fashion", "watches", 0.95),
    _surface("sports", "sports", "sports fitness", 1.0),
    _surface("toys", "toys", "toys", 0.95),
    _surface("baby", "baby", "baby", 0.95),
    _surface("grocery", "grocery", "grocery", 1.0),
    _surface("coffee", "grocery", "coffee", 0.9),
    _surface("detergents", "grocery", "detergent cleaning", 0.9),
    _surface("automotive", "automotive", "car accessories", 0.9),
    _surface("office", "office", "office supplies", 0.85),
]


def _number(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, dict):
        for key in ("value", "amount", "price", "min", "max"):
            if key in value:
                v = _number(value.get(key))
                if v:
                    return v
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,"))
    text = text.replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    try:
        return float(m.group(1)) if m else 0.0
    except Exception:
        return 0.0


def _first(obj: dict, keys: tuple[str, ...]):
    for k in keys:
        if k in obj and obj[k] not in (None, "", [], {}):
            return obj[k]
    return None


def _canonical_product_url(hit: dict, sku: str) -> str:
    raw = str(_first(hit, ("url", "url_slug", "urlKey", "canonical_url")) or "").strip()

    if raw.startswith("http"):
        # Rewrite any non-Egypt locale path into the Egypt storefront path when
        # we can extract a slug.
        m = re.search(r"/(?:uae|saudi|egypt)-en/([^/]+)/[A-Z0-9]+/p/?", raw, re.I)
        if m:
            return f"{BASE}/egypt-en/{m.group(1)}/{sku}/p/"
        return raw

    slug = raw.strip("/")
    # The API usually returns a slug, but some payloads return a partial path.
    if "/" in slug:
        parts = [p for p in slug.split("/") if p]
        if parts and parts[-1].lower() == "p":
            parts = parts[:-1]
        if parts and parts[-1].upper() == sku.upper():
            parts = parts[:-1]
        slug = parts[-1] if parts else ""

    if slug:
        return f"{BASE}/egypt-en/{slug}/{sku}/p/"
    return f"{BASE}/egypt-en/{sku}/p/"


class NoonDiscovery:
    store = "noon"
    surfaces = NOON_SURFACES

    @staticmethod
    def _from_hit(hit: dict, surface: Surface) -> DealCandidate | None:
        if not isinstance(hit, dict):
            return None

        sku = str(_first(hit, ("sku", "catalog_sku", "sku_config", "product_sku", "id")) or "").strip()
        title = str(_first(hit, ("name", "title", "product_name", "productName")) or "").strip()

        # Noon search payload convention: price=list/was, sale_price=current.
        old = _number(_first(hit, ("price", "old_price", "oldPrice", "regular_price", "regularPrice")))
        current = _number(_first(hit, ("sale_price", "salePrice", "offer_price", "offerPrice")))
        if current <= 0:
            current = old

        if not sku or not title or current <= 0:
            return None

        if old <= current:
            old = 0.0

        image = _first(hit, ("image_url", "imageUrl", "thumbnailUrl", "primaryImage", "image"))
        if isinstance(image, dict):
            image = _first(image, ("url", "src"))
        elif isinstance(image, list) and image:
            image = image[0]
            if isinstance(image, dict):
                image = _first(image, ("url", "src"))

        rating = hit.get("product_rating")
        rating_value = 0.0
        rating_count = 0
        if isinstance(rating, dict):
            rating_value = _number(rating.get("value"))
            try:
                rating_count = int(rating.get("count") or 0)
            except Exception:
                rating_count = 0

        is_buyable = hit.get("is_buyable")
        if is_buyable is False:
            return None

        brand = _first(hit, ("brand", "brand_name", "brandName"))
        if isinstance(brand, dict):
            brand = _first(brand, ("name", "title"))

        return DealCandidate(
            store="noon",
            external_id=sku,
            title=title,
            url=_canonical_product_url(hit, sku),
            current_price=current,
            old_price=old or None,
            image_url=str(image or ""),
            category=surface.category,
            source=surface.name,
            metadata={
                "api_source": True,
                "locale": "en-eg",
                "currency": "EGP",
                "brand": str(brand or ""),
                "offer_code": str(hit.get("offer_code") or ""),
                "rating": rating_value,
                "review_count": rating_count,
                "in_stock": True if is_buyable is None else bool(is_buyable),
            },
        )

    @staticmethod
    def _parse_api(text: str, surface: Surface) -> list[DealCandidate] | None:
        raw = (text or "").lstrip()
        if not raw.startswith(("{", "[")):
            return None
        try:
            data = json.loads(raw)
        except Exception:
            return None

        if not isinstance(data, dict) or "hits" not in data:
            return None

        hits = data.get("hits")
        if not isinstance(hits, list):
            return []

        # Safety guard: if a CDN ignores x-locale and explicitly reports UAE,
        # do not contaminate the Egypt bot with AED-market prices.
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        market_text = " ".join(str(v) for v in meta.values()).lower()
        if any(x in market_text for x in ("dubai", "abu dhabi", "united arab emirates", " uae ")):
            return []

        out = []
        seen = set()
        for hit in hits:
            candidate = NoonDiscovery._from_hit(hit, surface)
            if not candidate:
                continue
            if candidate.external_id in seen:
                continue
            seen.add(candidate.external_id)
            out.append(candidate)
        return out

    @staticmethod
    def _json_candidates(obj, surface: Surface, out: list[DealCandidate]) -> None:
        """Fallback parser for embedded storefront JSON."""
        if isinstance(obj, dict):
            title = _first(obj, ("name", "title", "product_name", "productName"))
            sku = _first(obj, ("sku", "catalog_sku", "skuCode", "product_sku", "id", "productId"))
            if title and sku:
                candidate = NoonDiscovery._from_hit(obj, surface)
                if candidate:
                    out.append(candidate)
            for value in obj.values():
                NoonDiscovery._json_candidates(value, surface, out)
        elif isinstance(obj, list):
            for value in obj:
                NoonDiscovery._json_candidates(value, surface, out)

    @staticmethod
    def parse_page(html: str, surface: Surface) -> list[DealCandidate]:
        api = NoonDiscovery._parse_api(html, surface)
        if api is not None:
            return api

        # Storefront fallback remains available for future browser/proxy use.
        soup = BeautifulSoup(html or "", "html.parser")
        out: list[DealCandidate] = []

        for script in soup.select("script"):
            raw = script.string or script.get_text("", strip=True)
            if not raw or len(raw) < 20:
                continue
            typ = script.get("type") or ""
            sid = script.get("id") or ""
            if typ in {"application/json", "application/ld+json"} or "__NEXT_DATA__" in sid:
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                NoonDiscovery._json_candidates(data, surface, out)

        selectors = (
            "[data-qa='product-box'], [class*='ProductBox'], [class*='productContainer'], "
            "[class*='ProductCard'], [data-testid*='product']"
        )
        for card in soup.select(selectors):
            title_el = card.select_one(
                "[data-qa='product-name'], [class*='productTitle'], [class*='title'], h2, h3"
            )
            link = card.select_one("a[href]")
            if not (title_el and link):
                continue

            values = []
            for node in card.select(
                "[class*='priceNow'], [class*='salePrice'], [class*='priceWas'], "
                "[class*='oldPrice'], [data-qa='product-price'], [class*='price']"
            ):
                v = _number(node.get_text(" ", strip=True))
                if v:
                    values.append(v)
            if not values:
                continue

            current = min(values)
            old = max(values)
            if old <= current:
                old = 0.0

            href = link.get("href") or ""
            m = re.search(r"/([A-Z0-9]{8,24})/p/?", href, re.I)
            sku = m.group(1).upper() if m else ""
            if not sku:
                continue

            img = card.select_one("img")
            image = ""
            if img:
                image = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""

            out.append(
                DealCandidate(
                    store="noon",
                    external_id=sku,
                    title=title_el.get_text(" ", strip=True),
                    current_price=current,
                    old_price=old or None,
                    url=urljoin(BASE, href),
                    image_url=image,
                    category=surface.category,
                    source=surface.name,
                    metadata={"locale": "en-eg", "currency": "EGP"},
                )
            )

        unique: dict[str, DealCandidate] = {}
        for deal in out:
            key = deal.external_id or deal.url
            prev = unique.get(key)
            if prev is None or deal.discount_percent > prev.discount_percent:
                unique[key] = deal
        return list(unique.values())
