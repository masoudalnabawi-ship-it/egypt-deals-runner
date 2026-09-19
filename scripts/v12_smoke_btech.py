#!/usr/bin/env python3

import asyncio

from deals_v12.sources.btech import BtechConnector
from deals_v12.store_capture import capture
from deals_v12.review import TelegramReviewer


async def main():
    source = BtechConnector(
        timeout=25,
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 Chrome/140 Safari/537.36"
        ),
    )

    reviewer = TelegramReviewer()

    print("🔎 V12 BTECH DISCOVERY", flush=True)

    deals = await source.fetch_deals()

    deals = [
        d for d in deals
        if d.old_price
        and d.old_price > d.current_price
        and d.discount_percent >= 5
    ]

    deals.sort(
        key=lambda d: d.discount_percent,
        reverse=True,
    )

    print("📦 BTECH CANDIDATES =", len(deals), flush=True)

    for deal in deals[:6]:
        print(
            "📸 BTECH REAL PAGE CAPTURE",
            deal.external_id,
            flush=True,
        )

        result = await asyncio.to_thread(
            capture,
            "btech",
            deal.url,
            deal.external_id,
            deal.image_url or "",
        )

        if not result.get("ok"):
            print(
                "⚠️ CAPTURE FAILED",
                result.get("reason"),
                flush=True,
            )
            continue

        if result.get("source") != "store_page":
            print(
                "⚠️ NOT REAL STORE SCREENSHOT",
                result.get("source"),
                flush=True,
            )
            continue

        screenshot = str(
            result.get("screenshot") or ""
        ).strip()

        if not screenshot:
            continue

        deal.metadata["review_media_path"] = screenshot
        deal.metadata["review_media_source"] = "btech_real_page"

        message = await reviewer.send_review(deal)

        print(
            "✅ V12 BTECH SCREENSHOT SENT",
            "| PRODUCT =", deal.external_id,
            "| MESSAGE_ID =", message.get("message_id"),
            flush=True,
        )
        return

    raise RuntimeError(
        "No BTECH product produced a real page screenshot"
    )


if __name__ == "__main__":
    asyncio.run(main())
