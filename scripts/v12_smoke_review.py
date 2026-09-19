#!/usr/bin/env python3

import asyncio
import httpx

from deals_v12.sources.amazon import AmazonSource
from deals_v12.verification import AmazonVerifier
from deals_v12.review import TelegramReviewer
from deals_v12.amazon_capture import capture_amazon_page


async def main():
    source = AmazonSource()
    verifier = AmazonVerifier()
    reviewer = TelegramReviewer()

    print("🔎 V12 AMAZON DISCOVERY", flush=True)

    items = await source.scan_once()

    candidates = [
        deal
        for deal in items
        if deal.old_price
        and deal.old_price > deal.current_price
        and deal.discount_percent >= 5
    ]

    candidates.sort(
        key=lambda deal: deal.discount_percent,
        reverse=True,
    )

    print(
        f"📦 fetched={len(items)} candidates={len(candidates)}",
        flush=True,
    )

    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
    ) as client:

        for deal in candidates[:8]:
            print(
                "🔬 VERIFY",
                deal.external_id,
                f"{deal.discount_percent:.1f}%",
                flush=True,
            )

            try:
                result = await verifier.verify(
                    client,
                    deal,
                )
            except Exception as exc:
                print(
                    "⚠️ VERIFY ERROR",
                    deal.external_id,
                    repr(exc),
                    flush=True,
                )
                continue

            if not result.get("verified"):
                print(
                    "❌ NOT VERIFIED",
                    deal.external_id,
                    result.get("reason"),
                    flush=True,
                )
                continue

            deal.current_price = float(
                result["current_price"]
            )

            deal.old_price = float(
                result["old_price"]
            )

            deal.metadata["verification"] = result

            print(
                "📸 CAPTURE AMAZON PAGE",
                deal.external_id,
                flush=True,
            )

            capture = await asyncio.to_thread(
                capture_amazon_page,
                deal.url,
                deal.external_id or "product",
            )

            if not capture.get("ok"):
                print(
                    "⚠️ SCREENSHOT FAILED",
                    deal.external_id,
                    capture.get("reason"),
                    flush=True,
                )
                continue

            screenshot = str(
                capture.get("screenshot") or ""
            ).strip()

            if not screenshot:
                print(
                    "⚠️ SCREENSHOT MISSING",
                    deal.external_id,
                    flush=True,
                )
                continue

            deal.metadata["review_media_path"] = screenshot
            deal.metadata["review_media_source"] = "amazon_page_screenshot"

            message = await reviewer.send_review(deal)

            print(
                "✅ V12 TEST REVIEW SENT",
                "| ASIN =", deal.external_id,
                "| MESSAGE_ID =", message.get("message_id"),
                flush=True,
            )

            return

    raise RuntimeError(
        "No verified Amazon candidate found for smoke test"
    )


if __name__ == "__main__":
    asyncio.run(main())
