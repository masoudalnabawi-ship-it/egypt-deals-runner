#!/usr/bin/env python3

import asyncio
import signal
import json
import os
import time

from deals_v12.amazon_capture import capture_amazon_page
from deals_v12.models import DealCandidate
from deals_v12.orchestrator import V12Orchestrator
from deals_v12.review import TelegramReviewer


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


async def send_verified_reviews(core, reviewer):
    rows = core.queue.get_verified(
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

            capture = await asyncio.to_thread(
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

    last_scan = 0.0

    print(
        "🚀 V12 AMAZON CONTINUOUS WORKER STARTED",
        flush=True,
    )

    while not STOP_REQUESTED:
        now = time.monotonic()

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

    _checkpoint_v12_db()

    print(
        "✅ V12 AMAZON WORKER STOPPED CLEANLY",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
