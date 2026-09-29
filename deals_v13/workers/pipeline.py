from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from ..config import Settings
from ..delivery.telegram import TelegramDelivery
from ..discovery.amazon import AmazonDiscovery
from ..discovery.noon import NoonDiscovery
from ..discovery.scheduler import AdaptiveSurfaceSelector
from ..infra.db import DealDatabase
from ..infra.http import StoreHttpClient
from ..intelligence import IntelligenceEngine, best_cross_store_match
from ..models import DealCandidate, Lane
from ..verification.verifier import StoreVerifier, VerificationRejected


log = logging.getLogger("v13")


class V13Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = DealDatabase(settings.db_path)
        self.http = StoreHttpClient(settings)
        self.intel = IntelligenceEngine(settings)
        self.verifier = StoreVerifier(self.http)
        self.delivery = TelegramDelivery(settings)
        self.stop_event = asyncio.Event()

        self.discovery = {
            "amazon": AmazonDiscovery(),
            "noon": NoonDiscovery(),
        }
        self.selectors = {
            store: AdaptiveSurfaceSelector(
                list(obj.surfaces),
                exploration_rate=settings.exploration_rate,
            )
            for store, obj in self.discovery.items()
        }

    async def close(self):
        await self.delivery.aclose()
        await self.http.aclose()

    def _preliminary(self, deal: DealCandidate):
        flash = bool((deal.metadata or {}).get("flash_hint"))
        decision = self.intel.evaluate(
            deal,
            verified=False,
            coupon_percent=0,
            flash=flash,
            history=[],
        )
        if deal.discount_percent >= 50:
            decision.lane = Lane.ULTRA
            decision.score = max(decision.score, min(95, 55 + deal.discount_percent * 0.35))
            decision.reasons.append("pre_ultra_surface_discount")
        else:
            decision.lane = Lane.NORMAL
        return decision

    async def discovery_loop(self, store: str):
        adapter = self.discovery[store]
        selector = self.selectors[store]
        while not self.stop_event.is_set():
            health = await asyncio.to_thread(self.db.source_health, store)
            surfaces = selector.pick(self.settings.surface_batch_size, health)

            for surface in surfaces:
                started = time.monotonic()
                fetched = 0
                candidates = 0
                error = ""
                latency = 0
                try:
                    result = await self.http.fetch(surface.url, store)
                    latency = result.latency_ms
                    deals = (
                        adapter.parse_search(result.text, surface)
                        if store == "amazon"
                        else adapter.parse_page(result.text, surface)
                    )
                    fetched = len(deals)

                    for deal in deals:
                        if deal.current_price <= 0:
                            continue
                        preliminary = self._preliminary(deal)
                        await asyncio.to_thread(self.db.upsert_candidate, deal, preliminary)
                        candidates += 1

                except Exception as exc:
                    error = f"{type(exc).__name__}:{exc}"
                    log.warning("DISCOVERY %s/%s failed | %s", store, surface.name, error)

                await asyncio.to_thread(
                    self.db.source_result,
                    store, surface.name, surface.category,
                    fetched, candidates, latency, error,
                )
                log.info(
                    "DISCOVERY store=%s source=%s fetched=%s queued=%s error=%s",
                    store, surface.name, fetched, candidates, bool(error),
                )

            try:
                await asyncio.wait_for(
                    self.stop_event.wait(),
                    timeout=self.settings.discovery_interval,
                )
            except asyncio.TimeoutError:
                pass

    async def verification_loop(self, store: str, lane: Lane, index: int):
        worker_id = f"verify-{store}-{lane.value}-{index}-{uuid.uuid4().hex[:6]}"
        while not self.stop_event.is_set():
            row = await asyncio.to_thread(
                self.db.claim_for_verification,
                store, lane, worker_id, self.settings.lease_seconds,
            )
            if not row:
                await asyncio.sleep(self.settings.verification_interval)
                continue

            deal_key = row["deal_key"]
            incoming = self.db.row_to_candidate(row)
            try:
                verified, vmeta = await self.verifier.verify(incoming)

                history = await asyncio.to_thread(self.db.recent_prices, deal_key)
                others = await asyncio.to_thread(self.db.recent_other_store, store)
                cross, similarity = best_cross_store_match(verified, others)

                anomaly = bool((incoming.metadata or {}).get("price_anomaly"))
                decision = self.intel.evaluate(
                    verified,
                    verified=True,
                    coupon_percent=float(vmeta.get("coupon_percent") or 0),
                    flash=bool(vmeta.get("flash")),
                    anomaly=anomaly,
                    history=history,
                    cross_store_row=cross,
                    cross_store_similarity=similarity,
                    verification_signals=int(vmeta.get("verification_signals") or 0),
                )
                ok, reason = self.intel.acceptable(decision)
                if not ok:
                    await asyncio.to_thread(self.db.mark_rejected, deal_key, reason)
                    log.info("REJECT %s %s | %s", store, deal_key[:10], reason)
                    continue

                # STRICT50 final routing after live verification:
                # - verified real discount < 50% => review chat
                # - verified real discount >= 50% => ultra group
                # - exceptional/anomalous price => ultra group with maximum priority
                exceptional = anomaly or ("price_anomaly" in decision.reasons)
                if exceptional:
                    decision.lane = Lane.ULTRA
                    decision.score = max(decision.score, 99.0)
                    if "exceptional_price_priority" not in decision.reasons:
                        decision.reasons.append("exceptional_price_priority")
                elif decision.real_discount >= 50.0:
                    decision.lane = Lane.ULTRA
                    decision.score = max(decision.score, 90.0)
                    if "strict50_ultra" not in decision.reasons:
                        decision.reasons.append("strict50_ultra")
                else:
                    decision.lane = Lane.NORMAL
                    if "strict50_review" not in decision.reasons:
                        decision.reasons.append("strict50_review")

                meta = dict(verified.metadata or {})
                meta.update(vmeta)
                meta["decision_reasons"] = decision.reasons
                meta["strict50_route"] = decision.lane.value
                meta["exceptional_priority"] = exceptional
                if cross:
                    meta["cross_store"] = {
                        "store": cross.get("store"),
                        "price": cross.get("current_price"),
                        "similarity": round(similarity, 3),
                    }

                await asyncio.to_thread(
                    self.db.mark_verified,
                    deal_key, verified, decision, meta,
                )
                log.info(
                    "VERIFY OK store=%s lane=%s discount=%.1f confidence=%.2f score=%.1f id=%s",
                    store, decision.lane.value, decision.real_discount,
                    decision.confidence, decision.score, verified.external_id,
                )

            except VerificationRejected as exc:
                await asyncio.to_thread(self.db.mark_rejected, deal_key, str(exc))
            except Exception as exc:
                await asyncio.to_thread(
                    self.db.mark_retry,
                    deal_key, f"{type(exc).__name__}:{exc}",
                    self.settings.retry_base_seconds, self.settings.max_attempts,
                )
                log.warning("VERIFY RETRY store=%s key=%s | %s", store, deal_key[:10], exc)

    async def delivery_loop(self, lane: Lane):
        worker_id = f"deliver-{lane.value}-{uuid.uuid4().hex[:6]}"
        while not self.stop_event.is_set():
            row = await asyncio.to_thread(
                self.db.claim_for_delivery,
                lane, worker_id, self.settings.lease_seconds,
            )
            if not row:
                await asyncio.sleep(self.settings.delivery_interval)
                continue

            if int(row.get("next_attempt_at") or 0) > int(time.time()):
                await asyncio.to_thread(
                    self.db.delivery_retry,
                    row["deal_key"], "delivery_not_due",
                    self.settings.retry_base_seconds, self.settings.max_attempts,
                )
                await asyncio.sleep(1)
                continue

            try:
                await self.delivery.send(row)
                await asyncio.to_thread(self.db.mark_sent, row["deal_key"])
                log.info(
                    "SEND OK store=%s lane=%s discount=%.1f id=%s",
                    row["store"], lane.value, float(row.get("real_discount") or 0),
                    row.get("external_id") or row["deal_key"][:10],
                )
            except Exception as exc:
                await asyncio.to_thread(
                    self.db.delivery_retry,
                    row["deal_key"], f"{type(exc).__name__}:{exc}",
                    self.settings.retry_base_seconds, self.settings.max_attempts,
                )
                log.warning("SEND RETRY lane=%s | %s", lane.value, exc)

    async def health_loop(self):
        while not self.stop_event.is_set():
            released = await asyncio.to_thread(self.db.release_stale_leases)
            stats = await asyncio.to_thread(self.db.stats)
            log.info(
                "HEALTH V13 released=%s stats=%s",
                released, json.dumps(stats, ensure_ascii=False),
            )
            try:
                await asyncio.wait_for(
                    self.stop_event.wait(),
                    timeout=self.settings.health_interval,
                )
            except asyncio.TimeoutError:
                pass

    async def run(self):
        tasks = [
            asyncio.create_task(self.discovery_loop("amazon"), name="discover-amazon"),
            asyncio.create_task(self.discovery_loop("noon"), name="discover-noon"),
            asyncio.create_task(self.delivery_loop(Lane.ULTRA), name="deliver-ultra"),
            asyncio.create_task(self.delivery_loop(Lane.NORMAL), name="deliver-normal"),
            asyncio.create_task(self.health_loop(), name="health"),
        ]

        for store in ("amazon", "noon"):
            for lane in (Lane.ULTRA, Lane.NORMAL):
                for i in range(self.settings.verification_workers_per_store):
                    tasks.append(
                        asyncio.create_task(
                            self.verification_loop(store, lane, i),
                            name=f"verify-{store}-{lane.value}-{i}",
                        )
                    )

        log.warning(
            "V13 START | stores=amazon,noon | STRICT50 | discovery=%ss | workers/store/lane=%s",
            self.settings.discovery_interval,
            self.settings.verification_workers_per_store,
        )

        try:
            await self.stop_event.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.close()

    def stop(self):
        self.stop_event.set()
