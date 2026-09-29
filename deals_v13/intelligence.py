from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import math
import re
import statistics

from .config import Settings
from .models import DealCandidate, DealDecision, Lane
from .identity import signature, compatibility


GENERIC_TOKENS = {
    "with", "and", "for", "the", "new", "original", "official", "black", "white",
    "عرض", "خصم", "جديد", "اصلي", "أصلي", "لون", "مع", "من", "في", "على",
}

ACCESSORY_TERMS = {
    "case", "cover", "screen protector", "replacement", "remote control", "strap",
    "cable", "charger", "adapter", "stand", "حافظة", "جراب", "واقي شاشة",
    "ريموت", "كابل", "شاحن", "محول", "حامل", "قطعة غيار",
}

MODEL_RE = re.compile(r"\b[A-Z]{1,5}[- ]?\d{2,6}[A-Z0-9-]*\b", re.I)


def _tokens(title: str) -> set[str]:
    words = re.findall(r"[\w+-]{2,}", (title or "").lower(), re.UNICODE)
    return {w for w in words if w not in GENERIC_TOKENS and not w.isdigit()}


def title_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    sa, sb = signature(a), signature(b)
    ok, evidence = compatibility(sa, sb)
    if not ok:
        return 0.0
    jaccard = len(ta & tb) / max(1, len(ta | tb))
    seq = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    bonus = 0.0
    if "model_match" in evidence:
        bonus += 0.22
    if "capacity_match" in evidence:
        bonus += 0.08
    if sa.brand and sb.brand and sa.brand == sb.brand:
        bonus += 0.05
    return max(0.0, min(1.0, 0.62 * jaccard + 0.38 * seq + bonus))


def best_cross_store_match(deal: DealCandidate, rows: list[dict]) -> tuple[dict | None, float]:
    best = None
    best_sim = 0.0
    sig = signature(deal.title)
    for row in rows:
        other_title = row.get("title") or ""
        ok, _ = compatibility(sig, signature(other_title))
        if not ok:
            continue
        sim = title_similarity(deal.title, other_title)
        if sim > best_sim:
            best, best_sim = row, sim
    # Require stronger evidence for market comparisons than generic de-dup.
    if best_sim < 0.72:
        return None, best_sim
    return best, best_sim


class IntelligenceEngine:
    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def _historical_reference(prices: list[float], current: float) -> float | None:
        clean = [p for p in prices if p > 0 and p >= current]
        if len(clean) < 3:
            return None
        # Median is intentionally resistant to one inflated crossed-out price.
        return float(statistics.median(clean[:30]))

    def evaluate(
        self,
        deal: DealCandidate,
        *,
        verified: bool,
        coupon_percent: float = 0.0,
        flash: bool = False,
        anomaly: bool = False,
        history: list[float] | None = None,
        cross_store_row: dict | None = None,
        cross_store_similarity: float = 0.0,
        verification_signals: int = 0,
    ) -> DealDecision:
        current = max(0.0, float(deal.current_price or 0))
        old = float(deal.old_price or 0)
        coupon = min(90.0, max(0.0, float(coupon_percent or 0)))
        effective = round(current * (1.0 - coupon / 100.0), 2) if current else 0.0

        visible_discount = deal.discount_percent
        effective_discount = (
            round(((old - effective) / old) * 100, 2)
            if old > effective > 0 else visible_discount
        )

        hist_ref = self._historical_reference(history or [], current)
        historical_discount = (
            round(((hist_ref - effective) / hist_ref) * 100, 2)
            if hist_ref and hist_ref > effective > 0 else 0.0
        )

        cross_price = None
        cross_store = None
        market_advantage = 0.0
        if cross_store_row and cross_store_similarity >= 0.66:
            try:
                cross_price = float(cross_store_row.get("current_price") or 0)
            except Exception:
                cross_price = 0.0
            if cross_price > effective > 0:
                market_advantage = round(((cross_price - effective) / cross_price) * 100, 2)
                cross_store = str(cross_store_row.get("store") or "")

        real_discount = max(visible_discount, effective_discount, historical_discount, coupon)

        title_low = deal.title.lower()
        accessory_like = any(term in title_low for term in ACCESSORY_TERMS)
        impossible_ratio = old >= 1000 and current > 0 and current / old <= 0.035

        # Detect a probable price anomaly from independent evidence rather than
        # trusting a search-page flag.
        if not anomaly:
            if historical_discount >= 70 and verification_signals >= 2:
                anomaly = True
                reasons = ["anomaly_from_history"]
            elif market_advantage >= 65 and cross_store_similarity >= 0.80:
                anomaly = True
                reasons = ["anomaly_from_cross_store"]
            else:
                reasons = []
        else:
            reasons = []

        confidence = 0.20
        if verified:
            confidence += 0.38
            reasons.append("product_page_verified")
        if verification_signals >= 2:
            confidence += 0.10
            reasons.append("multi_signal_price")
        if old > current > 0:
            confidence += 0.08
            reasons.append("live_old_price")
        if hist_ref and historical_discount >= 10:
            confidence += 0.10
            reasons.append("history_confirms_drop")
        if cross_price and cross_store_similarity >= 0.74:
            confidence += 0.08
            reasons.append("cross_store_match")
        if coupon > 0:
            confidence += 0.04
            reasons.append(f"coupon_{coupon:g}")
        if flash:
            confidence += 0.03
            reasons.append("flash")
        if anomaly:
            confidence += 0.02
            reasons.append("anomaly")

        if accessory_like and anomaly:
            confidence -= 0.24
            anomaly = False
            reasons.append("accessory_anomaly_suppressed")
        if impossible_ratio and not (hist_ref or verification_signals >= 2 or (cross_price and cross_store_similarity >= 0.86)):
            confidence -= 0.30
            reasons.append("extreme_ratio_needs_confirmation")
        if current <= 0:
            confidence = 0.0
        confidence = round(max(0.0, min(1.0, confidence)), 3)

        score = 0.0
        score += min(48.0, real_discount * 0.58)
        score += min(15.0, market_advantage * 0.35)
        score += confidence * 24.0
        # Absolute savings matters in Egypt: saving EGP 4,000 is usually more useful
        # than the same percentage on a very cheap item, but it is capped.
        absolute_saving = max(0.0, old - effective) if old > effective > 0 else 0.0
        score += min(8.0, math.log10(absolute_saving + 1.0) * 2.0)
        if flash:
            score += 6
        if coupon:
            score += min(6.0, coupon * 0.12)
        if anomaly and confidence >= 0.85:
            score += 10
        score = round(min(100.0, score), 2)

        ultra = False
        if real_discount >= self.settings.ultra_min_discount and confidence >= self.settings.min_confidence_ultra:
            ultra = True
            reasons.append("ultra_real_discount")
        elif flash and real_discount >= 30 and confidence >= 0.82:
            ultra = True
            reasons.append("ultra_verified_flash")
        elif anomaly and confidence >= 0.90:
            ultra = True
            reasons.append("ultra_verified_anomaly")
        elif market_advantage >= 35 and real_discount >= 25 and confidence >= 0.84:
            ultra = True
            reasons.append("ultra_market_advantage")

        lane = Lane.ULTRA if ultra else Lane.NORMAL
        return DealDecision(
            lane=lane,
            score=score,
            confidence=confidence,
            real_discount=round(real_discount, 2),
            effective_price=effective,
            reasons=reasons,
            cross_store_price=cross_price or None,
            cross_store_store=cross_store,
            anomaly=anomaly,
            flash=flash,
            coupon_percent=coupon,
        )

    def acceptable(self, decision: DealDecision) -> tuple[bool, str]:
        if decision.lane == Lane.ULTRA:
            if decision.confidence < self.settings.min_confidence_ultra:
                return False, "ultra_confidence_low"
            return True, "ok"

        if decision.real_discount < self.settings.normal_min_discount:
            return False, "discount_below_normal_threshold"
        if decision.confidence < self.settings.min_confidence_normal:
            return False, "normal_confidence_low"
        return True, "ok"
