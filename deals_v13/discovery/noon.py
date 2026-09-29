from __future__ import annotations

from urllib.parse import quote_plus, urljoin
import json
import re

from bs4 import BeautifulSoup

from ..models import DealCandidate
from .scheduler import Surface


BASE = "https://www.noon.com"


def _surface(name: str, category: str, query: str, priority: float = 1.0) -> Surface:
    return Surface(name, category, f"{BASE}/egypt-en/search/?q={quote_plus(query)}", priority)


NOON_SURFACES = [
    Surface("all_discount", "global", f"{BASE}/egypt-en/all-products/?sort[by]=discount&sort[dir]=desc", 1.8),
    Surface("daily_deals", "global", f"{BASE}/egypt-en/daily-deals-eg/", 1.8),
    Surface("megadeals", "global", f"{BASE}/egypt-en/eg-homepage-megadeals/", 1.7),
    _surface("mobiles", "mobiles", "mobile phones", 1.4),
    _surface("mobile_accessories", "mobiles", "mobile accessories"),
    _surface("laptops", "computers", "laptops", 1.4),
    _surface("tablets", "computers", "tablets"),
    _surface("computer_accessories", "computers", "computer accessories"),
    _surface("tvs", "electronics", "televisions", 1.2),
    _surface("audio", "electronics", "headphones earbuds speakers"),
    _surface("gaming", "electronics", "gaming"),
    _surface("appliances", "appliances", "home appliances", 1.3),
    _surface("kitchen", "kitchen", "kitchen appliances"),
    _surface("home", "home", "home decor"),
    _surface("tools", "tools", "tools home improvement"),
    _surface("beauty", "beauty", "beauty"),
    _surface("personal_care", "beauty", "personal care"),
    _surface("men_fashion", "fashion", "men fashion"),
    _surface("women_fashion", "fashion", "women fashion"),
    _surface("kids_fashion", "fashion", "kids fashion"),
    _surface("shoes", "fashion", "shoes"),
    _surface("bags", "fashion", "bags"),
    _surface("watches", "fashion", "watches"),
    _surface("sports", "sports", "sports fitness"),
    _surface("toys", "toys", "toys"),
    _surface("baby", "baby", "baby"),
    _surface("grocery", "grocery", "grocery"),
    _surface("automotive", "automotive", "car accessories"),
    _surface("office", "office", "office supplies"),
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


class NoonDiscovery:
    store = "noon"
    surfaces = NOON_SURFACES

    @staticmethod
    def _json_candidates(obj, surface: Surface, out: list[DealCandidate]) -> None:
        if isinstance(obj, dict):
            title = _first(obj, ("name", "title", "product_name", "productName"))
            current = _number(_first(obj, (
                "sale_price", "salePrice", "offer_price", "offerPrice",
                "price", "priceNow", "selling_price", "sellingPrice"
            )))
            old = _number(_first(obj, (
                "old_price", "oldPrice", "was_price", "regular_price", "regularPrice",
                "priceWas", "original_price", "originalPrice"
            )))
            url = _first(obj, ("url", "productUrl", "url_key", "urlKey", "canonical_url"))
            sku = _first(obj, ("sku", "skuCode", "product_sku", "id", "productId"))
            image = _first(obj, ("image_url", "imageUrl", "thumbnailUrl", "primaryImage", "image"))

            if isinstance(image, dict):
                image = _first(image, ("url", "src"))
            elif isinstance(image, list) and image:
                image = image[0]
                if isinstance(image, dict):
                    image = _first(image, ("url", "src"))

            if title and current > 0 and url:
                full = str(url)
                if not full.startswith("http"):
                    full = urljoin(BASE, full)
                if old <= current:
                    old = 0.0
                out.append(
                    DealCandidate(
                        store="noon",
                        external_id=str(sku or ""),
                        title=str(title),
                        url=full,
                        current_price=current,
                        old_price=old or None,
                        image_url=str(image or ""),
                        category=surface.category,
                        source=surface.name,
                        metadata={"json_source": True},
                    )
                )

            for value in obj.values():
                NoonDiscovery._json_candidates(value, surface, out)

        elif isinstance(obj, list):
            for value in obj:
                NoonDiscovery._json_candidates(value, surface, out)

    @staticmethod
    def parse_page(html: str, surface: Surface) -> list[DealCandidate]:
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

            current, old = min(values), max(values)
            if old <= current:
                old = 0.0
            href = link.get("href") or ""
            img = card.select_one("img")
            image = ""
            if img:
                image = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""

            out.append(
                DealCandidate(
                    store="noon",
                    external_id="",
                    title=title_el.get_text(" ", strip=True),
                    url=urljoin(BASE, href),
                    current_price=current,
                    old_price=old or None,
                    image_url=image,
                    category=surface.category,
                    source=surface.name,
                )
            )

        unique: dict[str, DealCandidate] = {}
        for d in out:
            identity = d.external_id or d.url
            prev = unique.get(identity)
            if prev is None or d.discount_percent > prev.discount_percent:
                unique[identity] = d
        return list(unique.values())
