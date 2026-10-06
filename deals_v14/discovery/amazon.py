from __future__ import annotations

from urllib.parse import quote_plus, urljoin
import re
import json

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


def _discount_surface(
    name: str,
    percent: int,
    priority: float = 1.0,
) -> Surface:
    # Amazon's percentage-off search filter.
    # This is much stronger than merely searching the words "50% off".
    url = (
        f"{BASE}/s?"
        f"k={quote_plus('deals')}"
        f"&rh=p_8%3A{int(percent)}-"
    )
    return Surface(
        name,
        "global",
        url,
        priority,
    )


AMAZON_SURFACES = [
    Surface("goldbox", "global", f"{BASE}/gp/goldbox/", 3.5),
    _surface("limited_time", "global", "limited time deals", 1.8),
    _surface("clearance", "global", "clearance deals", 1.5),
    _surface("90off", "global", "90% off deals", 2.2),
    _surface("75off", "global", "75% off deals", 2.1),
    _surface("70off", "global", "70% off deals", 2.0),
    _surface("65off", "global", "65% off deals", 2.0),
    _surface("50off", "global", "50% off deals", 1.0),

    # Amazon Ultra direct percentage filters.
    # 65% = Ultra gate / 75% = MAX priority.
    _discount_surface("65filter", 65, 2.6),
    _discount_surface("70filter", 70, 2.7),
    _discount_surface("75filter", 75, 2.9),
    _discount_surface("90filter", 90, 3.0),

    # 50% remains useful for NORMAL discovery only.
    _discount_surface("50filter", 50, 1.0),

    _surface(
        "electronics_65hot",
        "electronics",
        "electronics 65% off",
        1.8,
    ),
    _surface(
        "appliances_65hot",
        "appliances",
        "home appliances 65% off",
        1.8,
    ),
    _surface(
        "beauty_65hot",
        "beauty",
        "beauty 65% off",
        1.6,
    ),
    _surface(
        "fashion_65hot",
        "fashion",
        "fashion 65% off",
        1.5,
    ),
    # =====================================================
    # AMAZON ULTRA 65% SMART CATEGORY MATRIX
    # Search hints only; live product verification remains mandatory.
    # =====================================================
    _surface("mobiles_65hot", "mobiles", "mobile phones 65% off", 2.0),
    _surface("laptops_65hot", "computers", "laptops 65% off", 2.0),
    _surface("tablets_65hot", "computers", "tablets 65% off", 1.9),
    _surface("tvs_65hot", "electronics", "televisions 65% off", 2.0),
    _surface("audio_65hot", "electronics", "headphones earbuds speakers 65% off", 1.9),
    _surface("gaming_65hot", "electronics", "gaming video games 65% off", 1.9),
    _surface("cameras_65hot", "electronics", "cameras photography 65% off", 1.8),
    _surface("networking_65hot", "electronics", "routers networking 65% off", 1.8),
    _surface("smart_home_65hot", "electronics", "smart home devices 65% off", 1.8),

    _surface("kitchen_65hot", "kitchen", "kitchen appliances 65% off", 2.0),
    _surface("home_65hot", "home", "home products 65% off", 1.9),
    _surface("furniture_65hot", "home", "furniture 65% off", 1.8),
    _surface("tools_65hot", "tools", "tools home improvement 65% off", 1.9),
    _surface("cleaning_65hot", "home", "cleaning products 65% off", 1.7),

    _surface("personal_care_65hot", "beauty", "personal care 65% off", 1.9),
    _surface("health_65hot", "health", "health personal care 65% off", 1.8),
    _surface("perfumes_65hot", "beauty", "perfumes fragrances 65% off", 1.9),

    _surface("shoes_65hot", "fashion", "shoes 65% off", 1.8),
    _surface("bags_65hot", "fashion", "bags luggage 65% off", 1.8),
    _surface("watches_65hot", "fashion", "watches 65% off", 1.8),
    _surface("jewelry_65hot", "fashion", "jewelry 65% off", 1.7),

    _surface("sports_65hot", "sports", "sports fitness 65% off", 1.9),
    _surface("outdoor_65hot", "sports", "outdoor camping 65% off", 1.8),

    _surface("toys_65hot", "toys", "toys games 65% off", 1.9),
    _surface("baby_65hot", "baby", "baby products 65% off", 1.9),

    _surface("grocery_65hot", "grocery", "grocery food beverages 65% off", 1.7),
    _surface("pet_65hot", "pets", "pet supplies 65% off", 1.8),

    _surface("office_65hot", "office", "office products 65% off", 1.8),
    _surface("printers_65hot", "office", "printers scanners 65% off", 1.7),
    _surface("books_65hot", "books", "books 65% off", 1.6),

    _surface("automotive_65hot", "automotive", "automotive accessories 65% off", 1.8),
    _surface("music_65hot", "music", "musical instruments 65% off", 1.7),

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

    # Wider Amazon Egypt department coverage.
    _surface("books", "books", "books deals"),
    _surface("pets", "pets", "pet supplies deals"),
    _surface("outdoor", "sports", "outdoor camping deals"),
    _surface("luggage", "fashion", "luggage travel accessories deals"),
    _surface("jewelry", "fashion", "jewelry deals"),
    _surface("health", "health", "health personal care deals"),
    _surface("perfumes", "beauty", "perfumes fragrances deals"),
    _surface("musical_instruments", "music", "musical instruments deals"),
    _surface("printers", "office", "printers scanners deals"),
    _surface("networking", "electronics", "routers networking deals"),
    _surface("smart_home", "electronics", "smart home devices deals"),
]


class AmazonDiscovery:
    store = "amazon"
    surfaces = AMAZON_SURFACES

    @staticmethod
    def parse_goldbox(
        html: str,
        surface: Surface,
    ) -> list[DealCandidate]:
        """
        Parse Amazon Today's Deals / Goldbox embedded JSON.

        Goldbox exposes structured product data including:
        ASIN, title, offer price, basis/list price, deal badge,
        deal type/state, and Lightning Deal state.

        Coupon text is only a discovery hint here.
        Final coupon value is verified on the live product page.
        """

        raw = str(html or "")
        marker = '"productSearchResponse":'
        decoder = json.JSONDecoder()

        products = []
        pos = 0

        while True:
            idx = raw.find(marker, pos)

            if idx < 0:
                break

            start = raw.find(
                "{",
                idx + len(marker),
            )

            if start < 0:
                break

            try:
                payload, consumed = decoder.raw_decode(
                    raw[start:]
                )
            except Exception:
                pos = idx + len(marker)
                continue

            if isinstance(payload, dict):
                rows = payload.get("products")

                if isinstance(rows, list):
                    products.extend(rows)

            pos = start + max(consumed, 1)

        out = []

        for product in products:
            if not isinstance(product, dict):
                continue

            asin = str(
                product.get("asin") or ""
            ).strip().upper()

            if len(asin) != 10:
                continue

            title = " ".join(
                str(
                    product.get("title") or ""
                ).split()
            )

            price = product.get("price")

            if not isinstance(price, dict):
                price = {}

            current = _p(
                (
                    price.get("priceToPay")
                    or {}
                ).get("price")
                if isinstance(
                    price.get("priceToPay"),
                    dict,
                )
                else 0
            )

            old = _p(
                (
                    price.get("basisPrice")
                    or {}
                ).get("price")
                if isinstance(
                    price.get("basisPrice"),
                    dict,
                )
                else 0
            )

            if current <= 0:
                continue

            if old <= current:
                old = 0.0

            link = str(
                product.get("link")
                or f"/dp/{asin}"
            )

            url = urljoin(
                BASE,
                link.split("?")[0],
            )

            image = ""
            image_data = product.get("image")

            if isinstance(image_data, dict):
                hi = image_data.get("hiRes")
                lo = image_data.get("lowRes")

                chosen = (
                    hi
                    if isinstance(hi, dict)
                    else lo
                    if isinstance(lo, dict)
                    else {}
                )

                base_url = str(
                    chosen.get("baseUrl")
                    or ""
                )

                extension = str(
                    chosen.get("extension")
                    or ""
                )

                if base_url:
                    image = (
                        f"{base_url}.{extension}"
                        if extension
                        and not base_url.endswith(
                            f".{extension}"
                        )
                        else base_url
                    )

            deal_details = product.get(
                "dealDetails"
            )

            if not isinstance(
                deal_details,
                dict,
            ):
                deal_details = {}

            add_to_cart = product.get(
                "addToCart"
            )

            if not isinstance(
                add_to_cart,
                dict,
            ):
                add_to_cart = {}

            promo_blob = json.dumps(
                {
                    "dealBadge":
                        product.get("dealBadge"),
                    "messaging":
                        product.get("messaging"),
                },
                ensure_ascii=False,
            )

            low_promo = promo_blob.lower()

            flash = bool(
                add_to_cart.get(
                    "isLightningDeal"
                )
                or "limited" in low_promo
                or "لفترة محدودة" in promo_blob
                or "عرض محدود" in promo_blob
            )

            coupon_hint = any(
                token in low_promo
                for token in (
                    "coupon",
                    "voucher",
                    "كوبون",
                    "قسيمة",
                )
            )

            promo_hint = ""

            if coupon_hint:
                promo_hint = "coupon"
            elif flash:
                promo_hint = "limited_time"
            elif deal_details:
                promo_hint = "amazon_deal"

            out.append(
                DealCandidate(
                    store="amazon",
                    external_id=asin,
                    title=title or asin,
                    url=url,
                    current_price=current,
                    old_price=old or None,
                    image_url=image,
                    category=surface.category,
                    source=surface.name,
                    metadata={
                        "goldbox": True,
                        "promo_hint":
                            promo_hint,
                        "coupon_hint":
                            coupon_hint,
                        "flash_hint":
                            flash,
                        "deal_id":
                            deal_details.get(
                                "id"
                            ),
                        "deal_type":
                            deal_details.get(
                                "type"
                            ),
                        "deal_state":
                            deal_details.get(
                                "state"
                            ),
                    },
                )
            )

        unique = {}

        for deal in out:
            previous = unique.get(
                deal.external_id
            )

            if (
                previous is None
                or deal.discount_percent
                > previous.discount_percent
            ):
                unique[
                    deal.external_id
                ] = deal

        return list(unique.values())

    @staticmethod
    def parse_search(html: str, surface: Surface) -> list[DealCandidate]:
        if surface.name == "goldbox":
            return AmazonDiscovery.parse_goldbox(
                html,
                surface,
            )

        soup = BeautifulSoup(html or "", "html.parser")
        out: list[DealCandidate] = []

        for card in soup.select("[data-component-type='s-search-result'][data-asin]"):
            asin = (card.get("data-asin") or "").strip().upper()
            if len(asin) != 10:
                continue

            title_el = card.select_one("h2 a span, h2 span")
            price_el = card.select_one(".a-price .a-offscreen")

            # Amazon search cards can omit the product href entirely.
            # ASIN is already canonical, so do not depend on fragile
            # card-link markup.
            if not (title_el and price_el):
                continue

            title = " ".join(title_el.get_text(" ", strip=True).split())
            current = _p(price_el.get_text(" ", strip=True))
            if not title or current <= 0:
                continue

            old = 0.0
            for node in card.select(
                ".a-text-price .a-offscreen, "
                ".a-price[data-a-strike='true'] .a-offscreen"
            ):
                val = _p(
                    node.get_text(" ", strip=True)
                )
                if val > current:
                    old = max(old, val)

            # Amazon search sometimes shows only "-XX%" and omits
            # the crossed-out price. This value is DISCOVERY ONLY;
            # the product page must prove it again before Telegram.
            if old <= current:
                for node in card.select(
                    ".savingsPercentage, "
                    "[class*='savingsPercentage']"
                ):
                    text_pct = node.get_text(
                        " ",
                        strip=True,
                    )

                    match = re.search(
                        r"-?\s*(\d+(?:\.\d+)?)\s*%",
                        text_pct,
                    )

                    if not match:
                        continue

                    try:
                        pct = float(match.group(1))
                    except Exception:
                        continue

                    if 5.0 <= pct <= 90.0:
                        derived = (
                            current
                            / (1.0 - pct / 100.0)
                        )

                        if (
                            derived > current
                            and derived
                            <= current * 10
                        ):
                            old = round(
                                derived,
                                2,
                            )
                            break

            img = card.select_one("img.s-image, img[src]")
            image = ""
            if img:
                image = img.get("src") or img.get("data-src") or ""

            # Stable canonical product URL built from ASIN.
            url = f"{BASE}/dp/{asin}"
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
