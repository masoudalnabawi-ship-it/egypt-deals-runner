import test from 'node:test';
import assert from 'node:assert/strict';
import {SOURCE_URL, sameResalePage, analyzeResaleSnapshot} from './resale_snapshot.js';

test('only exact resale destination is accepted',()=>{
  assert.equal(sameResalePage(SOURCE_URL),true);
  assert.equal(sameResalePage('https://www.amazon.eg/l/27972173031'),true);
  assert.equal(sameResalePage('https://www.amazon.eg/b?node=27972175031'),false);
  assert.equal(sameResalePage('https://example.com/b?node=27972173031'),false);
});
test('rendered markdown extracts same-origin product and category candidates',()=>{
  const x=analyzeResaleSnapshot({meta:{title:'Amazon Resale'},result:{markdown:'[Used - EGP 125](/dp/B0DBHRWRKC) [Audio](/b?node=12345678901) [bad](https://evil.example/dp/B0DYGHH7CY)',accessibilityTree:{role:'RootWebArea',children:[]}}});
  assert.equal(x.product_candidate_count,1);
  assert.equal(x.product_candidates[0].asin,'B0DBHRWRKC');
  assert.equal(x.category_link_count,1);
  assert.equal(x.verified_used_offers,0);
  assert.equal(x.resale_text_signal,true);
});
test('accessibility tree links work with missing markdown and never confirm price',()=>{
  const x=analyzeResaleSnapshot({result:{accessibilityTree:{role:'RootWebArea',children:[{role:'link',name:'Product',url:'https://www.amazon.eg/dp/B0DYGHH7CY'}]}}});
  assert.equal(x.product_candidate_count,1);
  assert.equal(x.product_candidates[0].used_offer_verified,false);
  assert.equal(x.public_posting_enabled,false);
});
test('generic Category without items is diagnosed, never interpreted as empty inventory',()=>{
  const x=analyzeResaleSnapshot({meta:{title:'Category'},result:{markdown:'# Category',accessibilityTree:{role:'RootWebArea',name:'Category'}}});
  assert.equal(x.product_candidate_count,0);
  assert.equal(x.resale_text_signal,false);
  assert.equal(x.source_title,'Category');
});
test('captcha signal prevents any publication',()=>{
  const x=analyzeResaleSnapshot({result:{markdown:'Please enter the characters to verify you are human'}});
  assert.equal(x.captcha_text_signal,true);
  assert.equal(x.public_posting_enabled,false);
});
