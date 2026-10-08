import type {
  Lane,
  PriceProfile,
  Store,
} from "./types";

export interface RankingV3 {
  version: "ranking-v3";
  tier: 1 | 2 | 3;
  strike_score: number;
  fast_strike: boolean;
  historical_rarity_score: number;
  historical_label:
    | "new_verified_low"
    | "strong_historical"
    | "near_historical_low"
    | "mature_history"
    | "insufficient_history";
  freshness_score: number;
  reasons: string[];
  components: {
    tier_bonus: number;
    discount_strength: number;
    evidence_quality: number;
    intelligence_quality: number;
    historical_rarity: number;
    freshness: number;
    urgency: number;
  };
}

function clamp(
  value: number,
  min: number,
  max: number,
): number {
  return Math.max(min, Math.min(max, value));
}

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

function rarity(
  profile: PriceProfile,
): {
  score: number;
  label: RankingV3["historical_label"];
  reasons: string[];
} {
  const reasons: string[] = [];
  let score = 0;

  if (!profile || profile.samples < 2) {
    return {
      score: 0,
      label: "insufficient_history",
      reasons,
    };
  }

  if (profile.mature_history) {
    score += Math.min(
      6,
      Math.max(
        0,
        Number(
          profile.drop_from_reference_pct || 0
        ) * 0.12,
      ),
    );
    reasons.push("mature_price_history");
  }

  if (profile.price_percentile <= 25) {
    score += 2;
    reasons.push("bottom_price_quartile");
  }

  if (profile.strong_history_signal) {
    score += 3;
    reasons.push("strong_history_signal");
  }

  if (profile.new_verified_low) {
    score += 5;
    reasons.push("new_verified_low");
  } else if (profile.near_historical_low) {
    score += 3;
    reasons.push("near_historical_low");
  }

  score =
    round1(
      clamp(score, 0, 16)
    );

  const label:
    RankingV3["historical_label"] =
      profile.new_verified_low
        ? "new_verified_low"
        : profile.strong_history_signal
          ? "strong_historical"
          : profile.near_historical_low
            ? "near_historical_low"
            : profile.mature_history
              ? "mature_history"
              : "insufficient_history";

  return {
    score,
    label,
    reasons,
  };
}

function freshnessScore(
  ageSeconds: number,
): number {
  if (ageSeconds <= 300) return 8;
  if (ageSeconds <= 900) return 6;
  if (ageSeconds <= 3600) return 3;
  if (ageSeconds <= 21600) return 1;
  return 0;
}

export function rankVerifiedDeal(args: {
  store: Store;
  lane: Lane;
  liveDiscount: number;
  confidence: number;
  decisionScore: number;
  profile: PriceProfile;
  discoveredAt: number;
  nowTs?: number;
  flash?: boolean;
  couponPercent?: number;
}): RankingV3 {
  const now =
    Math.max(
      0,
      Math.floor(
        args.nowTs ??
        Date.now() / 1000
      ),
    );

  const age =
    Math.max(
      0,
      now -
        Math.max(
          0,
          Math.floor(args.discoveredAt || 0),
        ),
    );

  const tier: 1 | 2 | 3 =
    args.store === "amazon" &&
    args.lane === "ultra" &&
    args.liveDiscount >= 75
      ? 1
      : args.lane === "ultra"
        ? 2
        : 3;

  const tierBonus =
    tier === 1
      ? 16
      : tier === 2
        ? 10
        : 0;

  const discountStrength =
    round1(
      Math.min(
        28,
        Math.max(
          0,
          args.liveDiscount
        ) * 0.30,
      )
    );

  const evidenceQuality =
    round1(
      clamp(
        args.confidence,
        0,
        1,
      ) * 18
    );

  const intelligenceQuality =
    round1(
      Math.min(
        12,
        Math.max(
          0,
          args.decisionScore
        ) * 0.12,
      )
    );

  const hist =
    rarity(args.profile);

  const freshness =
    freshnessScore(age);

  let urgency = 0;

  if (args.flash) {
    urgency += 3;
  }

  urgency += Math.min(
    3,
    Math.max(
      0,
      Number(args.couponPercent || 0)
    ) * 0.08,
  );

  urgency =
    round1(
      Math.min(5, urgency)
    );

  const strikeScore =
    round1(
      clamp(
        tierBonus +
        discountStrength +
        evidenceQuality +
        intelligenceQuality +
        hist.score +
        freshness +
        urgency,
        0,
        100,
      )
    );

  const reasons = [
    tier === 1
      ? "amazon_tier1"
      : tier === 2
        ? "ultra_tier2"
        : "normal_lane",
    ...hist.reasons,
  ];

  if (freshness >= 6) {
    reasons.push("fresh_verified_lead");
  }

  if (urgency > 0) {
    reasons.push("time_sensitive_offer");
  }

  const fastStrike =
    tier === 1 &&
    args.confidence >= 0.80 &&
    freshness >= 6 &&
    strikeScore >= 82;

  if (fastStrike) {
    reasons.push("fast_strike_ready");
  }

  return {
    version: "ranking-v3",
    tier,
    strike_score: strikeScore,
    fast_strike: fastStrike,
    historical_rarity_score:
      hist.score,
    historical_label:
      hist.label,
    freshness_score:
      freshness,
    reasons,
    components: {
      tier_bonus:
        tierBonus,
      discount_strength:
        discountStrength,
      evidence_quality:
        evidenceQuality,
      intelligence_quality:
        intelligenceQuality,
      historical_rarity:
        hist.score,
      freshness,
      urgency,
    },
  };
}
