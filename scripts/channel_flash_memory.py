#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime, timezone
import json
import re

from playwright.sync_api import sync_playwright
from channel_link_resolver import resolve_one

ROOT = Path(__file__).resolve().parents[1]

STATE_DIR = ROOT / ".runtime_state"
NEW_FILE = STATE_DIR / "channel_new_posts.json"
MEMORY_FILE = STATE_DIR / "channel_flash_memory.json"
PENDING_FILE = STATE_DIR / "channel_amazon_pending.json"

RADAR_WATCH = (
    STATE_DIR / "amazon_radar_watch.json"
)

STATE_MANUAL = (
    STATE_DIR / "amazon_manual_watch.txt"
)

LIVE_MANUAL = (
    ROOT
    / "amazon_dynamic_runtime_v8"
    / "telegram_deals_bot_v1_ready"
    / ".amazon_manual_watch.txt"
)


def load_json(path, default):
    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return default


def num(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def explicit_old_price(text, current):
    text = str(text or "")

    pats = [
        r"(?:بدلًا من|بدلا من|بدل)\s*([\d,]+(?:\.\d+)?)",
        r"(?:كان|السعر القديم)\s*([\d,]+(?:\.\d+)?)",
    ]

    vals = []

    for pat in pats:
        for m in re.findall(
            pat,
            text,
            flags=re.I,
        ):
            try:
                v = float(
                    str(m).replace(",", "")
                )

                if v > current:
                    vals.append(v)
            except Exception:
                pass

    return max(vals) if vals else 0.0


def radar_reference(rec):
    if not isinstance(rec, dict):
        return 0.0, ""

    anchor = max(
        num(rec.get("stable_anchor")),
        num(rec.get("intel_anchor_price")),
    )

    hits = max(
        int(
            rec.get(
                "stable_anchor_hits",
                0
            ) or 0
        ),
        int(
            rec.get(
                "intel_anchor_hits",
                0
            ) or 0
        ),
    )

    if anchor > 0 and hits >= 2:
        return anchor, "stable_anchor"

    samples = (
        rec.get("price_intel_samples")
        or rec.get("price_samples")
        or []
    )

    prices = []

    for x in samples:
        try:
            if isinstance(x, dict):
                p = num(
                    x.get("p")
                    or x.get("price")
                )
            else:
                p = num(x)

            if p > 0:
                prices.append(p)
        except Exception:
            pass

    if len(prices) >= 3:
        prices = sorted(prices)
        mid = len(prices) // 2

        if len(prices) % 2:
            ref = prices[mid]
        else:
            ref = (
                prices[mid - 1]
                + prices[mid]
            ) / 2

        return ref, "observed_history"

    return 0.0, ""


def add_manual_asin(asin):
    asin = asin.strip().upper()

    for path in (
        STATE_MANUAL,
        LIVE_MANUAL,
    ):
        path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        existing = []

        if path.exists():
            existing = [
                x.strip()
                for x in path.read_text(
                    encoding="utf-8"
                ).splitlines()
                if x.strip()
            ]

        if asin not in {
            x.upper()
            for x in existing
        }:
            existing.append(asin)

            path.write_text(
                "\n".join(existing) + "\n",
                encoding="utf-8",
            )


def main():
    posts = load_json(
        NEW_FILE,
        [],
    )

    radar = load_json(
        RADAR_WATCH,
        {},
    )

    memory = load_json(
        MEMORY_FILE,
        {
            "products": {},
            "events": [],
        },
    )

    pending = load_json(
        PENDING_FILE,
        [],
    )

    if not isinstance(pending, list):
        pending = []

    pending_by_asin = {}

    for item in pending:
        if not isinstance(item, dict):
            continue

        key = str(
            item.get("asin") or ""
        ).strip().upper()

        if key:
            pending_by_asin[key] = item

    print(
        f"📡 FLASH INPUT POSTS = {len(posts)}"
    )

    if not posts:
        MEMORY_FILE.write_text(
            json.dumps(
                memory,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print("✅ NOTHING NEW TO ANALYZE")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox"],
        )

        for post in posts:
            current = num(
                post.get("price")
            )

            if current <= 0:
                continue

            links = (
                post.get("links")
                or []
            )

            amazon_result = None

            for link in links[:4]:
                result = resolve_one(
                    link,
                    browser,
                )

                if (
                    result.get("store")
                    == "amazon"
                    and result.get("asin")
                ):
                    amazon_result = result
                    break

            if not amazon_result:
                continue

            asin = (
                amazon_result["asin"]
                .upper()
            )

            # Every NEW competitor Amazon product gets
            # exact Amazon verification in the scanner.
            # Competitor price/discount is ONLY a hint.
            pending_by_asin[asin] = {
                "asin": asin,
                "channel": post.get("channel"),
                "post": post.get("post"),
                "channel_time": post.get("time"),
                "channel_price_hint": current,
                "final_url": amazon_result.get(
                    "final_url"
                ),
                "queued_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "attempts": 0,
            }

            print(
                "🎯 COMPETITOR AMAZON PENDING"
                f" | {asin}"
                f" | channel={post.get('channel')}"
                f" | hint={current:.2f}"
            )

            rec = radar.get(
                asin,
                {},
            )

            radar_ref, radar_source = (
                radar_reference(rec)
            )

            old_ref = explicit_old_price(
                post.get("text"),
                current,
            )

            reference = 0.0
            source = ""

            if radar_ref > 0:
                reference = radar_ref
                source = radar_source

            if old_ref > reference:
                reference = old_ref
                source = "channel_explicit_old_price"

            drop = 0.0

            if reference > current:
                drop = (
                    reference - current
                ) / reference * 100.0

            # Flash threshold:
            # >=80% below a real/explicit reference.
            flash = (
                reference > 0
                and drop >= 80
            )

            event = {
                "asin": asin,
                "channel":
                    post.get("channel"),
                "post":
                    post.get("post"),
                "channel_time":
                    post.get("time"),
                "observed_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),
                "price": current,
                "reference": round(
                    reference,
                    2,
                ),
                "drop": round(
                    drop,
                    1,
                ),
                "reference_source":
                    source,
                "flash": flash,
                "original_url":
                    amazon_result.get(
                        "original_url"
                    ),
                "final_url":
                    amazon_result.get(
                        "final_url"
                    ),
            }

            memory.setdefault(
                "events",
                []
            ).append(event)

            prod = memory.setdefault(
                "products",
                {}
            ).setdefault(
                asin,
                {
                    "first_seen_channel":
                        post.get("time"),
                    "flash_hits": 0,
                }
            )

            prod["last_channel"] = (
                post.get("channel")
            )
            prod["last_channel_time"] = (
                post.get("time")
            )
            prod["last_channel_price"] = (
                current
            )

            if flash:
                prod["flash_hits"] = (
                    int(
                        prod.get(
                            "flash_hits",
                            0
                        )
                    )
                    + 1
                )

                prod["last_flash_price"] = (
                    current
                )

                prod["last_reference"] = (
                    reference
                )

                prod["last_drop"] = (
                    round(drop, 1)
                )

                add_manual_asin(asin)

                print(
                    "🚨 FLASH MEMORY"
                    f" | {asin}"
                    f" | {current:.2f}"
                    f" vs {reference:.2f}"
                    f" | drop={drop:.1f}%"
                    f" | {post.get('channel')}"
                )

            else:
                print(
                    "📊 BENCHMARK AMAZON"
                    f" | {asin}"
                    f" | price={current:.2f}"
                    f" | ref={reference:.2f}"
                    f" | drop={drop:.1f}%"
                )

        browser.close()

    memory["events"] = (
        memory.get(
            "events",
            []
        )[-2000:]
    )

    memory["updated_at"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    MEMORY_FILE.write_text(
        json.dumps(
            memory,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    pending_out = list(
        pending_by_asin.values()
    )[-100:]

    PENDING_FILE.write_text(
        json.dumps(
            pending_out,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "🎯 AMAZON COMPETITOR PENDING =",
        len(pending_out)
    )

    print(
        "✅ FLASH MEMORY UPDATED"
        f" | products="
        f"{len(memory.get('products', {}))}"
    )


if __name__ == "__main__":
    main()
