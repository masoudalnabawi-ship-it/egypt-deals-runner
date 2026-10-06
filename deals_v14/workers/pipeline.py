from __future__ import annotations

from dataclasses import asdict
import asyncio
import json
import logging
import time
import uuid
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlsplit,
    urlunsplit,
)

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
from ..anomaly_shield import inspect_deal
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

        # Each Amazon Ultra source rotates through search pages
        # instead of repeatedly scanning page 1.
        self._amazon_ultra_page_cursor: dict[str, int] = {}

        # Hidden Coupon Exploration:
        # rotate through one product per normal Amazon surface
        # instead of repeatedly probing the first ASIN.
        self._amazon_coupon_probe_cursor: dict[str, int] = {}

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

        # ==================================================
        # EVIDENCE-DRIVEN AMAZON ULTRA POLICY
        #
        # A source/query name is never proof of a discount.
        # Actual visible discount or later live verification is.
        # ==================================================

        store = str(deal.store or "").strip().lower()
        discount = float(deal.discount_percent or 0)
        metadata = dict(deal.metadata or {})

        if store != "amazon":
            decision.lane = Lane.NORMAL

            if (
                store == "noon"
                and "noon_normal_only"
                not in decision.reasons
            ):
                decision.reasons.append(
                    "noon_normal_only"
                )

            return decision

        if discount >= 75.0:
            decision.lane = Lane.ULTRA
            decision.score = 100.0

            if "amazon_pre_max_75" not in decision.reasons:
                decision.reasons.append(
                    "amazon_pre_max_75"
                )

        elif discount >= 70.0:
            decision.lane = Lane.ULTRA
            decision.score = max(
                float(decision.score or 0),
                97.0,
            )

            if "amazon_pre_ultra_70" not in decision.reasons:
                decision.reasons.append(
                    "amazon_pre_ultra_70"
                )

        elif discount >= 65.0:
            decision.lane = Lane.ULTRA
            decision.score = max(
                float(decision.score or 0),
                96.0,
            )

            if "amazon_pre_ultra_65" not in decision.reasons:
                decision.reasons.append(
                    "amazon_pre_ultra_65"
                )

        elif (
            metadata.get("promo_hint")
            or metadata.get("flash_hint")
        ):
            # Interesting promo: verify quickly in NORMAL.
            # Live verification may later promote it to Ultra.
            decision.lane = Lane.NORMAL
            decision.score = max(
                float(decision.score or 0),
                88.0,
            )

            if (
                "amazon_promo_fast_probe"
                not in decision.reasons
            ):
                decision.reasons.append(
                    "amazon_promo_fast_probe"
                )

        else:
            decision.lane = Lane.NORMAL

        return decision

    def _amazon_ultra_page_url(
        self,
        surface,
    ) -> tuple[str, int]:
        """
        Rotate each Amazon radar through pages 1..4.

        Important:
        - one request per selected surface only
        - no concurrency increase
        - source identity stays unchanged for learning
        """
        key = str(surface.name or "")

        cursor = self._amazon_ultra_page_cursor.get(
            key,
            0,
        )

        page = (cursor % 4) + 1

        self._amazon_ultra_page_cursor[key] = (
            cursor + 1
        )

        if page == 1:
            return surface.url, page

        parts = urlsplit(surface.url)

        query = [
            (k, v)
            for k, v in parse_qsl(
                parts.query,
                keep_blank_values=True,
            )
            if k != "page"
        ]

        query.append(
            ("page", str(page))
        )

        url = urlunsplit((
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        ))

        return url, page

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
                # Reliable promotional surfaces stay mandatory.
                # High-discount/category surfaces are handled by
                # adaptive exploration and Ultra Hunter.
                mandatory_names = {
                    "limited_time",
                    "clearance",
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

                    # ==================================================
                    # HIDDEN COUPON EXPLORATION
                    #
                    # Search cards do not always expose Amazon coupons.
                    # From each ordinary Amazon surface, probe exactly
                    # ONE product per scan and rotate the ASIN over time.
                    #
                    # Goldbox / limited-time / clearance already have
                    # their own high-priority verification paths.
                    # ==================================================
                    coupon_probe_id = ""

                    if (
                        store == "amazon"
                        and deals
                        and surface.name not in {
                            "goldbox",
                            "limited_time",
                            "clearance",
                        }
                    ):
                        eligible = [
                            item
                            for item in deals
                            if item.current_price > 0
                        ]

                        if eligible:
                            cursor = (
                                self._amazon_coupon_probe_cursor
                                .get(surface.name, 0)
                            )

                            probe = eligible[
                                cursor % len(eligible)
                            ]

                            self._amazon_coupon_probe_cursor[
                                surface.name
                            ] = cursor + 1

                            coupon_probe_id = (
                                probe.external_id
                            )

                    for deal in deals:
                        if deal.current_price <= 0:
                            continue

                        is_coupon_probe = bool(
                            store == "amazon"
                            and coupon_probe_id
                            and deal.external_id
                            == coupon_probe_id
                        )

                        if is_coupon_probe:
                            metadata = dict(
                                deal.metadata or {}
                            )

                            metadata.update({
                                "coupon_probe": True,
                                "coupon_probe_surface":
                                    surface.name,
                            })

                            deal.metadata = metadata

                        preliminary = self._preliminary(
                            deal
                        )

                        if is_coupon_probe:
                            preliminary.score = max(
                                float(
                                    preliminary.score
                                    or 0
                                ),
                                87.0,
                            )

                            if (
                                "amazon_coupon_probe"
                                not in preliminary.reasons
                            ):
                                preliminary.reasons.append(
                                    "amazon_coupon_probe"
                                )

                        # ==========================================
                        # SMART AMAZON ADMISSION GATE
                        #
                        # Do not flood live verification with every
                        # ordinary search result.
                        #
                        # Admit only:
                        # - Goldbox / Today's Deals
                        # - explicit promo / coupon / flash evidence
                        # - visible discount meeting normal threshold
                        # - one rotating hidden-coupon probe
                        #
                        # This keeps full department exploration while
                        # reserving verifier capacity for useful leads.
                        # ==========================================
                        if store == "amazon":
                            meta = dict(
                                deal.metadata or {}
                            )

                            goldbox_evidence = bool(
                                surface.name == "goldbox"
                                or meta.get("goldbox")
                            )

                            promo_evidence = bool(
                                meta.get("promo_hint")
                                or meta.get("coupon_hint")
                                or meta.get("flash_hint")
                            )

                            visible_evidence = bool(
                                deal.discount_percent
                                >= self.settings.normal_min_discount
                            )

                            if not (
                                is_coupon_probe
                                or goldbox_evidence
                                or promo_evidence
                                or visible_evidence
                            ):
                                continue

                        await asyncio.to_thread(
                            self.db.upsert_candidate,
                            deal,
                            preliminary,
                        )

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
        The final verified Amazon 65%+ decision happens in verification_loop().
        """
        adapter = self.discovery[store]

        while not self.stop_event.is_set():
            health = await asyncio.to_thread(
                self.db.source_health,
                store,
            )

            plan = self.ultra_hunter.pick_surfaces(
                store,
                list(adapter.surfaces),
                self.settings.ultra_hunter_batch_size,
                health=health,
            )

            fetched_total = 0
            queued_total = 0
            errors = 0

            for surface in plan.surfaces:
                surface_fetched = 0
                surface_queued = 0
                surface_latency = 0
                surface_error = ""

                try:
                    fetch_url = surface.url
                    hunter_page = 1

                    if store == "amazon":
                        (
                            fetch_url,
                            hunter_page,
                        ) = self._amazon_ultra_page_url(
                            surface
                        )

                    result = await self.http.fetch(
                        fetch_url,
                        store,
                    )

                    surface_latency = int(
                        getattr(
                            result,
                            "latency_ms",
                            0,
                        )
                        or 0
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

                    surface_fetched = len(deals)
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
                            "v14_hunter_page":
                                hunter_page,
                        })

                        deal.metadata = metadata

                        upsert_result = await asyncio.to_thread(
                            self.db.upsert_candidate,
                            deal,
                            preliminary,
                        )

                        # Count only genuinely useful discoveries:
                        # - brand-new ASIN
                        # - meaningful price improvement
                        # - lane upgrade
                        #
                        # Repeated unchanged products no longer make a
                        # stale Amazon source look productive.
                        if upsert_result.get(
                            "new_or_reopened"
                        ):
                            surface_queued += 1
                            queued_total += 1

                except Exception as exc:
                    errors += 1

                    surface_error = (
                        f"{type(exc).__name__}:"
                        f"{exc}"
                    )

                    log.warning(
                        "ULTRA HUNTER %s/%s failed | %s:%s",
                        store,
                        surface.name,
                        type(exc).__name__,
                        exc,
                    )

                # Teach Source Brain from BOTH success and failure.
                await asyncio.to_thread(
                    self.db.source_result,
                    store,
                    surface.name,
                    surface.category,
                    surface_fetched,
                    surface_queued,
                    surface_latency,
                    surface_error,
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

                shield = inspect_deal(
                    incoming,
                    verified,
                    vmeta,
                    price_profile,
                )

                if shield.hard_block:
                    reason = (
                        "anti_fake:"
                        + ",".join(
                            shield.reasons
                        )
                    )

                    await asyncio.to_thread(
                        self.db.mark_rejected,
                        deal_key,
                        reason,
                    )

                    log.warning(
                        "ANTI-FAKE BLOCK "
                        "store=%s id=%s risk=%.1f "
                        "reasons=%s",
                        store,
                        verified.external_id,
                        shield.risk_score,
                        ",".join(
                            shield.reasons
                        ),
                    )

                    continue

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

                # FINAL AMAZON ULTRA POLICY:
                # Noon -> normal path only.
                # Amazon <65% -> normal.
                # Amazon 65-74.99% -> Ultra.
                # Amazon >=75% -> Ultra MAX priority.
                signals = int(
                    vmeta.get(
                        "verification_signals"
                    )
                    or 0
                )

                required_signals = max(
                    2,
                    int(
                        shield.required_signals
                    ),
                )

                old_live = float(
                    verified.old_price or 0
                )

                current_live = float(
                    verified.current_price or 0
                )

                irrational_price = bool(
                    old_live >= 1000
                    and current_live > 0
                    and current_live
                    <= old_live * 0.30
                    and signals >= required_signals
                    and decision.confidence
                    >= self.settings.min_confidence_ultra
                )

                hot_priority = False

                if store == "noon":
                    # Noon never enters Amazon Ultra.
                    decision.lane = Lane.NORMAL

                    if (
                        "noon_normal_only"
                        not in decision.reasons
                    ):
                        decision.reasons.append(
                            "noon_normal_only"
                        )

                elif store == "amazon":
                    strong_ultra_proof = bool(
                        signals >= required_signals
                        and decision.confidence
                        >= self.settings.min_confidence_ultra
                    )

                    if decision.real_discount >= 75.0:
                        if not strong_ultra_proof:
                            await asyncio.to_thread(
                                self.db.mark_rejected,
                                deal_key,
                                "amazon_75_needs_stronger_verification",
                            )

                            log.warning(
                                "AMAZON 75+ BLOCKED "
                                "id=%s discount=%.1f "
                                "signals=%s/%s confidence=%.2f",
                                verified.external_id,
                                decision.real_discount,
                                signals,
                                required_signals,
                                decision.confidence,
                            )

                            continue

                        decision.lane = Lane.ULTRA
                        decision.score = 100.0
                        hot_priority = True

                        if (
                            "amazon_ultra_max_75"
                            not in decision.reasons
                        ):
                            decision.reasons.append(
                                "amazon_ultra_max_75"
                            )

                    elif decision.real_discount >= 65.0:
                        if not strong_ultra_proof:
                            await asyncio.to_thread(
                                self.db.mark_rejected,
                                deal_key,
                                "amazon_65_needs_stronger_verification",
                            )

                            log.warning(
                                "AMAZON 65+ BLOCKED "
                                "id=%s discount=%.1f "
                                "signals=%s/%s confidence=%.2f",
                                verified.external_id,
                                decision.real_discount,
                                signals,
                                required_signals,
                                decision.confidence,
                            )

                            continue

                        decision.lane = Lane.ULTRA
                        decision.score = max(
                            float(decision.score or 0),
                            94.0,
                        )

                        if (
                            "amazon_ultra_65"
                            not in decision.reasons
                        ):
                            decision.reasons.append(
                                "amazon_ultra_65"
                            )

                    else:
                        decision.lane = Lane.NORMAL

                        if (
                            "amazon_below_ultra_65"
                            not in decision.reasons
                        ):
                            decision.reasons.append(
                                "amazon_below_ultra_65"
                            )

                meta = dict(verified.metadata or {})
                meta.update(vmeta)
                meta["decision_reasons"] = decision.reasons
                meta["verified_route"] = decision.lane.value
                meta["exceptional_priority"] = hot_priority
                meta["irrational_price"] = irrational_price
                meta["hot_priority"] = hot_priority
                meta["price_intelligence"] = asdict(
                    price_profile
                )
                meta["deal_score_breakdown"] = (
                    decision.score_breakdown
                )

                meta["anti_fake_shield"] = {
                    "risk_score":
                        shield.risk_score,
                    "required_signals":
                        required_signals,
                    "reasons":
                        list(shield.reasons),
                }

                if shield.reasons:
                    decision.reasons.extend(
                        reason
                        for reason in shield.reasons
                        if reason
                        not in decision.reasons
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
                log.warning("V14 CALLBACK polling retry | %s", exc)
                await asyncio.sleep(3)

    async def health_loop(self):
        while not self.stop_event.is_set():
            released = await asyncio.to_thread(self.db.release_stale_leases)
            stats = await asyncio.to_thread(self.db.stats)
            log.info(
                "HEALTH V14 released=%s stats=%s",
                released,
                json.dumps(
                    stats,
                    ensure_ascii=False,
                ),
            )

            for store, selector in self.selectors.items():
                health = await asyncio.to_thread(
                    self.db.source_health,
                    store,
                )

                ranked = sorted(
                    (
                        (
                            surface.name,
                            selector._weight(
                                surface,
                                health,
                            ),
                        )
                        for surface
                        in selector.surfaces
                    ),
                    key=lambda item: item[1],
                    reverse=True,
                )[:5]

                log.info(
                    "SOURCE BRAIN store=%s top=%s",
                    store,
                    ",".join(
                        f"{name}:{weight:.2f}"
                        for name, weight
                        in ranked
                    ),
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
            "AMAZON65 | callbacks=v14 | discovery=%ss | "
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
