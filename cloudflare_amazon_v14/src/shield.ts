import type { DealCandidate, PriceProfile } from './types';
import { compatibility, signature } from './identity';

export interface ShieldResult { hard_block: boolean; required_signals: number; risk_score: number; reasons: string[]; }

export function inspectDeal(incoming: DealCandidate, verified: DealCandidate, meta: Record<string, unknown>, profile: PriceProfile | null): ShieldResult {
  const reasons: string[] = []; let risk = 0; let required = 2; let hard = false;
  const signals = Number(meta.verification_signals || 0) || 0;
  const current = Number(verified.current_price || 0); const old = Number(verified.old_price || 0);
  const liveDiscount = old > current && current > 0 ? ((old-current)/old)*100 : 0;

  const [compatible, mismatch] = compatibility(signature(incoming.title), signature(verified.title));
  if (!compatible) { hard = true; risk = 100; reasons.push(...mismatch.map(r => `identity_${r}`)); }

  const md = verified.metadata || {}; const currency = String(md.currency || '').toUpperCase().trim();
  if (currency && !['EGP','LE','L.E','L.E.'].includes(currency)) { hard = true; risk = 100; reasons.push('wrong_market_currency'); }
  if (md.in_stock === false) { hard = true; risk = 100; reasons.push('product_not_buyable'); }

  const discovery = Number(incoming.current_price || 0);
  if (discovery > 0 && current > 0) {
    const gap = Math.abs(current-discovery) / Math.max(discovery,current,1);
    if (gap >= 0.55 && liveDiscount >= 50) { risk += 18; required = Math.max(required,3); reasons.push('large_discovery_live_price_gap'); }
  }

  if (profile?.mature_history && profile.reference_price) {
    const ref = Number(profile.reference_price); const drop = Number(profile.drop_from_reference_pct || 0);
    if (old > ref*2.25 && drop < 20) { hard = true; risk = 100; reasons.push('inflated_reference_price'); }
    else if (old > ref*1.65 && drop < 12) { risk += 30; required = Math.max(required,3); reasons.push('suspicious_old_price_vs_history'); }
    if (current < ref*0.18 && !profile.strong_history_signal) { risk += 25; required = Math.max(required,3); reasons.push('extreme_current_vs_history'); }
  }

  const amazonSavings = Number(meta.amazon_savings_percent || 0);
  const directAmazon = verified.store === 'amazon' && amazonSavings >= 70 && Math.abs(amazonSavings-liveDiscount) <= 4;
  const strongHistory = Boolean(profile?.strong_history_signal);
  if (liveDiscount >= 80 && !(directAmazon || strongHistory || signals >= 3)) { required = Math.max(required,3); risk += 25; reasons.push('extreme_discount_needs_extra_confirmation'); }
  if (liveDiscount >= 95) { required = Math.max(required,3); risk += 15; reasons.push('ultra_extreme_ratio'); }

  return { hard_block: hard, required_signals: required, risk_score: Math.round(Math.max(0,Math.min(100,risk))*100)/100, reasons: [...new Set(reasons)] };
}
