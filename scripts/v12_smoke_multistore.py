#!/usr/bin/env python3

import asyncio

from deals_v12.review import TelegramReviewer
from deals_v12.store_capture import capture
from deals_v12.sources.noon import NoonConnector
from deals_v12.sources.two_b import TwoBConnector


UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 Chrome/140 Safari/537.36"
)


async def test_store(store, source, reviewer):
    print(f"🔎 V12 {store.upper()} DISCOVERY", flush=True)

    deals = await source.fetch_deals()

    candidates = [
        d for d in deals
        if d.old_price
        and d.old_price > d.current_price
        and d.discount_percent >= 5
    ]

    candidates.sort(
        key=lambda d: d.discount_percent,
        reverse=True,
    )

    print(
        f"📦 {store.upper()} CANDIDATES = {len(candidates)}",
        flush=True,
    )

    for deal in candidates[:8]:
        print(
            f"📸 {store.upper()} REAL PAGE CAPTURE",
            deal.external_id,
            flush=True,
        )

        result = await asyncio.to_thread(
            capture,
            store,
            deal.url,
            deal.external_id,
            deal.image_url or "",
        )

        if (
            not result.get("ok")
            or result.get("source") != "store_page"
        ):
            print(
                "⚠️ CAPTURE SKIPPED",
                result.get("reason"),
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
        deal.metadata["review_media_source"] = (
            f"{store}_real_page"
        )

        message = await reviewer.send_review(deal)

        print(
            f"✅ {store.upper()} REAL SCREENSHOT SENT",
            "| MESSAGE_ID =",
            message.get("message_id"),
            flush=True,
        )

        return True

    return False


async def main():
    reviewer = TelegramReviewer()

    noon = NoonConnector(
        timeout=25,
        user_agent=UA,
    )

    twob = TwoBConnector(
        timeout=25,
        user_agent=UA,
    )

    noon_ok = await test_store(
        "noon",
        noon,
        reviewer,
    )

    twob_ok = await test_store(
        "2b",
        twob,
        reviewer,
    )

    if not noon_ok or not twob_ok:
        raise RuntimeError(
            f"multistore smoke incomplete: "
            f"noon={noon_ok} 2b={twob_ok}"
        )


if __name__ == "__main__":
    asyncio.run(main())
