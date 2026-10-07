export type Store = "amazon" | "noon";
export type Lane = "normal" | "ultra";
export type DealState = "pending" | "verifying" | "verified" | "delivering" | "sent" | "retry" | "rejected";

export interface DealCandidate {
  store: Store;
  external_id: string;
  title: string;
  url: string;
  current_price: number;
  old_price?: number | null;
  image_url?: string;
  category?: string;
  source?: string;
  discovered_at?: number;
  metadata?: Record<string, unknown>;
}

export interface DealDecision {
  lane: Lane;
  score: number;
  confidence: number;
  real_discount: number;
  effective_price: number;
  reasons: string[];
  cross_store_price?: number | null;
  cross_store_store?: string | null;
  anomaly: boolean;
  flash: boolean;
  coupon_percent: number;
  score_breakdown: Record<string, number>;
}

export interface PriceProfile {
  samples: number;
  unique_prices: number;
  min_price: number | null;
  max_price: number | null;
  median_price: number | null;
  mean_price: number | null;
  reference_price: number | null;
  drop_from_reference_pct: number;
  drop_from_median_pct: number;
  price_percentile: number;
  new_verified_low: boolean;
  near_historical_low: boolean;
  mature_history: boolean;
  strong_history_signal: boolean;
}

export interface Surface {
  name: string;
  category: string;
  url: string;
  priority?: number;
}

export interface DealRow extends Record<string, unknown> {
  deal_key: string;
  store: Store;
  external_id: string;
  title: string;
  url: string;
  image_url: string;
  category: string;
  source: string;
  current_price: number;
  old_price: number | null;
  effective_price: number | null;
  visible_discount: number;
  real_discount: number;
  lane: Lane;
  score: number;
  confidence: number;
  state: DealState;
  discovered_at: number;
  updated_at: number;
  verified_at: number | null;
  sent_at: number | null;
  attempts: number;
  next_attempt_at: number;
  lease_owner: string | null;
  lease_until: number;
  last_error: string;
  metadata_json: string;
}

export interface V14Env {
  egypt_deals_v14_db: D1Database;
  BROWSER: any;
  JOBS: Queue<JobMessage>;

  TELEGRAM_BOT_TOKEN?: string;
  V13_NORMAL_REVIEW_CHAT_ID?: string;
  REVIEW_CHAT_ID?: string;
  AMAZON_NORMAL_REVIEW_CHAT_ID?: string;
  V13_ULTRA_REVIEW_CHAT_ID?: string;
  AMAZON_REVIEW_GROUP_ID?: string;
  NOON_REVIEW_BOT_TOKEN?: string;
  NOON_REVIEW_BOT_CHAT_ID?: string;
  NOON_NORMAL_REVIEW_CHAT_ID?: string;
  AMAZON_CHANNEL_ID?: string;
  NOON_CHANNEL_ID?: string;
  TELEGRAM_CHANNEL_ID?: string;
  TELEGRAM_WEBHOOK_SECRET?: string;
  NOON_TELEGRAM_WEBHOOK_SECRET?: string;
  V14_ADMIN_KEY?: string;
  V14_GITHUB_PIPELINE_KEY?: string;

  V14_ULTRA_MIN_DISCOUNT?: string;
  V14_ULTRA_HOT_DISCOUNT?: string;
  V14_NORMAL_MIN_DISCOUNT?: string;
  V14_MIN_CONFIDENCE_NORMAL?: string;
  V14_MIN_CONFIDENCE_ULTRA?: string;
  V14_BROWSER_DAILY_BUDGET_MS?: string;
  V14_AMAZON_DISCOVERY_LIMIT?: string;
  V14_NOON_DISCOVERY_LIMIT?: string;
}

export interface Settings {
  ultra_min_discount: number;
  ultra_hot_discount: number;
  normal_min_discount: number;
  min_confidence_normal: number;
  min_confidence_ultra: number;
  browser_daily_budget_ms: number;
  amazon_discovery_limit: number;
  noon_discovery_limit: number;
  max_attempts: number;
  retry_base_seconds: number;
  lease_seconds: number;
}

export type JobMessage = { type: "cycle"; scheduled_at: number };
