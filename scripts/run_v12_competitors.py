#!/usr/bin/env python3

import asyncio
import os
import time

# Competitor worker must use completely separate state from Amazon.
os.environ.setdefault(
    "V12_DB_PATH",
    ".runtime_state/competitors_v12.db",
)
os.environ.setdefault(
    "V12_SEEN_LEDGER",
    ".runtime_state/competitors_seen_ledger.json",
)

from deals_v12.review import TelegramReviewer
from deals_v12.store_capture import capture
from deals_v12.sources.btech import BtechConnector
from deals_v12.sources.two_b import TwoBConnector
from deals_v12.queue import DealQueue


UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 Chrome/140 Safari/537.36"
)

SCAN_INTERVAL = int(
    os.getenv("V12_COMPETITOR_SCAN_INTERVAL", "90")
)


async def process_store(store, source, reviewer, queue):
    print(f"🔎 {store.upper()} scan started", flush=True)

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
        f"📦 {store.upper()} candidates={len(candidates)}",
        flush=True,
    )

    unseen = [
        deal for deal in candidates
        if not queue.was_seen_exact(deal)
    ]

    print(
        f"🆕 {store.upper()} unseen={len(unseen)}",
        flush=True,
    )

    for deal in unseen[:5]:

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
                f"⚠️ {store.upper()} capture skipped",
                deal.external_id,
                result.get("reason"),
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

        try:
            message = await reviewer.send_review(deal)

            queue.remember_seen_exact(deal)

            print(
                f"✅ {store.upper()} review sent",
                deal.external_id,
                "message_id=",
                message.get("message_id"),
                flush=True,
            )

        except Exception as exc:
            print(
                f"❌ {store.upper()} send failed",
                deal.external_id,
                repr(exc),
                flush=True,
            )


async def main():
    os.environ["TELEGRAM_BOT_TOKEN"] = os.environ[
        "COMPETITOR_TELEGRAM_BOT_TOKEN"
    ]

    os.environ["REVIEW_CHAT_ID"] = os.environ[
        "COMPETITOR_REVIEW_CHAT_ID"
    ]

    reviewer = TelegramReviewer()
    queue = DealQueue()

    btech = BtechConnector(
        timeout=25,
        user_agent=UA,
    )

    two_b = TwoBConnector(
        timeout=25,
        user_agent=UA,
    )

    print(
        "🚀 V12 COMPETITORS REALTIME STARTED",
        flush=True,
    )

    while True:
        started = time.time()

        try:
            await process_store(
                "btech",
                btech,
                reviewer,
                queue,
            )
        except Exception as exc:
            print(
                "❌ BTECH scan failed",
                repr(exc),
                flush=True,
            )

        try:
            await process_store(
                "2b",
                two_b,
                reviewer,
                queue,
            )
        except Exception as exc:
            print(
                "❌ 2B scan failed",
                repr(exc),
                flush=True,
            )

        elapsed = time.time() - started
        sleep_for = max(
            5,
            SCAN_INTERVAL - int(elapsed),
        )

        print(
            f"⏳ next competitor scan in {sleep_for}s",
            flush=True,
        )

        await asyncio.sleep(sleep_for)


if __name__ == "__main__":
    asyncio.run(main())
