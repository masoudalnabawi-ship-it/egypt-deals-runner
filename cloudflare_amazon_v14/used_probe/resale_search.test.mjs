import test from 'node:test';
import assert from 'node:assert/strict';
import {FIXED_SEARCH_URL,validResaleSearchDestination,inspectSearchData} from './resale_search.js';
test('fixed node search canonical Amazon Egypt',()=>{
 assert.equal(validResaleSearchDestination(FIXED_SEARCH_URL),true);
 assert.equal(validResaleSearchDestination('https://www.amazon.eg/s?rh=n%3A27972175031&page=2'),true);
});
test('refuses other sections, external redirects and login',()=>{
 for(const u of ['https://evil.example/s?rh=n%3A27972175031','https://www.amazon.eg/s?rh=n%3A1234','https://www.amazon.eg/ap/signin?rh=n%3A27972175031','http://www.amazon.eg/s?rh=n%3A27972175031']){
  assert.equal(validResaleSearchDestination(u),false,u);
 }
});
test('one result candidate never verified as used',()=>{
 const x=inspectSearchData({result:[{selector:'div[data-asin]',results:[{attributes:[{name:'data-asin',value:'B0DYGHH7CY'}],text:'EGP 1,000'}]}]});
 assert.equal(x.product_count,1);assert.equal(x.verified_used_offers,0);
 assert.equal(x.product_candidates[0].used_price_verified,false);
});
test('generic category page does not become a used deal',()=>{
 const x=inspectSearchData({result:[{selector:'title',results:[{text:'Category'}]},{selector:'a[href]',results:[{attributes:[{name:'href',value:'/b?node=2345678'}],text:'Tools'}]}]});
 assert.equal(x.product_count,0);assert.equal(x.page_context[0].sample,'Category');
});
test('explicit captcha is noted without retries',()=>{
 const x=inspectSearchData({result:[{selector:'#captchacharacters',results:[{text:''}]}]});
 assert.equal(x.has_captcha_elements,true);
});
