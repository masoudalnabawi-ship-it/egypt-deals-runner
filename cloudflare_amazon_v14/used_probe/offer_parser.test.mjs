import test from 'node:test';
import assert from 'node:assert/strict';
import {parseEgyptianMoney, classifyUsedCondition, extractUsedOffers} from './offer_parser.js';

test('English EGP and Arabic prices', () => {
  assert.deepEqual(parseEgyptianMoney('EGP 2,950.00'), [2950]);
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
