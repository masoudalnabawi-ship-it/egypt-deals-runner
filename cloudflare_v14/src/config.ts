import type { Settings, V14Env } from "./types";

function num(value: string | undefined, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export function getSettings(env: V14Env): Settings {
  return {
    ultra_min_discount: Math.max(65, num(env.V14_ULTRA_MIN_DISCOUNT, 65)),
    ultra_hot_discount: Math.max(80, num(env.V14_ULTRA_HOT_DISCOUNT, 80)),
    normal_min_discount: num(env.V14_NORMAL_MIN_DISCOUNT, 10),
    min_confidence_normal: num(env.V14_MIN_CONFIDENCE_NORMAL, 0.62),
    min_confidence_ultra: num(env.V14_MIN_CONFIDENCE_ULTRA, 0.76),
    browser_daily_budget_ms: Math.max(0, num(env.V14_BROWSER_DAILY_BUDGET_MS, 540000)),
    amazon_discovery_limit: Math.max(1, Math.min(20, Math.floor(num(env.V14_AMAZON_DISCOVERY_LIMIT, 10)))),
    noon_discovery_limit: Math.max(1, Math.min(20, Math.floor(num(env.V14_NOON_DISCOVERY_LIMIT, 8)))),
    max_attempts: 5,
    retry_base_seconds: 30,
    lease_seconds: 180,
  };
}

export function normalChatId(env: V14Env): string {
  return String(env.V13_NORMAL_REVIEW_CHAT_ID || env.REVIEW_CHAT_ID || env.AMAZON_NORMAL_REVIEW_CHAT_ID || "").trim();
}

export function ultraChatId(env: V14Env): string {
  return String(env.V13_ULTRA_REVIEW_CHAT_ID || env.AMAZON_REVIEW_GROUP_ID || "").trim();
}

export function noonReviewChatId(env: V14Env): string {
  // HARD ISOLATION:
  // Noon must NEVER fall back to Amazon normal review chat.
  return String(
    env.NOON_REVIEW_BOT_CHAT_ID ||
    env.NOON_NORMAL_REVIEW_CHAT_ID ||
    ""
  ).trim();
}
