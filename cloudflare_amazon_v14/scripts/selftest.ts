import { strict as assert } from 'node:assert';
import { evaluateDeal, acceptable, preliminaryDecision, buildPriceProfile } from '../src/intelligence';
import { getSettings } from '../src/config';
import { dealQualityBand, nearDuplicateGuard } from '../src/quality';
import { rankVerifiedDeal } from '../src/ranking';
import type { DealCandidate, DealRow, Settings } from '../src/types';

// Regression test: rediscovery must not reset rejected-deal cooldown.
import { readFileSync } from 'node:fs';
const dbSource = readFileSync(new URL('../src/db.ts', import.meta.url), 'utf8');
assert.match(
  dbSource,
  /old\.state === 'rejected' && !shouldReopen \? Number\(old\.updated_at \|\| now\) : now/
);

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

const recentRow = {
  deal_key:'recent-1',
  store:'amazon',
  external_id:'B0RECENT01',
  title:'Samsung Galaxy A55 256GB 8GB RAM',
  url:'https://www.amazon.eg/dp/B0RECENT01',
  image_url:'',
  category:'mobiles',
  source:'goldbox',
  current_price:252,
  old_price:1000,
  effective_price:252,
  visible_discount:74.8,
  real_discount:74.8,
  lane:'ultra',
  score:92,
  confidence:0.90,
  state:'sent',
  discovered_at:1,
  updated_at:1,
  verified_at:1,
  sent_at:1,
  attempts:0,
  next_attempt_at:0,
  lease_owner:null,
  lease_until:0,
  last_error:'',
  metadata_json:'{}',
} as DealRow;

const currentRow = {
  ...recentRow,
  deal_key:'current-1',
  external_id:'B0CURRENT1',
  current_price:250,
  effective_price:250,
  real_discount:75,
  score:95,
  state:'verified',
  sent_at:null,
} as DealRow;

const duplicate =
  nearDuplicateGuard(
    currentRow,
    [recentRow],
  );
assert.equal(duplicate.duplicate,true);

const clearlyBetter =
  nearDuplicateGuard(
    {
      ...currentRow,
      current_price:230,
      effective_price:230,
    } as DealRow,
    [recentRow],
  );
assert.equal(clearlyBetter.duplicate,false);

const band =
  dealQualityBand(currentRow);
assert.equal(band.code,'elite');

const rarityProfile =
  buildPriceProfile(
    [600,580,620,610,590],
    250,
  );

const ranking =
  rankVerifiedDeal({
    store:'amazon',
    lane:'ultra',
    liveDiscount:75,
    confidence:0.90,
    decisionScore:100,
    profile:rarityProfile,
    discoveredAt:800,
    nowTs:1000,
  });

assert.equal(ranking.tier,1);
assert.equal(
  ranking.historical_label,
  'new_verified_low',
);
assert.ok(
  ranking.historical_rarity_score >= 10
);
assert.ok(ranking.strike_score >= 82);
assert.equal(ranking.fast_strike,true);

const slowerTier2 =
  rankVerifiedDeal({
    store:'amazon',
    lane:'ultra',
    liveDiscount:68,
    confidence:0.82,
    decisionScore:94,
    profile:buildPriceProfile([],450),
    discoveredAt:800,
    nowTs:1000,
  });

assert.equal(slowerTier2.tier,2);
assert.equal(
  slowerTier2.fast_strike,
  false,
);

console.log('V14_CLOUDFLARE_CORE_SELFTEST_PASS');

// V14_ULTRA_ALL_70_99_V1: ensure 70%+ coverage and 95% source availability.
import { AMAZON_SURFACES as allUltraSurfaces, parseAmazon as parseAmazonForUltra } from "../src/amazon";
assert.ok(allUltraSurfaces.some(s => s.name === "70flashfilter"));
assert.ok(allUltraSurfaces.some(s => s.name === "ultra70_air_conditioners"));
assert.ok(allUltraSurfaces.some(s => s.name === "ultra70_grocery"));
const ninetyFiveCard = `<div data-component-type="s-search-result" data-asin="B012345678"><h2><span>Ultra test</span></h2><span class="a-price"><span class="a-offscreen">50.00</span></span><span class="savingsPercentage">-95%</span></div>`;
const ultraParsed = parseAmazonForUltra(ninetyFiveCard, allUltraSurfaces.find(s=>s.name==="70flashfilter")!);
assert.equal(ultraParsed.length,1);

// V14_SEARCH_ATTRIBUTE_ORDER_TEST
for (const attrs of [
  'data-component-type="s-search-result" data-asin="B012345678"',
  'data-asin="B012345678" data-component-type="s-search-result"',
]) {
  const html = `<div ${attrs}><h2><span>Test product</span></h2><span class="a-price"><span class="a-offscreen">100.00</span></span></div>`;
  const parsed = parseAmazonForUltra(html, allUltraSurfaces.find(s => s.name === "70flashfilter")!);
  assert.equal(parsed.length, 1, `Failed attribute order: ${attrs}`);
}

assert.ok(Number(ultraParsed[0].old_price) > ultraParsed[0].current_price);

// V14_AMAZON_PARSER_SAFE_REGRESSION
const amazonSurface = allUltraSurfaces.find(s => s.name === "70flashfilter")!;
for (const [formatted, expected] of [
  ["EGP 1,299.50", 1299.5],
  ["EGP 1.299,50", 1299.5],
  ["١٬٢٩٩٫٥٠ ج.م.", 1299.5],
  ["1,299", 1299],
] as const) {
  const card = `<div data-asin="B012345678" data-component-type="s-search-result"><h2><span>Sample</span></h2><span class="a-price"><span class="a-offscreen">${formatted}</span></span></div>`;
  const parsed = parseAmazonForUltra(card, amazonSurface);
  assert.equal(parsed.length, 1, `Could not parse ${formatted}`);
  assert.equal(parsed[0].current_price, expected, `Incorrect price for ${formatted}`);
}
const missingPriceCard = `<div data-asin="B012345678" data-component-type="s-search-result"><h2><span>Sample</span></h2></div>`;
assert.equal(parseAmazonForUltra(missingPriceCard, amazonSurface).length, 0);
console.log("V14_AMAZON_PARSER_SAFE_REGRESSION_PASS");

// V14_AMAZON_MALFORMED_PRICE_REGRESSION
for (const malformed of ["1,29,9.50", "1,299,50", "1299,"]) {
  const card = `<div data-component-type="s-search-result" data-asin="B012345678"><h2><span>Test</span></h2><span class="a-price"><span class="a-offscreen">${malformed}</span></span></div>`;
  assert.equal(parseAmazonForUltra(card, amazonSurface).length, 0, `Malformed price accepted: ${malformed}`);
}
