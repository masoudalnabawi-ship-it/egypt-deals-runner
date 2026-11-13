import test from 'node:test';
import assert from 'node:assert/strict';
import {extractResaleListing} from './resale_source.js';
test('product link attributes extracted when HTML absent',()=>{
 const x=extractResaleListing({result:[{selector:'a[href*="/dp/"]',results:[{attributes:[{name:'href',value:'/dp/B0DYGHH7CY'}],text:'EGP950'}]}]});
 assert.equal(x.products.length,1);assert.equal(x.products[0].asin,'B0DYGHH7CY');assert.equal(x.products[0].used_price_verified,false);
});
test('direct href extracted when HTML absent',()=>{
 const x=extractResaleListing({result:[{selector:'#search a[href*="/dp/"]',results:[{href:'https://www.amazon.eg/dp/B0DYGHH7CY?th=1',text:'EGP 950'}]}]});
 assert.equal(x.products.length,1);
});
test('external link cannot create a product candidate',()=>{
 const x=extractResaleListing({result:[{selector:'a[href*="/dp/"]',results:[{href:'https://fake.example/dp/B0DYGHH7CY',text:'Used EGP 20'}]}]});
 assert.equal(x.products.length,0);
});
