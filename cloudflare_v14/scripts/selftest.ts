import { strict as assert } from 'node:assert';
import { evaluateDeal, acceptable, preliminaryDecision } from '../src/intelligence';
import { getSettings } from '../src/config';
import type { DealCandidate, Settings } from '../src/types';

const settings: Settings = {
  ultra_min_discount:65, ultra_hot_discount:75, normal_min_discount:10,
  min_confidence_normal:0.62, min_confidence_ultra:0.76,
  browser_daily_budget_ms:540000, amazon_discovery_limit:10, noon_discovery_limit:8,
  max_attempts:5, retry_base_seconds:30, lease_seconds:180,
};
assert.equal(getSettings({} as any).ultra_hot_discount,75);

const amazon: DealCandidate = { store:'amazon', external_id:'B012345678', title:'Test Product', url:'https://www.amazon.eg/dp/B012345678', current_price:450, old_price:1000 };
const d = evaluateDeal(settings, amazon, {verified:true,coupon_percent:25,verification_signals:2});
assert.equal(d.effective_price,337.5);
assert.equal(d.real_discount,66.25);
assert.equal(d.lane,'ultra');
assert.ok(d.confidence >= 0.76);
assert.equal(acceptable(settings,d)[0],true);

const noon: DealCandidate = {...amazon, store:'noon', external_id:'N12345678A', url:'https://www.noon.com/egypt-en/x/N12345678A/p/'};
const n = evaluateDeal(settings,noon,{verified:true,coupon_percent:25,verification_signals:2});
assert.equal(n.lane,'normal');
assert.ok(n.reasons.includes('noon_normal_only'));

const hotCandidate = {...amazon,current_price:250};
const hot = evaluateDeal(settings,hotCandidate,{verified:true,verification_signals:2});
assert.ok(hot.real_discount >= 75);
assert.equal(hot.lane,'ultra');

const hotPrelim = preliminaryDecision(settings,hotCandidate);
assert.equal(hotPrelim.lane,'ultra');
assert.ok(hotPrelim.reasons.includes('amazon_top_priority_probe'));
assert.equal(hotPrelim.score,95);

const tier2Prelim = preliminaryDecision(settings,{...amazon,current_price:260});
assert.equal(tier2Prelim.lane,'ultra');
assert.ok(!tier2Prelim.reasons.includes('amazon_top_priority_probe'));

console.log('V14_CLOUDFLARE_CORE_SELFTEST_PASS');
