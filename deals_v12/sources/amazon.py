from __future__ import annotations

import re
import time
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from ..models import DealCandidate


BASE = "https://www.amazon.eg"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml",
}


PRIORITY_SURFACES = [

    ("limited_time", BASE + "/s?k=" + quote_plus("limited time deals")),
    ("sale", BASE + "/s?k=" + quote_plus("sale deals")),
    ("discount", BASE + "/s?k=" + quote_plus("discount deals")),
    ("offers", BASE + "/s?k=" + quote_plus("offers")),
    ("clearance", BASE + "/s?k=" + quote_plus("clearance deals")),

    ("electronics", BASE + "/s?k=" + quote_plus("electronics deals")),
    ("mobiles", BASE + "/s?k=" + quote_plus("mobile phones deals")),
    ("laptops", BASE + "/s?k=" + quote_plus("laptops deals")),
    ("tablets", BASE + "/s?k=" + quote_plus("tablets deals")),
    ("tvs", BASE + "/s?k=" + quote_plus("smart tv deals")),
    ("monitors", BASE + "/s?k=" + quote_plus("computer monitors deals")),
    ("headphones", BASE + "/s?k=" + quote_plus("headphones earbuds deals")),
    ("gaming", BASE + "/s?k=" + quote_plus("gaming deals")),
    ("cameras", BASE + "/s?k=" + quote_plus("cameras deals")),

    ("appliances", BASE + "/s?k=" + quote_plus("home appliances deals")),
    ("refrigerators", BASE + "/s?k=" + quote_plus("refrigerators deals")),
    ("washing_machines", BASE + "/s?k=" + quote_plus("washing machines deals")),
    ("air_conditioners", BASE + "/s?k=" + quote_plus("air conditioners deals")),
    ("kitchen", BASE + "/s?k=" + quote_plus("kitchen appliances deals")),
    ("small_appliances", BASE + "/s?k=" + quote_plus("small appliances deals")),

    ("home", BASE + "/s?k=" + quote_plus("home deals")),
    ("tools", BASE + "/s?k=" + quote_plus("tools deals")),
    ("beauty", BASE + "/s?k=" + quote_plus("beauty deals")),
    ("fashion", BASE + "/s?k=" + quote_plus("fashion deals")),
    ("sports", BASE + "/s?k=" + quote_plus("sports fitness deals")),
]



def _price(text) -> float:
    text = str(text or "")
    text = text.replace(",", "")

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


def _clean(text) -> str:
    return " ".join(
        str(text or "").split()
    ).strip()


PROMO_RADAR_SURFACES = (
    (
        "promo_buy_more_save_more",
        BASE + "/s?k=" + quote_plus("buy more save more"),
    ),
    (
        "promo_buy_1_get_1",
        BASE + "/s?k=" + quote_plus("buy 1 get 1"),
    ),
    (
        "promo_2_for_1",
        BASE + "/s?k=" + quote_plus("2 for 1"),
    ),
    (
        "promo_coupon",
        BASE + "/s?k=" + quote_plus("coupon discount"),
    ),
)

FAST_RADAR_SURFACES = (
    (
        "radar_70off",
        BASE + "/s?k=" + quote_plus("70% off deals"),
    ),
    (
        "radar_clearance",
        BASE + "/s?k=" + quote_plus("clearance deals"),
    ),
    (
        "radar_expensive",
        BASE + "/s?k=" + quote_plus(
            "laptop mobile refrigerator treadmill deals"
        ),
    ),
)


class AmazonSource:
    name = "amazon"

    def __init__(self):
        self.last_request_at = 0.0
        self.min_gap = 2.0

    async def _wait(self):
        wait = (
            self.last_request_at
            + self.min_gap
            - time.monotonic()
        )

        if wait > 0:
            await __import__("asyncio").sleep(wait)

        self.last_request_at = time.monotonic()

    async def fetch(self, client, url):
        await self._wait()

        r = await client.get(
            url,
            headers=HEADERS,
            timeout=20,
            follow_redirects=True,
        )

        body = r.text or ""
        low = body.lower()

        protected = (
            "captcha" in low
            or "robot check" in low
            or "enter the characters you see below" in low
        )

        if r.status_code in (403, 429):
            raise RuntimeError(
                f"amazon_http_{r.status_code}"
            )

        if protected:
            raise RuntimeError(
                "amazon_protection_page"
            )

        if r.status_code != 200:
            raise RuntimeError(
                f"amazon_http_{r.status_code}"
            )

        return body

    def parse_items(self, body, surface="amazon"):
        soup = BeautifulSoup(
            body,
            "html.parser",
        )

        results = {}
        cards = soup.select(
            '[data-component-type="s-search-result"][data-asin]'
        )

        if not cards:
            cards = soup.select(
                '[data-asin]'
            )

        for card in cards:
            asin = str(
                card.get("data-asin")
                or ""
            ).strip().upper()

            if not re.fullmatch(
                r"[A-Z0-9]{10}",
                asin,
            ):
                continue

            title_node = (
                card.select_one("h2 a span")
                or card.select_one("h2 span")
            )

            title = _clean(
                title_node.get_text(" ", strip=True)
                if title_node
                else ""
            )

            link_node = (
                card.select_one("h2 a[href]")
                or card.select_one(
                    'a[href*="/dp/"]'
                )
            )

            href = (
                str(link_node.get("href") or "")
                if link_node
                else ""
            )

            if href.startswith("/"):
                url = BASE + href.split("?")[0]
            elif href.startswith("http"):
                url = href.split("?")[0]
            else:
                url = BASE + "/dp/" + asin

            current_node = (
                card.select_one(
                    ".a-price:not(.a-text-price) .a-offscreen"
                )
                or card.select_one(
                    ".a-price .a-offscreen"
                )
            )

            current = _price(
                current_node.get_text(" ", strip=True)
                if current_node
                else ""
            )

            old_node = (
                card.select_one(
                    ".a-price.a-text-price .a-offscreen"
                )
                or card.select_one(
                    ".a-text-price .a-offscreen"
                )
            )

            old = _price(
                old_node.get_text(" ", strip=True)
                if old_node
                else ""
            )

            image_node = (
                card.select_one("img.s-image")
                or card.select_one("img[src]")
            )

            image_url = (
                str(image_node.get("src") or "")
                if image_node
                else ""
            )

            if current <= 0:
                continue

            if old <= current:
                old = None

            # Detect non-price Amazon promotions from the product card.
            card_text = card.get_text(" ", strip=True)

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
                "buy 1 get 1",
                "buy one get one",
                "buy more save more",
                "buy more & save",
                "2 for 1",
                "buy 2",
                "coupon",
                "كوبون",
            )

            promo_text = ""

            lowered_card_text = card_text.lower()

            # Price anomaly is NOT decided from category alone.
            # It must be supported by a real previous/reference price.
            price_anomaly = False
            anomaly_category = ""
            anomaly_threshold = 0.0

            if (
                old
                and old > current
                and current > 0
            ):
                price_ratio = current / old
                discount_ratio = 1.0 - price_ratio

                # Conservative anomaly rule based on a real reference price.
                # Very expensive products get a slightly wider threshold.
                if old >= 10000:
                    anomaly_ratio_limit = 0.25
                elif old >= 1000:
                    anomaly_ratio_limit = 0.20
                else:
                    anomaly_ratio_limit = 0.0

                if (
                    anomaly_ratio_limit > 0
                    and price_ratio <= anomaly_ratio_limit
                ):
                    price_anomaly = True
                    anomaly_category = "verified_price_collapse"
                    anomaly_threshold = float(
                        old * anomaly_ratio_limit
                    )

            for pattern in promo_patterns:
                if pattern.lower() in lowered_card_text:
                    promo_text = pattern
                    break

            results[asin] = DealCandidate(
                store="amazon",
                external_id=asin,
                title=title or asin,
                url=url,
                current_price=current,
                old_price=old,
                image_url=image_url,
                metadata={
                    "surface": surface,
                    "source": "amazon_direct",
                    "promo_text": promo_text,
                    "price_anomaly": price_anomaly,
                    "anomaly_category": anomaly_category,
                    "anomaly_threshold": anomaly_threshold,
                },
            )

        return list(results.values())

    async def scan_surface(
        self,
        client,
        name,
        url,
    ):
        body = await self.fetch(
            client,
            url,
        )

        return self.parse_items(
            body,
            surface=name,
        )

    async def scan_fast_radar_once(self):
        """
        Small high-frequency Amazon scan.
        Only returns extreme discounts and price anomalies.
        """
        found = {}

        async with httpx.AsyncClient() as client:
            for name, url in (
                *FAST_RADAR_SURFACES,
                *PROMO_RADAR_SURFACES,
            ):
                try:
                    items = await self.scan_surface(
                        client,
                        name,
                        url,
                    )
                except Exception as exc:
                    print(
                        "⚠️ AMAZON FAST RADAR SKIPPED",
                        name,
                        repr(exc),
                        flush=True,
                    )
                    continue

                for deal in items:
                    meta = deal.metadata or {}

                    if (
                        bool(meta.get("price_anomaly"))
                        or bool(str(meta.get("promo_text") or "").strip())
                        or deal.discount_percent >= 70
                    ):
                        found[deal.fingerprint] = deal

        return list(found.values())


    async def scan_once(self):
        found = {}

        # Deep discovery: inspect multiple result pages for each surface.
        # Keep the first page as the primary source, then add page 2.
        expanded = []

        for name, url in PRIORITY_SURFACES:
            expanded.append((name, url))

            if "/s?" in url:
                separator = "&" if "?" in url else "?"
                expanded.append(
                    (
                        f"{name}_page2",
                        f"{url}{separator}page=2",
                    )
                )

        async with httpx.AsyncClient() as client:
            for name, url in expanded:
                try:
                    items = await self.scan_surface(
                        client,
                        name,
                        url,
                    )
                except Exception as exc:
                    print(
                        "⚠️ AMAZON SURFACE SKIPPED",
                        name,
                        repr(exc),
                        flush=True,
                    )
                    continue

                for deal in items:
                    found[deal.fingerprint] = deal

        return list(found.values())
