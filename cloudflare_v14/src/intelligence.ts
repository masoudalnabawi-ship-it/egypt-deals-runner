import type { DealCandidate, DealDecision, PriceProfile, Settings } from "./types";
import { clamp, discountPercent, round2 } from "./util";

const ACCESSORY_TERMS = [
  "case","cover","screen protector","replacement","remote control","strap",
  "cable","charger","adapter","stand","حافظة","جراب","واقي شاشة","ريموت",
  "كابل","شاحن","محول","حامل","قطعة غيار",
];

function median(values: number[]): number {
  const a = [...values].sort((x, y) => x - y);
  if (!a.length) return 0;
  const m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}

function pctDrop(reference: number, current: number): number {
  if (!(reference > current && current > 0)) return 0;
  return round2(clamp(((reference - current) / reference) * 100, 0, 99));
}

export function buildPriceProfile(history: number[] | undefined, current: number): PriceProfile {
  const clean = (history || []).map(Number).filter(x => Number.isFinite(x) && x > 0).slice(0, 60);
  const unique = new Set(clean.map(x => round2(x))).size;
  if (!(current > 0) || !clean.length) {
    return {
      samples: clean.length, unique_prices: unique, min_price: null, max_price: null,
      median_price: null, mean_price: null, reference_price: null,
      drop_from_reference_pct: 0, drop_from_median_pct: 0, price_percentile: 100,
      new_verified_low: false, near_historical_low: false, mature_history: false,
      strong_history_signal: false,
    };
  }
  const samples = clean.length;
  const minimum = Math.min(...clean);
  const maximum = Math.max(...clean);
  const med = median(clean);
  const mean = clean.reduce((a, b) => a + b, 0) / samples;
  const reference = samples >= 3 ? med : null;
  const dropRef = reference ? pctDrop(reference, current) : 0;
  const dropMedian = pctDrop(med, current);
  const lower = clean.filter(p => p <= current * 1.002).length;
  const percentile = Math.round((lower / samples) * 1000) / 10;
  const newLow = samples >= 2 && current < minimum * 0.995;
  const nearLow = samples >= 2 && current <= minimum * 1.02;
  const mature = samples >= 5 && unique >= 2;
  const strong = mature && (dropRef >= 20 || newLow) && percentile <= 25;
  return {
    samples, unique_prices: unique, min_price: round2(minimum), max_price: round2(maximum),
    median_price: round2(med), mean_price: round2(mean), reference_price: reference ? round2(reference) : null,
    drop_from_reference_pct: dropRef, drop_from_median_pct: dropMedian, price_percentile: percentile,
    new_verified_low: newLow, near_historical_low: nearLow, mature_history: mature,
    strong_history_signal: strong,
  };
}

function smartDealScore(args: {
  realDiscount: number; confidence: number; verificationSignals: number; effectivePrice: number;
  oldPrice: number; marketAdvantage: number; profile?: PriceProfile | null; flash: boolean;
  coupon: number; anomaly: boolean; accessoryLike: boolean; impossibleRatio: boolean;
}): Record<string, number> {
  const discount = Math.min(30, Math.max(0, args.realDiscount) * 0.5);
  const evidence = Math.min(20, Math.max(0, args.confidence) * 14 + Math.min(6, Math.max(0, args.verificationSignals) * 3));
  let history = 0;
  if (args.profile) {
    history += Math.min(10, Math.max(0, args.profile.drop_from_reference_pct) * 0.18);
    if (args.profile.new_verified_low) history += 3;
    if (args.profile.strong_history_signal) history += 2;
  }
  history = Math.min(15, history);
  const market = Math.min(10, Math.max(0, args.marketAdvantage) * 0.22);
  const saving = args.oldPrice > args.effectivePrice && args.effectivePrice > 0 ? Math.max(0, args.oldPrice - args.effectivePrice) : 0;
  const value = Math.min(10, saving > 0 ? Math.log10(saving + 1) * 2.5 : 0);
  const urgency = args.flash ? 5 : 0;
  const anomalyScore = args.anomaly && args.confidence >= 0.85 ? 5 : 0;
  const couponValue = Math.min(5, Math.max(0, args.coupon) * 0.1);
  let penalties = 0;
  if (args.accessoryLike && args.anomaly) penalties += 8;
  if (args.impossibleRatio && args.verificationSignals < 2 && !args.profile?.strong_history_signal) penalties += 12;
  const total = round2(clamp(discount + evidence + history + market + value + urgency + anomalyScore + couponValue - penalties, 0, 100));
  return {
    discount_strength: round2(discount), evidence_quality: round2(evidence), historical_rarity: round2(history),
    market_advantage: round2(market), absolute_value: round2(value), urgency: round2(urgency),
    anomaly_quality: round2(anomalyScore), coupon_value: round2(couponValue), penalties: round2(penalties), total,
  };
}

export function evaluateDeal(
  settings: Settings,
  deal: DealCandidate,
  opts: {
    verified: boolean;
    coupon_percent?: number;
    flash?: boolean;
    anomaly?: boolean;
    history?: number[];
    verification_signals?: number;
    price_profile?: PriceProfile | null;
    cross_store_price?: number | null;
    cross_store_store?: string | null;
    cross_store_similarity?: number;
  },
): DealDecision {
  const current = Math.max(0, Number(deal.current_price || 0));
  const old = Number(deal.old_price || 0);
  const coupon = clamp(Number(opts.coupon_percent || 0), 0, 99);
  const effective = current ? round2(current * (1 - coupon / 100)) : 0;
  const visible = discountPercent(deal);
  const effectiveDiscount = old > effective && effective > 0 ? round2(((old - effective) / old) * 100) : visible;
  const profile = opts.price_profile || buildPriceProfile(opts.history || [], current);
  const histRef = profile.reference_price && profile.samples >= 3 ? profile.reference_price : null;
  let historical = histRef && histRef > effective && effective > 0 ? round2(((histRef - effective) / histRef) * 100) : 0;
  historical = Math.max(historical, profile.drop_from_reference_pct || 0);

  const similarity = Number(opts.cross_store_similarity || 0);
  const crossPrice = Number(opts.cross_store_price || 0);
  let marketAdvantage = 0;
  let crossStore: string | null = null;
  if (similarity >= 0.66 && crossPrice > effective && effective > 0) {
    marketAdvantage = round2(((crossPrice - effective) / crossPrice) * 100);
    crossStore = opts.cross_store_store || null;
  }

  const realDiscount = Math.max(visible, effectiveDiscount, historical, coupon);
  const lowTitle = String(deal.title || "").toLowerCase();
  const accessoryLike = ACCESSORY_TERMS.some(x => lowTitle.includes(x));
  const impossibleRatio = old >= 1000 && current > 0 && current / old <= 0.035;
  const signals = Math.max(0, Math.floor(opts.verification_signals || 0));
  let anomaly = Boolean(opts.anomaly);
  const reasons: string[] = [];
  if (!anomaly) {
    if (historical >= 70 && signals >= 2) { anomaly = true; reasons.push("anomaly_from_history"); }
    else if (marketAdvantage >= 65 && similarity >= 0.8) { anomaly = true; reasons.push("anomaly_from_cross_store"); }
  }

  let confidence = 0.20;
  if (opts.verified) { confidence += 0.38; reasons.push("product_page_verified"); }
  if (signals >= 2) { confidence += 0.10; reasons.push("multi_signal_price"); }
  if (old > current && current > 0) { confidence += 0.08; reasons.push("live_old_price"); }
  if (histRef && historical >= 10) { confidence += 0.10; reasons.push("history_confirms_drop"); }
  if (profile.mature_history) reasons.push("mature_verified_price_history");
  if (profile.new_verified_low) { confidence += 0.04; reasons.push("new_verified_low"); }
  else if (profile.near_historical_low && profile.samples >= 5) { confidence += 0.02; reasons.push("near_verified_low"); }
  if (profile.strong_history_signal) { confidence += 0.04; reasons.push("strong_history_signal"); }
  if (crossPrice && similarity >= 0.74) { confidence += 0.08; reasons.push("cross_store_match"); }
  if (coupon > 0) { confidence += 0.04; reasons.push(`coupon_${coupon}`); }
  if (opts.flash) { confidence += 0.03; reasons.push("flash"); }
  if (anomaly) { confidence += 0.02; reasons.push("anomaly"); }
  if (accessoryLike && anomaly) { confidence -= 0.24; anomaly = false; reasons.push("accessory_anomaly_suppressed"); }
  if (impossibleRatio && !(histRef || signals >= 2 || (crossPrice && similarity >= 0.86))) {
    confidence -= 0.30; reasons.push("extreme_ratio_needs_confirmation");
  }
  if (current <= 0) confidence = 0;
  confidence = Math.round(clamp(confidence, 0, 1) * 1000) / 1000;

  const breakdown = smartDealScore({
    realDiscount, confidence, verificationSignals: signals, effectivePrice: effective,
    oldPrice: old, marketAdvantage, profile, flash: Boolean(opts.flash), coupon,
    anomaly, accessoryLike, impossibleRatio,
  });

  let lane: "normal" | "ultra" = "normal";
  if (deal.store === "amazon" && realDiscount >= settings.ultra_min_discount && confidence >= settings.min_confidence_ultra) {
    lane = "ultra";
    reasons.push("amazon_ultra_65");
  } else if (deal.store === "noon") {
    reasons.push("noon_normal_only");
  }

  return {
    lane, score: breakdown.total, confidence, real_discount: round2(realDiscount), effective_price: effective,
    reasons, cross_store_price: crossPrice || null, cross_store_store: crossStore,
    anomaly, flash: Boolean(opts.flash), coupon_percent: coupon, score_breakdown: breakdown,
  };
}

export function acceptable(settings: Settings, decision: DealDecision): [boolean, string] {
  if (decision.lane === "ultra") {
    if (decision.confidence < settings.min_confidence_ultra) return [false, "ultra_confidence_low"];
    return [true, "ok"];
  }
  if (decision.real_discount < settings.normal_min_discount) return [false, "discount_below_normal_threshold"];
  if (decision.confidence < settings.min_confidence_normal) return [false, "normal_confidence_low"];
  return [true, "ok"];
}

export function preliminaryDecision(settings: Settings, deal: DealCandidate): DealDecision {
  const visible = discountPercent(deal);
  const meta = deal.metadata || {};
  const promo = Boolean(meta.coupon_hint || meta.flash_hint || meta.promo_hint || meta.coupon_probe || meta.goldbox);
  let lane: "normal" | "ultra" = "normal";
  if (deal.store === "amazon" && visible >= settings.ultra_min_discount) lane = "ultra";
  const score = Math.min(100, visible + (promo ? 18 : 0) + (visible >= settings.ultra_hot_discount ? 20 : 0));
  return {
    lane,
    score: round2(score),
    confidence: 0,
    real_discount: visible,
    effective_price: deal.current_price,
    reasons: [deal.store === "noon" ? "noon_normal_only" : visible >= 65 ? "amazon_visible_65_probe" : promo ? "promo_probe" : "normal_discovery"],
    anomaly: false,
    flash: Boolean(meta.flash_hint),
    coupon_percent: 0,
    score_breakdown: {},
  };
}
