from __future__ import annotations

from dataclasses import asdict
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
from ..price_intelligence import build_price_profile
from ..ultra_hunter import UltraHunterPlanner
from ..models import DealCandidate, Lane
from ..verification.verifier import StoreVerifier, VerificationRejected


log = logging.getLogger("v14")


class V14Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = DealDatabase(settings.db_path)
        self.http = StoreHttpClient(settings)
        self.intel = IntelligenceEngine(settings)
        self.verifier = StoreVerifier(self.http)
        self.delivery = TelegramDelivery(settings)
        self.stop_event = asyncio.Event()

        self.ultra_hunter = UltraHunterPlanner()

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
        flash = bool(
            (deal.metadata or {}).get("flash_hint")
        )

        decision = self.intel.evaluate(
            deal,
            verified=False,
            coupon_percent=0,
            flash=flash,
            history=[],
        )

        # Search cards frequently omit Amazon's crossed-out/list price.
        # A product found through a dedicated hot radar is therefore sent
        # to the Ultra VERIFICATION queue even when the search card itself
        # cannot calculate the percentage.
        #
        # IMPORTANT:
        # This does NOT publish it as Ultra.
        # The product page must still prove a real >=50% discount later.
        hot_floor = 0.0

        if deal.store == "amazon":
            hot_floor = {
                "50off": 50.0,
                "70off": 70.0,
                "90off": 90.0,
                "50filter": 50.0,
                "70filter": 70.0,
                "90filter": 90.0,
                "electronics_50hot": 50.0,
                "appliances_50hot": 50.0,
                "beauty_50hot": 50.0,
                "fashion_50hot": 50.0,
            }.get(
                str(deal.source or "").lower(),
                0.0,
            )

        if hot_floor:
            decision.lane = Lane.ULTRA
            decision.score = max(
                decision.score,
                100.0 if hot_floor >= 70.0
                else 94.0,
            )

            reason = (
                "amazon_hot_radar_priority_"
                f"{int(hot_floor)}"
            )

            if reason not in decision.reasons:
                decision.reasons.append(reason)

        elif deal.discount_percent >= 70:
            decision.lane = Lane.ULTRA
            decision.score = 100.0

            if "pre_hot_ultra_70" not in decision.reasons:
                decision.reasons.append(
                    "pre_hot_ultra_70"
                )

        elif deal.discount_percent >= 50:
            decision.lane = Lane.ULTRA
            decision.score = max(
                decision.score,
                min(
                    95.0,
                    55.0
                    + deal.discount_percent * 0.35,
                ),
            )

            if (
                "pre_ultra_surface_discount"
                not in decision.reasons
            ):
                decision.reasons.append(
                    "pre_ultra_surface_discount"
                )

        else:
            decision.lane = Lane.NORMAL

        return decision

    async def discovery_loop(self, store: str):
        adapter = self.discovery[store]
        selector = self.selectors[store]
        while not self.stop_event.is_set():
            health = await asyncio.to_thread(
                self.db.source_health,
                store,
            )
            surfaces = selector.pick(
                self.settings.surface_batch_size,
                health,
            )

            mandatory_names = set()

            if store == "amazon":
                mandatory_names = {
                    "90off",
                    "70off",
                    "50off",
                    "90filter",
                    "70filter",
                    "50filter",
                }

            elif store == "noon":
                # Never allow adaptive scoring to make Noon effectively
                # a fashion-only scanner. These reliable non-fashion
                # categories are checked every cycle.
                mandatory_names = {
                    "mobiles",
                    "laptops",
                    "appliances",
                }

            if mandatory_names:
                mandatory = [
                    item
                    for item in adapter.surfaces
                    if item.name in mandatory_names
                ]

                merged = mandatory + surfaces

                unique_surfaces = []
                seen_surface_names = set()

                for item in merged:
                    if item.name in seen_surface_names:
                        continue

                    seen_surface_names.add(
                        item.name
                    )
                    unique_surfaces.append(item)

                surfaces = unique_surfaces

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

    async def ultra_hunter_loop(
        self,
        store: str,
    ):
        """
        Independent fast radar.

        It only queues likely Ultra candidates for live verification.
        The final Strict50 decision still happens in verification_loop().
        """
        adapter = self.discovery[store]

        while not self.stop_event.is_set():
            plan = self.ultra_hunter.pick_surfaces(
                store,
                list(adapter.surfaces),
                self.settings.ultra_hunter_batch_size,
            )

            fetched_total = 0
            queued_total = 0
            errors = 0

            for surface in plan.surfaces:
                try:
                    result = await self.http.fetch(
                        surface.url,
                        store,
                    )

                    deals = (
                        adapter.parse_search(
                            result.text,
                            surface,
                        )
                        if store == "amazon"
                        else adapter.parse_page(
                            result.text,
                            surface,
                        )
                    )

                    fetched_total += len(deals)

                    for deal in deals:
                        if deal.current_price <= 0:
                            continue

                        preliminary = self._preliminary(
                            deal
                        )

                        priority = (
                            self.ultra_hunter
                            .prioritize(
                                deal,
                                preliminary,
                                noon_probe_floor=(
                                    self.settings
                                    .ultra_hunter_noon_probe_floor
                                ),
                            )
                        )

                        if not priority:
                            continue

                        metadata = dict(
                            deal.metadata or {}
                        )

                        metadata.update({
                            "v14_ultra_hunter": True,
                            "v14_hunter_surface":
                                surface.name,
                            "v14_hunter_observed_discount":
                                deal.discount_percent,
                        })

                        deal.metadata = metadata

                        await asyncio.to_thread(
                            self.db.upsert_candidate,
                            deal,
                            preliminary,
                        )

                        queued_total += 1

                except Exception as exc:
                    errors += 1

                    log.warning(
                        "ULTRA HUNTER %s/%s failed | %s:%s",
                        store,
                        surface.name,
                        type(exc).__name__,
                        exc,
                    )

            log.info(
                "ULTRA HUNTER store=%s "
                "surfaces=%s fetched=%s "
                "priority_queued=%s errors=%s",
                store,
                ",".join(
                    item.name
                    for item in plan.surfaces
                ),
                fetched_total,
                queued_total,
                errors,
            )

            try:
                await asyncio.wait_for(
                    self.stop_event.wait(),
                    timeout=(
                        self.settings
                        .ultra_hunter_interval
                    ),
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

                history = await asyncio.to_thread(
                    self.db.recent_prices,
                    deal_key,
                )

                price_profile = build_price_profile(
                    history,
                    verified.current_price,
                )

                others = await asyncio.to_thread(
                    self.db.recent_other_store,
                    store,
                )
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
                    verification_signals=int(
                        vmeta.get(
                            "verification_signals"
                        )
                        or 0
                    ),
                    price_profile=price_profile,
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
                signals = int(
                    vmeta.get("verification_signals") or 0
                )
                old_live = float(verified.old_price or 0)
                current_live = float(
                    verified.current_price or 0
                )

                http_via = str(
                    vmeta.get("http_via") or ""
                )
                noon_catalog_verified = (
                    "noon_catalog_api" in http_via
                )

                # Noon discounts >=50% must come from the product catalog API.
                # The generic storefront fallback is useful for discovery,
                # but is not strong enough for automatic Ultra routing.
                if (
                    store == "noon"
                    and decision.real_discount >= 50.0
                    and not noon_catalog_verified
                ):
                    await asyncio.to_thread(
                        self.db.mark_rejected,
                        deal_key,
                        "noon_high_discount_needs_catalog_confirmation",
                    )
                    log.warning(
                        "NOON HIGH DISCOUNT BLOCKED id=%s discount=%.1f via=%s",
                        verified.external_id,
                        decision.real_discount,
                        http_via,
                    )
                    continue

                irrational_price = bool(
                    old_live >= 1000
                    and current_live > 0
                    and current_live <= old_live * 0.30
                    and signals >= 2
                    and decision.confidence
                    >= self.settings.min_confidence_ultra
                )

                hot_priority = bool(
                    irrational_price
                    or (
                        decision.anomaly
                        and decision.confidence >= 0.90
                    )
                    or (
                        decision.real_discount >= 70.0
                        and signals >= 2
                        and decision.confidence
                        >= self.settings.min_confidence_ultra
                    )
                )

                if hot_priority:
                    decision.lane = Lane.ULTRA
                    decision.score = 100.0
                    if "hot_ultra_priority" not in decision.reasons:
                        decision.reasons.append(
                            "hot_ultra_priority"
                        )
                    if irrational_price:
                        decision.reasons.append(
                            "irrational_verified_price"
                        )

                elif (
                    decision.real_discount >= 50.0
                    and signals >= 2
                    and decision.confidence
                    >= self.settings.min_confidence_ultra
                ):
                    decision.lane = Lane.ULTRA
                    decision.score = max(
                        decision.score,
                        90.0,
                    )
                    if "strict50_ultra" not in decision.reasons:
                        decision.reasons.append(
                            "strict50_ultra"
                        )

                elif decision.real_discount >= 50.0:
                    await asyncio.to_thread(
                        self.db.mark_rejected,
                        deal_key,
                        "high_discount_needs_stronger_verification",
                    )
                    log.warning(
                        "HIGH DISCOUNT BLOCKED store=%s id=%s discount=%.1f signals=%s confidence=%.2f",
                        store,
                        verified.external_id,
                        decision.real_discount,
                        signals,
                        decision.confidence,
                    )
                    continue

                else:
                    decision.lane = Lane.NORMAL
                    if "strict50_review" not in decision.reasons:
                        decision.reasons.append(
                            "strict50_review"
                        )

                meta = dict(verified.metadata or {})
                meta.update(vmeta)
                meta["decision_reasons"] = decision.reasons
                meta["strict50_route"] = decision.lane.value
                meta["exceptional_priority"] = hot_priority
                meta["irrational_price"] = irrational_price
                meta["hot_priority"] = hot_priority
                meta["price_intelligence"] = asdict(
                    price_profile
                )
                meta["deal_score_breakdown"] = (
                    decision.score_breakdown
                )

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

    def _callback_allowed(self, cb: dict) -> bool:
        message = cb.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "")
        allowed = {
            str(self.settings.normal_chat_id or ""),
            str(self.settings.ultra_chat_id or ""),
            str(self.settings.noon_normal_chat_id or ""),
            str(self.settings.noon_ultra_chat_id or ""),
        }
        return bool(chat_id and chat_id in allowed)

    async def _handle_callback(self, cb: dict) -> None:
        cb_id = str(cb.get("id") or "")
        data = str(cb.get("data") or "")
        message = cb.get("message") or {}

        if not self._callback_allowed(cb):
            await self.delivery.answer_callback(cb_id, "غير مصرح", True)
            return

        parts = data.split(":")
        if len(parts) != 3 or parts[0] != "v14":
            return

        action, short_key = parts[1], parts[2]
        row = await asyncio.to_thread(self.db.find_by_prefix, short_key)
        if not row:
            await self.delivery.answer_callback(
                cb_id,
                "العرض غير موجود في قاعدة V14",
                True,
            )
            return

        if action == "r":
            await asyncio.to_thread(
                self.db.event,
                "manual_reject",
                row["store"],
                row["deal_key"],
                {"action": "reject"},
            )
            await self.delivery.answer_callback(cb_id, "تم رفض العرض ❌")
        elif action in {"p", "u"}:
            if await asyncio.to_thread(
                self.db.has_event,
                row["deal_key"],
                "manual_publish",
            ):
                await self.delivery.answer_callback(
                    cb_id,
                    "تم نشر العرض بالفعل",
                )
                return

            incoming = self.db.row_to_candidate(row)
            try:
                fresh, _ = await self.verifier.verify(incoming)
            except VerificationRejected:
                await self.delivery.answer_callback(
                    cb_id,
                    "العرض لم يعد يحقق شروط التحقق",
                    True,
                )
                return
            except Exception as exc:
                log.warning(
                    "CALLBACK recheck failed key=%s | %s",
                    row["deal_key"][:10],
                    exc,
                )
                await self.delivery.answer_callback(
                    cb_id,
                    "تعذر إعادة التحقق الآن، جرّب مرة أخرى",
                    True,
                )
                return

            reviewed_price = float(row.get("current_price") or 0)
            fresh_price = float(fresh.current_price or 0)
            if reviewed_price > 0 and fresh_price > reviewed_price * 1.02:
                await self.delivery.answer_callback(
                    cb_id,
                    "السعر ارتفع منذ المراجعة؛ لم يتم النشر",
                    True,
                )
                return

            public_row = dict(row)
            public_row["title"] = fresh.title or row["title"]
            public_row["url"] = fresh.url or row["url"]
            public_row["image_url"] = (
                fresh.image_url or row.get("image_url") or ""
            )
            public_row["current_price"] = fresh_price or reviewed_price
            public_row["old_price"] = (
                fresh.old_price or row.get("old_price")
            )

            await self.delivery.send_public(
                public_row,
                urgent=(action == "u"),
            )
            await asyncio.to_thread(
                self.db.event,
                "manual_publish",
                row["store"],
                row["deal_key"],
                {"urgent": action == "u"},
            )
            await self.delivery.answer_callback(
                cb_id,
                "تم النشر العاجل 🚀"
                if action == "u"
                else "تم النشر ✅",
            )
        else:
            return

        try:
            await self.delivery.clear_buttons(
                int((message.get("chat") or {}).get("id")),
                int(message.get("message_id")),
            )
        except Exception:
            pass

    async def callback_loop(self):
        await self.delivery.delete_webhook()
        offset = None
        while not self.stop_event.is_set():
            try:
                updates = await self.delivery.get_updates(
                    offset,
                    timeout=20,
                )
                for update in updates:
                    offset = int(update["update_id"]) + 1
                    cb = update.get("callback_query")
                    if cb:
                        await self._handle_callback(cb)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("V13 CALLBACK polling retry | %s", exc)
                await asyncio.sleep(3)

    async def health_loop(self):
        while not self.stop_event.is_set():
            released = await asyncio.to_thread(self.db.release_stale_leases)
            stats = await asyncio.to_thread(self.db.stats)
            log.info(
                "HEALTH V14 released=%s stats=%s",
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
            asyncio.create_task(
                self.discovery_loop("amazon"),
                name="discover-amazon",
            ),
            asyncio.create_task(
                self.discovery_loop("noon"),
                name="discover-noon",
            ),

            # Separate fast high-discount hunters.
            asyncio.create_task(
                self.ultra_hunter_loop("amazon"),
                name="ultra-hunter-amazon",
            ),
            asyncio.create_task(
                self.ultra_hunter_loop("noon"),
                name="ultra-hunter-noon",
            ),

            asyncio.create_task(
                self.delivery_loop(Lane.ULTRA),
                name="deliver-ultra",
            ),
            asyncio.create_task(self.delivery_loop(Lane.NORMAL), name="deliver-normal"),
            asyncio.create_task(self.callback_loop(), name="telegram-callbacks"),
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
            "V14 START | stores=amazon,noon | "
            "STRICT50 | callbacks=v14 | discovery=%ss | "
            "ultra_hunter=%ss | workers/store/lane=%s",
            self.settings.discovery_interval,
            self.settings.ultra_hunter_interval,
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
