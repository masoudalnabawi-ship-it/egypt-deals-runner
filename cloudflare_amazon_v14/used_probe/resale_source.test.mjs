import test from 'node:test';
import assert from 'node:assert/strict';
import {extractResaleListing} from './resale_source.js';

test('listing data asin yields candidate, never proof',()=>{
 const x=extractResaleListing({result:[{selector:'[data-asin]',results:[{attributes:[{name:'data-asin',value:'B0DYGHH7CY'}],text:'Used - Like New EGP2,100.00'}]}]});
 assert.equal(x.products.length,1);assert.equal(x.products[0].asin,'B0DYGHH7CY');
 assert.deepEqual(x.products[0].display_price_candidates,[2100]);
 assert.equal(x.products[0].used_price_verified,false);
});
test('normal unrelated elements and invalid asin ignored',()=>{
 const x=extractResaleListing({result:[{selector:'h1',results:[{text:'Amazon Resale EGP20'}]},{selector:'div[data-asin]',results:[{attributes:[{name:'data-asin',value:'BAD'}],text:'EGP 10'}]}]});
 assert.equal(x.products.length,0);
});
test('href extracts asin and duplicate is deduped',()=>{
 const x=extractResaleListing({result:[{selector:'a[href*="/dp/"]',results:[
 {html:'<a href="https://www.amazon.eg/dp/B0DYGHH7CY">example</a>',text:'Used EGP500'},
 {html:'<a href="/dp/B0DYGHH7CY">duplicate</a>',text:'EGP200'}]}]});
 assert.equal(x.products.length,1);assert.equal(x.products[0].asin,'B0DYGHH7CY');
});
test('listing without explicit condition remains unverified',()=>{
 const x=extractResaleListing({result:[{selector:'div.s-card-container',results:[{html:'<div data-asin="B0DYGHH7CY">test</div>',text:'EGP199'}]}]});
 assert.equal(x.products[0].condition_signal,null);
 assert.equal(x.products[0].stock_verified,false);
});
