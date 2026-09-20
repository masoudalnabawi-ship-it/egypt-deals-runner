import time

from .health import HealthMonitor
from .queue import DealQueue
from .sources.amazon import AmazonSource


class V12Orchestrator:
    def __init__(self):
        self.health = HealthMonitor()
        self.queue = DealQueue()
        self.amazon = AmazonSource()

    async def scan_amazon_radar_once(self):
        items = await self.amazon.scan_fast_radar_once()

        new_count = 0
        reopened_count = 0

        for deal in items:
            result = self.queue.enqueue(
                deal,
                priority=1000,
            )

            if result == "new":
                new_count += 1
            elif result == "reopened":
                reopened_count += 1

        return {
            "fetched": len(items),
            "new": new_count,
            "reopened": reopened_count,
        }


    async def scan_amazon_once(self):
        store = "amazon"
        started = time.monotonic()

        self.health.mark_attempt(store)

        try:
            items = await self.amazon.scan_once()

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

            new_count = 0
            reopened_count = 0

            for deal in candidates:
                if (deal.metadata or {}).get("price_anomaly"):
                    priority = 1000

                elif (deal.metadata or {}).get("promo_text"):
                    priority = max(
                        650,
                        int(
                            min(
                                1000,
                                deal.discount_percent * 10,
                            )
                        ),
                    )
                else:
                    priority = int(
                        min(
                            1000,
                            deal.discount_percent * 10,
                        )
                    )

                result = self.queue.enqueue(
                    deal,
                    priority=priority,
                )

                if result == "new":
                    new_count += 1
                elif result == "reopened":
                    reopened_count += 1

            latency_ms = int(
                (time.monotonic() - started) * 1000
            )

            self.health.mark_success(
                store,
                fetched=len(items),
                candidates=len(candidates),
                latency_ms=latency_ms,
            )

            return {
                "fetched": len(items),
                "candidates": len(candidates),
                "new": new_count,
                "reopened": reopened_count,
                "queue": self.queue.stats(),
            }

        except Exception as exc:
            latency_ms = int(
                (time.monotonic() - started) * 1000
            )

            self.health.mark_error(
                store,
                exc,
                latency_ms=latency_ms,
            )

            raise

    async def verify_amazon_batch(self, limit=6):
        import json
        import httpx

        from .models import DealCandidate
        from .verification import AmazonVerifier

        rows = [
            row
            for row in self.queue.get_due(limit=limit)
            if row.get("store") == "amazon"
        ]

        verifier = AmazonVerifier()

        verified = 0
        invalid = 0
        retried = 0

        async with httpx.AsyncClient() as client:
            for row in rows:
                fp = row["fingerprint"]

                try:
                    data = json.loads(row["payload"])

                    deal = DealCandidate(
                        store=data["store"],
                        external_id=data["external_id"],
                        title=data["title"],
                        url=data["url"],
                        current_price=float(
                            data["current_price"]
                        ),
                        old_price=data.get("old_price"),
                        image_url=data.get(
                            "image_url",
                            "",
                        ),
                        discovered_at=int(
                            data.get("discovered_at")
                            or 0
                        ),
                        metadata=data.get(
                            "metadata"
                        ) or {},
                    )

                    self.queue.mark_processing(fp)

                    result = await verifier.verify(
                        client,
                        deal,
                    )

                    if result.get("verified"):
                        self.queue.mark_verified(
                            fp,
                            result,
                        )
                        verified += 1

                    else:
                        reason = str(
                            result.get("reason")
                            or "verification_failed"
                        )

                        if reason == "no_live_price":
                            self.queue.mark_retry(
                                fp,
                                reason,
                            )
                            retried += 1
                        else:
                            self.queue.mark_invalid(
                                fp,
                                reason,
                            )
                            invalid += 1

                except Exception as exc:
                    self.queue.mark_retry(
                        fp,
                        f"{type(exc).__name__}: {exc}",
                    )
                    retried += 1

        return {
            "processed": len(rows),
            "verified": verified,
            "invalid": invalid,
            "retry": retried,
            "queue": self.queue.stats(),
        }
