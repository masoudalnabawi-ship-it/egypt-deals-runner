\
from __future__ import annotations

from urllib.parse import quote_plus, urljoin
import re

from bs4 import BeautifulSoup

from ..models import DealCandidate
from .scheduler import Surface


BASE = "https://www.amazon.eg"


def _p(text) -> float:
    text = str(text or "").replace(",", "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,"))
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    try:
        return float(m.group(1)) if m else 0.0
    except Exception:
        return 0.0


def _surface(name: str, category: str, query: str, priority: float = 1.0) -> Surface:
    return Surface(name, category, f"{BASE}/s?k={quote_plus(query)}", priority)


AMAZON_SURFACES = [
    _surface("limited_time", "global", "limited time deals", 1.8),
    _surface("clearance", "global", "clearance deals", 1.5),
    _surface("coupon", "global", "coupon discount", 1.5),
    _surface("90off", "global", "90% off deals", 1.6),
    _surface("70off", "global", "70% off deals", 1.6),
    _surface("50off", "global", "50% off deals", 1.5),
    _surface("mobiles", "mobiles", "mobile phones deals", 1.3),
    _surface("mobile_accessories", "mobiles", "mobile accessories deals"),
    _surface("laptops", "computers", "laptops deals", 1.3),
    _surface("computer_accessories", "computers", "computer accessories deals"),
    _surface("tablets", "computers", "tablets deals"),
    _surface("tvs", "electronics", "smart tv deals", 1.2),
    _surface("audio", "electronics", "headphones earbuds speakers deals"),
    _surface("gaming", "electronics", "gaming deals"),
    _surface("cameras", "electronics", "camera deals"),
    _surface("appliances", "appliances", "home appliances deals", 1.3),
    _surface("refrigerators", "appliances", "refrigerator deals"),
    _surface("washers", "appliances", "washing machine deals"),
    _surface("ac", "appliances", "air conditioner deals"),
    _surface("kitchen", "kitchen", "kitchen appliances deals", 1.2),
    _surface("cookware", "kitchen", "cookware kitchen deals"),
    _surface("home", "home", "home deals"),
    _surface("furniture", "home", "furniture deals"),
    _surface("tools", "tools", "tools home improvement deals"),
    _surface("beauty", "beauty", "beauty deals"),
    _surface("personal_care", "beauty", "personal care deals"),
    _surface("men_fashion", "fashion", "men fashion deals"),
    _surface("women_fashion", "fashion", "women fashion deals"),
    _surface("kids_fashion", "fashion", "kids clothing deals"),
    _surface("shoes", "fashion", "shoes deals"),
    _surface("bags", "fashion", "bags deals"),
    _surface("watches", "fashion", "watches deals"),
    _surface("sports", "sports", "sports fitness deals"),
    _surface("toys", "toys", "toys games deals"),
    _surface("baby", "baby", "baby products deals"),
    _surface("grocery", "grocery", "grocery food deals"),
    _surface("coffee", "grocery", "coffee tea deals"),
    _surface("cleaning", "grocery", "detergent cleaning products deals"),
    _surface("automotive", "automotive", "car accessories deals"),
    _surface("office", "office", "office supplies deals"),
]


class AmazonDiscovery:
    store = "amazon"
    surfaces = AMAZON_SURFACES

    @staticmethod
    def parse_search(html: str, surface: Surface) -> list[DealCandidate]:
        soup = BeautifulSoup(html or "", "html.parser")
        out: list[DealCandidate] = []

        for card in soup.select("[data-component-type='s-search-result'][data-asin]"):
            asin = (card.get("data-asin") or "").strip().upper()
            if len(asin) != 10:
                continue

            title_el = card.select_one("h2 a span, h2 span")
            link_el = card.select_one("h2 a[href], a.a-link-normal[href*='/dp/']")
            price_el = card.select_one(".a-price .a-offscreen")
            if not (title_el and link_el and price_el):
                continue

            title = " ".join(title_el.get_text(" ", strip=True).split())
            current = _p(price_el.get_text(" ", strip=True))
            if not title or current <= 0:
                continue

            old = 0.0
            for node in card.select(".a-text-price .a-offscreen, .a-price[data-a-strike='true'] .a-offscreen"):
                val = _p(node.get_text(" ", strip=True))
                if val > current:
                    old = max(old, val)

            img = card.select_one("img.s-image, img[src]")
            image = ""
            if img:
                image = img.get("src") or img.get("data-src") or ""

            href = link_el.get("href") or ""
            url = urljoin(BASE, href.split("?")[0])
            text = card.get_text(" ", strip=True)
            low = text.lower()

            promo = ""
            for marker in ("coupon", "كوبون", "خصم إضافي", "limited time deal", "عرض لفترة محدودة"):
                if marker.lower() in low:
                    promo = marker
                    break

            out.append(
                DealCandidate(
                    store="amazon",
                    external_id=asin,
                    title=title,
                    url=url,
                    current_price=current,
                    old_price=old or None,
                    image_url=image,
                    category=surface.category,
                    source=surface.name,
                    metadata={
                        "surface_text": text[:600],
                        "promo_hint": promo,
                        "flash_hint": "limited time" in low or "لفترة محدودة" in low,
                    },
                )
            )

        # Keep one observation per ASIN.
        unique: dict[str, DealCandidate] = {}
        for d in out:
            prev = unique.get(d.external_id)
            if prev is None or d.discount_percent > prev.discount_percent:
                unique[d.external_id] = d
        return list(unique.values())
