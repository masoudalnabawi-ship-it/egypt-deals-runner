from __future__ import annotations

import re
import time
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from ..models import DealCandidate
from ..state import connect


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


CATEGORY_EXPANSION_SURFACES = (
    ("fashion_clothing", BASE + "/s?k=" + quote_plus("clothing fashion deals")),
    ("fashion_shoes", BASE + "/s?k=" + quote_plus("shoes footwear deals")),
    ("fashion_bags", BASE + "/s?k=" + quote_plus("bags handbags deals")),
    ("fashion_men", BASE + "/s?k=" + quote_plus("men mens fashion deals")),
    ("fashion_women", BASE + "/s?k=" + quote_plus("women womens fashion deals")),
    ("fashion_kids", BASE + "/s?k=" + quote_plus("kids children clothing deals")),

    ("grocery", BASE + "/s?k=" + quote_plus("grocery food deals")),
    ("supermarket", BASE + "/s?k=" + quote_plus("supermarket grocery deals")),
    ("food", BASE + "/s?k=" + quote_plus("food pantry deals")),
    ("snacks", BASE + "/s?k=" + quote_plus("snacks biscuits chocolate deals")),
    ("beverages", BASE + "/s?k=" + quote_plus("beverages drinks deals")),
    ("coffee_tea", BASE + "/s?k=" + quote_plus("coffee tea deals")),
)

DEPARTMENT_EXPANSION_SURFACES = (
    # Fashion
    ("dept_tshirts", BASE + "/s?k=" + quote_plus("t shirts clothing deals")),
    ("dept_shirts", BASE + "/s?k=" + quote_plus("shirts clothing deals")),
    ("dept_jeans", BASE + "/s?k=" + quote_plus("jeans denim deals")),
    ("dept_pants", BASE + "/s?k=" + quote_plus("pants trousers deals")),
    ("dept_dresses", BASE + "/s?k=" + quote_plus("dresses women fashion deals")),
    ("dept_sneakers", BASE + "/s?k=" + quote_plus("sneakers shoes deals")),
    ("dept_shoes", BASE + "/s?k=" + quote_plus("shoes footwear deals")),
    ("dept_bags", BASE + "/s?k=" + quote_plus("bags handbags deals")),
    ("dept_watches", BASE + "/s?k=" + quote_plus("watches deals")),
    ("dept_kids_clothing", BASE + "/s?k=" + quote_plus("kids clothing deals")),

    # Grocery / supermarket
    ("dept_rice", BASE + "/s?k=" + quote_plus("rice grocery deals")),
    ("dept_pasta", BASE + "/s?k=" + quote_plus("pasta grocery deals")),
    ("dept_oil", BASE + "/s?k=" + quote_plus("cooking oil grocery deals")),
    ("dept_canned", BASE + "/s?k=" + quote_plus("canned food grocery deals")),
    ("dept_chocolate", BASE + "/s?k=" + quote_plus("chocolate sweets deals")),
    ("dept_biscuits", BASE + "/s?k=" + quote_plus("biscuits cookies deals")),
    ("dept_coffee", BASE + "/s?k=" + quote_plus("coffee deals")),
    ("dept_tea", BASE + "/s?k=" + quote_plus("tea deals")),
    ("dept_juice", BASE + "/s?k=" + quote_plus("juice drinks deals")),
    ("dept_water", BASE + "/s?k=" + quote_plus("water beverages deals")),
    ("dept_detergent", BASE + "/s?k=" + quote_plus("detergent cleaning products deals")),
)

DEPARTMENT_ROTATION_GROUPS = (
    (
        "fashion_clothing_deep",
        (
            DEPARTMENT_EXPANSION_SURFACES[0],
            DEPARTMENT_EXPANSION_SURFACES[1],
            DEPARTMENT_EXPANSION_SURFACES[2],
        ),
    ),
    (
        "fashion_bottoms",
        (
            DEPARTMENT_EXPANSION_SURFACES[3],
            DEPARTMENT_EXPANSION_SURFACES[4],
            DEPARTMENT_EXPANSION_SURFACES[5],
        ),
    ),
    (
        "fashion_accessories",
        (
            DEPARTMENT_EXPANSION_SURFACES[6],
            DEPARTMENT_EXPANSION_SURFACES[7],
            DEPARTMENT_EXPANSION_SURFACES[8],
        ),
    ),
    (
        "fashion_kids",
        (
            DEPARTMENT_EXPANSION_SURFACES[9],
            DEPARTMENT_EXPANSION_SURFACES[10],
            DEPARTMENT_EXPANSION_SURFACES[11],
        ),
    ),
    (
        "grocery_basics",
        (
            DEPARTMENT_EXPANSION_SURFACES[12],
            DEPARTMENT_EXPANSION_SURFACES[13],
            DEPARTMENT_EXPANSION_SURFACES[14],
        ),
    ),
    (
        "grocery_pantry",
        (
            DEPARTMENT_EXPANSION_SURFACES[15],
            DEPARTMENT_EXPANSION_SURFACES[16],
            DEPARTMENT_EXPANSION_SURFACES[17],
        ),
    ),
    (
        "grocery_drinks",
        (
            DEPARTMENT_EXPANSION_SURFACES[18],
            DEPARTMENT_EXPANSION_SURFACES[19],
            DEPARTMENT_EXPANSION_SURFACES[20],
        ),
    ),
)

CATEGORY_ROTATION_GROUPS = (
    (
        "fashion_core",
        (
            CATEGORY_EXPANSION_SURFACES[0],
            CATEGORY_EXPANSION_SURFACES[1],
            CATEGORY_EXPANSION_SURFACES[2],
        ),
    ),
    (
        "fashion_segments",
        (
            CATEGORY_EXPANSION_SURFACES[3],
            CATEGORY_EXPANSION_SURFACES[4],
            CATEGORY_EXPANSION_SURFACES[5],
        ),
    ),
    (
        "grocery_core",
        (
            CATEGORY_EXPANSION_SURFACES[6],
            CATEGORY_EXPANSION_SURFACES[7],
            CATEGORY_EXPANSION_SURFACES[8],
        ),
    ),
    (
        "grocery_segments",
        (
            CATEGORY_EXPANSION_SURFACES[9],
            CATEGORY_EXPANSION_SURFACES[10],
            CATEGORY_EXPANSION_SURFACES[11],
        ),
    ),
)


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

ULTRA_PERCENTAGE_RADAR = (
    (
        "radar_90off",
        BASE + "/s?k=" + quote_plus("90% off deals"),
    ),
    (
        "radar_80off",
        BASE + "/s?k=" + quote_plus("80% off deals"),
    ),
    (
        "radar_70off",
        BASE + "/s?k=" + quote_plus("70% off deals"),
    ),
    (
        "radar_60off",
        BASE + "/s?k=" + quote_plus("60% off deals"),
    ),
    (
        "radar_50off",
        BASE + "/s?k=" + quote_plus("50% off deals"),
    ),
)

FAST_RADAR_SURFACES = (
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

RADAR_ROTATION_GROUPS = (
    (
        "promo_primary",
        (
            PROMO_RADAR_SURFACES[0],
            PROMO_RADAR_SURFACES[1],
        ),
    ),
    (
        "promo_secondary",
        (
            PROMO_RADAR_SURFACES[2],
            PROMO_RADAR_SURFACES[3],
        ),
    ),
    (
        "extra_value",
        (
            FAST_RADAR_SURFACES[0],
            FAST_RADAR_SURFACES[1],
        ),
    ),
)


class AmazonSource:
    name = "amazon"

    def __init__(self):
        self.last_request_at = 0.0
        self.min_gap = 2.0
        self._radar_rotation = 0
        self._category_rotation = 0
        self._department_rotation = 0

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
                "coupon available",
                "clip coupon",
                "extra discount",
                "additional discount",
                "كوبون",
                "كوبون خصم",
                "استخدم الكوبون",
                "احصل على خصم",
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

            promo_text = ""
            flash_text = ""

            lowered_card_text = card_text.lower()

            for pattern in flash_patterns:
                if pattern.lower() in lowered_card_text:
                    flash_text = pattern
                    break

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
                    "flash_deal": bool(flash_text),
                    "flash_text": flash_text,
                    "price_anomaly": price_anomaly,
                    "anomaly_category": anomaly_category,
                    "anomaly_threshold": anomaly_threshold,
                },
            )

        return list(results.values())

    def _record_surface_stats(
        self,
        surface,
        fetched,
        candidates,
        ultra_hits,
        latency_ms,
    ):
        try:
            with connect() as con:
                con.execute(
                    """
                    INSERT INTO surface_stats(
                        store,
                        surface,
                        scans,
                        fetched,
                        candidates,
                        ultra_hits,
                        last_scan_at,
                        last_latency_ms
                    )
                    VALUES(
                        'amazon',
                        ?,
                        1,
                        ?,
                        ?,
                        ?,
                        CAST(strftime('%s','now') AS INTEGER),
                        ?
                    )
                    ON CONFLICT(store, surface)
                    DO UPDATE SET
                        scans = scans + 1,
                        fetched = fetched + excluded.fetched,
                        candidates = candidates + excluded.candidates,
                        ultra_hits = ultra_hits + excluded.ultra_hits,
                        last_scan_at = excluded.last_scan_at,
                        last_latency_ms = excluded.last_latency_ms
                    """,
                    (
                        surface,
                        int(fetched),
                        int(candidates),
                        int(ultra_hits),
                        int(latency_ms),
                    ),
                )
                con.commit()
        except Exception:
            # Metrics must never break deal discovery.
            pass

    def _apply_historical_anomaly(self, items):
        """
        Detect severe price collapses even when Amazon's current
        search card does not expose an old/reference price.
        """
        if not items:
            return items

        try:
            with connect() as con:
                for deal in items:
                    rows = con.execute(
                        """
                        SELECT current_price, old_price
                        FROM price_history
                        WHERE fingerprint=?
                        ORDER BY seen_at DESC
                        LIMIT 30
                        """,
                        (deal.fingerprint,),
                    ).fetchall()

                    historical_prices = []

                    for row in rows:
                        current_seen = float(
                            row["current_price"] or 0
                        )
                        old_seen = float(
                            row["old_price"] or 0
                        )

                        if current_seen > 0:
                            historical_prices.append(
                                current_seen
                            )

                        if old_seen > 0:
                            historical_prices.append(
                                old_seen
                            )

                    previous_price = (
                        max(historical_prices)
                        if historical_prices
                        else 0.0
                    )

                    meta = deal.metadata or {}

                    historical_anomaly = False
                    anomaly_threshold = float(
                        meta.get("anomaly_threshold")
                        or 0
                    )

                    if (
                        previous_price >= 1000
                        and deal.current_price > 0
                    ):
                        ratio = (
                            deal.current_price
                            / previous_price
                        )

                        # Critical historical collapse:
                        # current price <= 20% of the previous observed price.
                        if ratio <= 0.20:
                            historical_anomaly = True
                            anomaly_threshold = (
                                previous_price * 0.20
                            )

                    if historical_anomaly:
                        meta["price_anomaly"] = True
                        meta["anomaly_category"] = (
                            "historical_price_collapse"
                        )
                        meta["anomaly_threshold"] = float(
                            anomaly_threshold
                        )
                        meta["historical_reference_price"] = (
                            float(previous_price)
                        )
                        meta["anomaly_source"] = (
                            "price_history"
                        )

                    deal.metadata = meta

                    latest = con.execute(
                        """
                        SELECT current_price, old_price
                        FROM price_history
                        WHERE fingerprint=?
                        ORDER BY seen_at DESC
                        LIMIT 1
                        """,
                        (deal.fingerprint,),
                    ).fetchone()

                    current_value = float(
                        deal.current_price or 0
                    )

                    old_value = (
                        float(deal.old_price)
                        if deal.old_price is not None
                        else 0.0
                    )

                    latest_current = (
                        float(latest["current_price"] or 0)
                        if latest
                        else -1.0
                    )

                    latest_old = (
                        float(latest["old_price"] or 0)
                        if latest
                        else -1.0
                    )

                    if (
                        not latest
                        or current_value != latest_current
                        or old_value != latest_old
                    ):
                        con.execute(
                            """
                            INSERT INTO price_history(
                                fingerprint,
                                store,
                                current_price,
                                old_price,
                                seen_at
                            )
                            VALUES(?,?,?,?,?)
                            """,
                            (
                                deal.fingerprint,
                                deal.store.lower(),
                                current_value,
                                (
                                    old_value
                                    if old_value > 0
                                    else None
                                ),
                                int(time.time()),
                            ),
                        )

                con.commit()

        except Exception:
            # Historical intelligence must never break discovery.
            pass

        return items

    async def scan_surface(
        self,
        client,
        name,
        url,
    ):
        started = time.monotonic()

        body = await self.fetch(
            client,
            url,
        )

        items = self.parse_items(
            body,
            surface=name,
        )

        items = self._apply_historical_anomaly(
            items
        )

        candidates = [
            deal
            for deal in items
            if (
                (
                    deal.old_price
                    and deal.old_price > deal.current_price
                    and deal.discount_percent >= 5
                )
                or bool(
                    (deal.metadata or {}).get("promo_text")
                )
                or bool(
                    (deal.metadata or {}).get("price_anomaly")
                )
            )
        ]

        ultra_hits = [
            deal
            for deal in items
            if (
                bool(
                    (deal.metadata or {}).get("price_anomaly")
                )
                or deal.discount_percent >= 70
            )
        ]

        self._record_surface_stats(
            name,
            fetched=len(items),
            candidates=len(candidates),
            ultra_hits=len(ultra_hits),
            latency_ms=int(
                (time.monotonic() - started) * 1000
            ),
        )

        return items

    def _smart_radar_order(self, surfaces):
        """
        Reorder radar surfaces using historical productivity.
        Every surface remains enabled; productive surfaces simply
        get scanned earlier so strong deals reach the queue sooner.
        """
        try:
            with connect() as con:
                rows = con.execute(
                    """
                    SELECT
                        surface,
                        scans,
                        candidates,
                        ultra_hits,
                        last_latency_ms
                    FROM surface_stats
                    WHERE store='amazon'
                    """
                ).fetchall()

            stats = {
                str(row["surface"]): {
                    "scans": int(row["scans"] or 0),
                    "candidates": int(
                        row["candidates"] or 0
                    ),
                    "ultra_hits": int(
                        row["ultra_hits"] or 0
                    ),
                    "latency": int(
                        row["last_latency_ms"] or 0
                    ),
                }
                for row in rows
            }

        except Exception:
            stats = {}

        def base_priority(name):
            name = str(name)

            # Explicit radar strength always dominates historical
            # productivity so a 90% radar can never fall behind 50%.
            if "90off" in name:
                return 600
            if "80off" in name:
                return 500
            if "70off" in name:
                return 400
            if "60off" in name:
                return 300
            if "50off" in name:
                return 200

            if name.startswith("promo_"):
                return 100

            return 50

        def score(item):
            name, _url = item
            data = stats.get(name)

            priority = base_priority(name)

            if not data:
                return (priority, 0, 0, 0)

            scans = max(data["scans"], 1)

            ultra_rate = (
                data["ultra_hits"] / scans
            )

            candidate_rate = (
                data["candidates"] / scans
            )

            return (
                priority,
                round(ultra_rate, 4),
                round(candidate_rate, 4),
                data["candidates"],
            )

        return sorted(
            surfaces,
            key=score,
            reverse=True,
        )

    async def scan_fast_radar_once(self):
        """
        Smart high-frequency Amazon radar.
        All radar surfaces remain enabled, but historically
        productive surfaces are scanned first.
        """
        found = {}

        # Core ultra bands run every radar cycle.
        # All 50%+ percentage bands are always scanned.
        # This guarantees that lower ultra bands are never starved
        # by category or promotional discovery.
        core = (
            ULTRA_PERCENTAGE_RADAR[0],
            ULTRA_PERCENTAGE_RADAR[1],
            ULTRA_PERCENTAGE_RADAR[2],
            ULTRA_PERCENTAGE_RADAR[3],
            ULTRA_PERCENTAGE_RADAR[4],
        )

        # Rotate the lower bands and promo searches so we keep broad
        # coverage without repeatedly requesting every radar surface.
        rotation_index = int(
            getattr(self, "_radar_rotation", 0)
        ) % len(RADAR_ROTATION_GROUPS)

        rotation_name, rotation_group = RADAR_ROTATION_GROUPS[
            rotation_index
        ]

        self._radar_rotation = rotation_index + 1

        print(
            "🔄 AMAZON RADAR ROTATION",
            rotation_name,
            flush=True,
        )

        radar_surfaces = self._smart_radar_order(
            (
                *core,
                *rotation_group,
            )
        )

        async with httpx.AsyncClient() as client:
            for name, url in radar_surfaces:
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

                    surface = str(
                        meta.get("surface") or ""
                    )

                    is_ultra_percentage_surface = surface.startswith(
                        "radar_"
                    )

                    if (
                        bool(meta.get("price_anomaly"))
                        or bool(
                            str(
                                meta.get("promo_text") or ""
                            ).strip()
                        )
                        or deal.discount_percent >= 70
                        or (
                            is_ultra_percentage_surface
                            and deal.discount_percent >= 50
                        )
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

        category_index = (
            int(getattr(self, "_category_rotation", 0))
            % len(CATEGORY_ROTATION_GROUPS)
        )

        category_name, category_group = CATEGORY_ROTATION_GROUPS[
            category_index
        ]

        self._category_rotation = category_index + 1

        print(
            "🛍️ AMAZON CATEGORY ROTATION",
            category_name,
            flush=True,
        )

        # Category expansion is deliberately rotated so it improves
        # vertical coverage without multiplying every normal scan.
        for name, url in category_group:
            expanded.append((name, url))

        department_index = (
            int(getattr(self, "_department_rotation", 0))
            % len(DEPARTMENT_ROTATION_GROUPS)
        )

        department_name, department_group = DEPARTMENT_ROTATION_GROUPS[
            department_index
        ]

        self._department_rotation = department_index + 1

        print(
            "🧩 AMAZON DEPARTMENT ROTATION",
            department_name,
            flush=True,
        )

        # Deep department discovery is also rotated. This adds
        # only three specialized queries per normal scan.
        for name, url in department_group:
            expanded.append((name, url))

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
