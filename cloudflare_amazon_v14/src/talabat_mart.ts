/**
 * Talabat Mart location-aware offer validation (not a live crawler).
 * The Talabat consumer catalogue is delivery-address dependent. This
 * module only accepts independently collected, timestamped observations.
 * No internal/mobile APIs, location spoofing, or unverified price claims.
 */
export const TALABAT_MART_MIN_DISCOUNT = 40;
export const TALABAT_MART_MAX_DISCOUNT = 99;
export const TALABAT_MART_PRIORITY_REGION = 'el-mahalla-el-kubra';

export interface TalabatMartObservation {
  productId: string;
  title: string;
  productUrl: string;
  region: string;
  currentPrice: number;
  originalPrice: number;
  observedAt: number; // epoch milliseconds
  available: boolean;
}

export interface TalabatMartOffer extends TalabatMartObservation {
  discountPercent: number;
  priorityRegion: boolean;
}

/** Fail closed: stale, unavailable, non-Talabat or unsupported prices are rejected. */
export function validateTalabatMartOffer(
  item: TalabatMartObservation,
  now = Date.now(),
): TalabatMartOffer | null {
  if (!item || !item.available || !item.productId?.trim() || !item.title?.trim() || !item.region?.trim()) return null;
  let url: URL;
  try { url = new URL(item.productUrl); } catch { return null; }
  if (url.protocol !== 'https:' || !['talabat.com', 'www.talabat.com'].includes(url.hostname.toLowerCase())) return null;
  if (!Number.isFinite(item.currentPrice) || !Number.isFinite(item.originalPrice) || item.currentPrice <= 0 || item.originalPrice <= item.currentPrice) return null;
  if (!Number.isFinite(item.observedAt) || item.observedAt > now + 60000 || now - item.observedAt > 15 * 60 * 1000) return null;
  const discountPercent = Math.round((1 - item.currentPrice / item.originalPrice) * 10000) / 100;
  if (discountPercent < TALABAT_MART_MIN_DISCOUNT || discountPercent > TALABAT_MART_MAX_DISCOUNT) return null;
  const region = item.region.toLowerCase().replace(/[_\s]+/g, '-');
  return { ...item, discountPercent, priorityRegion: region === TALABAT_MART_PRIORITY_REGION || region === 'المحلة-الكبرى' };
}
