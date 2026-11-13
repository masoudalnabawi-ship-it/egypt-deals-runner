import test from 'node:test';
import assert from 'node:assert/strict';
import {parseEgyptianMoney, classifyUsedCondition, extractUsedOffers, extractUsedFromProductPage} from './offer_parser.js';

test('English EGP and Arabic prices', () => {
  assert.deepEqual(parseEgyptianMoney('EGP 2,950.00'), [2950]);
  assert.deepEqual(parseEgyptianMoney('EGP2,950.00'), [2950]);
  assert.deepEqual(parseEgyptianMoney('EGP2950'), [2950]);
  assert.deepEqual(parseEgyptianMoney('2,950.00 EGP'), [2950]);
  assert.deepEqual(parseEgyptianMoney('١٬٢٩٩٫٥٠ جنيه'), [1299.5]);
  assert.deepEqual(parseEgyptianMoney('ج.م. 850.00'), [850]);
});
test('used condition must be explicit', () => {
  assert.equal(classifyUsedCondition('New, very good price'), null);
  assert.equal(classifyUsedCondition('Used - Like New'), 'USED_LIKE_NEW');
  assert.equal(classifyUsedCondition('مستعمل - جيد جدا'), 'USED_VERY_GOOD');
});
test('one used card yields one candidate, never published proof', () => {
  const x = extractUsedOffers([{text:'Used - Very Good EGP 1,899.00'}], 'https://www.amazon.eg/gp/offer-listing/B0DYGHH7CY?condition=used');
  assert.equal(x.length, 1);
  assert.equal(x[0].price, 1899);
  assert.equal(x[0].verified_checkout, false);
  assert.deepEqual(extractUsedOffers([{text:'New EGP 1,000.00'}], 'x'), []);
  assert.deepEqual(extractUsedOffers([{text:'New & Used from EGP 1,000'}], 'x'), []);
});
test('multiple prices require manual evidence review', () => {
  const x = extractUsedOffers([{text:'Used - Good EGP 1,200.00 shipping EGP 40.00'}], 'x');
  assert.equal(x[0].price, null);
  assert.equal(x[0].status, 'PRICE_AMBIGUOUS');
});


test('main product page: used-specific section is a candidate, not verified', () => {
  const rows = [{selector: '#usedBuyBox', samples: ['Used - Like New EGP 27.78']}];
  const out = extractUsedFromProductPage(rows, 'https://www.amazon.eg/dp/B0DYGHH7CY');
  assert.equal(out.length, 1);
  assert.equal(out[0].price, 27.78);
  assert.equal(out[0].condition, 'USED_LIKE_NEW');
  assert.equal(out[0].verified_checkout, false);
  assert.equal(out[0].verified_stock, false);
});

test('generic new/used navigation and new buybox never prove used deal', () => {
  const rows = [
    {selector:'#olp_feature_div', samples:['New & Used from EGP 27.78']},
    {selector:'#newBuyBoxPrice', samples:['EGP 2950.00']},
    {selector:'#availability', samples:['In Stock']},
    {selector:'#usedAccordionRow', samples:['New & Used from EGP 27.78']},
  ];
  assert.deepEqual(extractUsedFromProductPage(rows, 'https://www.amazon.eg/dp/B0DYGHH7CY'), []);
});

test('used price-only ID accepted as tentative price; deduplicate nested sections', () => {
  const rows = [
    {selector:'#usedBuyBox', samples:['Used - Good EGP 1200']},
    {selector:'#usedBuyBoxPrice', samples:['EGP 1200']},
  ];
  const out = extractUsedFromProductPage(rows, 'x');
  assert.equal(out.length, 1);
  assert.equal(out[0].condition, 'USED_GOOD');
  assert.equal(out[0].price, 1200);
});

test('multiple price amounts and renewed products are not a priced used offer', () => {
  const rows = [
    {selector:'#usedAccordionRow', samples:['Used - Very Good EGP 1200 + delivery EGP 90']},
    {selector:'#usedOffer', samples:['Renewed EGP 900']},
  ];
  assert.deepEqual(extractUsedFromProductPage(rows, 'x'), []);
});

test('Arabic used-only section may show price but condition remains unspecified', () => {
  const out = extractUsedFromProductPage(
    [{selector:'#usedAccordionRow', samples:['العرض المستعمل: ١٬٤٩٩٫٥٠ جنيه']}], 'x');
  assert.equal(out.length, 1);
  assert.equal(out[0].price, 1499.5);
  assert.equal(out[0].condition, 'USED_UNSPECIFIED');
});
