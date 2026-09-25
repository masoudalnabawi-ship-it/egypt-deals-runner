#!/usr/bin/env python3

import asyncio
from concurrent.futures import ThreadPoolExecutor
import signal
import json
import os
import time

from deals_v12.amazon_capture import capture_amazon_page
from deals_v12.models import DealCandidate
from deals_v12.orchestrator import V12Orchestrator
from deals_v12.review import TelegramReviewer


ULTRA_RADAR_INTERVAL = int(
    os.getenv("V12_AMAZON_ULTRA_INTERVAL", "5")
)

RADAR_INTERVAL = int(
    os.getenv("V12_AMAZON_RADAR_INTERVAL", "25")
)

SCAN_INTERVAL = int(
    os.getenv("V12_AMAZON_SCAN_INTERVAL", "120")
)

LOOP_INTERVAL = int(
    os.getenv("V12_LOOP_INTERVAL", "15")
)

VERIFY_LIMIT = int(
    os.getenv("V12_VERIFY_LIMIT", "8")
)

REVIEW_LIMIT = int(
    os.getenv("V12_REVIEW_LIMIT", "5")
)


def row_to_deal(row):
    data = json.loads(row["payload"])

    return DealCandidate(
        store=data["store"],
        external_id=data["external_id"],
        title=data["title"],
        url=data["url"],
        current_price=float(data["current_price"]),
        old_price=(
            float(data["old_price"])
            if data.get("old_price") is not None
            else None
        ),
        image_url=data.get("image_url") or "",
        discovered_at=int(
            data.get("discovered_at") or 0
        ),
        metadata=data.get("metadata") or {},
    )


async def send_verified_reviews(
    core,
    reviewer,
    *,
    use_lock=True,
    ultra_only=False,
):
    if use_lock:
        async with REVIEW_LOCK:
            return await send_verified_reviews(
                core,
                reviewer,
                use_lock=False,
                ultra_only=ultra_only,
            )
    ultra_limit = max(
        1,
        min(
            REVIEW_LIMIT,
            4,
        ),
    )

    if ultra_only:
        rows = core.queue.get_ultra_verified(
            limit=ultra_limit
        )
    else:
        rows = core.queue.get_normal_verified(
            limit=REVIEW_LIMIT
        )

    sent = 0
    retried = 0

    for row in rows:
        fp = row["fingerprint"]

        try:
            deal = row_to_deal(row)

            print(
                "📸 V12 AMAZON CAPTURE",
                deal.external_id,
                f"{deal.discount_percent:.1f}%",
                flush=True,
            )

            loop = asyncio.get_running_loop()
            capture = await loop.run_in_executor(
                CAPTURE_EXECUTOR,
                capture_amazon_page,
                deal.url,
                deal.external_id or "product",
            )

            if not capture.get("ok"):
                raise RuntimeError(
                    "amazon_screenshot_failed: "
                    + str(
                        capture.get("reason")
                        or capture
                    )
                )

            screenshot = str(
                capture.get("screenshot") or ""
            ).strip()

            if not screenshot:
                raise RuntimeError(
                    "amazon_screenshot_missing"
                )

            deal.metadata["review_media_path"] = screenshot
            deal.metadata["review_media_source"] = (
                "amazon_page_screenshot"
            )

            message = await reviewer.send_review(
                deal
            )

            # Persist exact store/product/price immediately after
            # Telegram confirms the review message was sent.
            core.queue.remember_seen_exact(deal)

            core.queue.mark_reviewed(
                fp,
                message.get("message_id"),
            )

            sent += 1

            print(
                "✅ V12 AMAZON REVIEW SENT",
                deal.external_id,
                f"{deal.discount_percent:.1f}%",
                flush=True,
            )

        except Exception as exc:
            delay = core.queue.mark_retry(
                fp,
                f"{type(exc).__name__}: {exc}",
            )

            retried += 1

            print(
                "⚠️ V12 REVIEW RETRY",
                fp[:12],
                f"delay={delay}",
                repr(exc),
                flush=True,
            )

    return {
        "sent": sent,
        "retry": retried,
    }


REVIEW_LOCK = asyncio.Lock()
CAPTURE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="amazon-capture")

STOP_REQUESTED = False


def _request_stop():
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print(
        "🛑 V12 graceful shutdown requested",
        flush=True,
    )


def _checkpoint_v12_db():
    try:
        from deals_v12.state import connect

        with connect() as con:
            con.execute("PRAGMA wal_checkpoint(FULL)")
            con.commit()

        print(
            "💾 V12 database checkpoint complete",
            flush=True,
        )

    except Exception as exc:
        print(
            "⚠️ V12 database checkpoint failed",
            repr(exc),
            flush=True,
        )


async def amazon_ultra_delivery_loop(core, reviewer):
    print(
        "🚨 V12 AMAZON ULTRA DELIVERY LOOP STARTED",
        flush=True,
    )

    while not STOP_REQUESTED:
        try:
            verify = await core.verify_amazon_ultra_batch(
                limit=4
            )

            if verify["processed"]:
                print(
                    "🚨 V12 ULTRA VERIFY",
                    verify,
                    flush=True,
                )

                review = await send_verified_reviews(
                    core,
                    reviewer,
                    ultra_only=True,
                )

                if review["sent"] or review["retry"]:
                    print(
                        "🚨 V12 ULTRA REVIEWS",
                        review,
                        flush=True,
                    )

        except Exception as exc:
            print(
                "⚠️ V12 AMAZON ULTRA DELIVERY ERROR",
                repr(exc),
                flush=True,
            )

        await asyncio.sleep(2)


async def amazon_ultra_loop(core):
    """
    Independent emergency Amazon radar.

    It must never wait for the broad scan, verification,
    screenshots, or Telegram review delivery.
    """
    print(
        "⚡ V12 AMAZON ULTRA FAST LOOP STARTED",
        flush=True,
    )

    while not STOP_REQUESTED:
        started = time.monotonic()

        try:
            result = await core.scan_amazon_ultra_fast_once()

            if (
                result["fetched"]
                or result["new"]
                or result["reopened"]
            ):
                print(
                    "⚡ V12 AMAZON ULTRA FAST",
                    result,
                    f"elapsed={time.monotonic() - started:.1f}s",
                    flush=True,
                )

        except Exception as exc:
            print(
                "⚠️ V12 AMAZON ULTRA FAST ERROR",
                repr(exc),
                flush=True,
            )

        await asyncio.sleep(ULTRA_RADAR_INTERVAL)

    print(
        "⚡ V12 AMAZON ULTRA FAST LOOP STOPPED",
        flush=True,
    )


async def main():
    core = V12Orchestrator()
    reviewer = TelegramReviewer()

    loop = asyncio.get_running_loop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(
                sig,
                _request_stop,
            )
        except NotImplementedError:
            pass

    core.queue.recover_stuck()

    ultra_task = asyncio.create_task(
        amazon_ultra_loop(core)
    )

    ultra_delivery_task = asyncio.create_task(
        amazon_ultra_delivery_loop(
            core,
            reviewer,
        )
    )

    last_scan = 0.0
    last_radar = 0.0

    print(
        "🚀 V12 AMAZON CONTINUOUS WORKER STARTED",
        flush=True,
    )

    while not STOP_REQUESTED:
        now = time.monotonic()

        if (
            last_radar == 0
            or now - last_radar >= RADAR_INTERVAL
        ):
            try:
                radar = await core.scan_amazon_radar_once()

                if (
                    radar["fetched"]
                    or radar["new"]
                    or radar["reopened"]
                ):
                    print(
                        "🚨 V12 AMAZON FAST RADAR",
                        radar,
                        flush=True,
                    )

            except Exception as exc:
                print(
                    "⚠️ V12 AMAZON FAST RADAR ERROR",
                    repr(exc),
                    flush=True,
                )

            last_radar = time.monotonic()

        if (
            last_scan == 0
            or now - last_scan >= SCAN_INTERVAL
        ):
            try:
                result = await core.scan_amazon_once()

                print(
                    "🔎 V12 AMAZON SCAN",
                    result,
                    flush=True,
                )

            except Exception as exc:
                print(
                    "⚠️ V12 AMAZON SCAN ERROR",
                    repr(exc),
                    flush=True,
                )

            last_scan = time.monotonic()

        try:
            verify = await core.verify_amazon_batch(
                limit=VERIFY_LIMIT
            )

            if verify["processed"]:
                print(
                    "🔬 V12 VERIFY",
                    verify,
                    flush=True,
                )

        except Exception as exc:
            print(
                "⚠️ V12 VERIFY ERROR",
                repr(exc),
                flush=True,
            )

        try:
            review = await send_verified_reviews(
                core,
                reviewer,
            )

            if review["sent"] or review["retry"]:
                print(
                    "📨 V12 REVIEWS",
                    review,
                    flush=True,
                )

        except Exception as exc:
            print(
                "⚠️ V12 REVIEW LOOP ERROR",
                repr(exc),
                flush=True,
            )

        core.queue.recover_stuck()

        await asyncio.sleep(
            LOOP_INTERVAL
        )

    try:
        await ultra_task
    except asyncio.CancelledError:
        pass

    try:
        await ultra_delivery_task
    except asyncio.CancelledError:
        pass

    _checkpoint_v12_db()

    print(
        "✅ V12 AMAZON WORKER STOPPED CLEANLY",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
