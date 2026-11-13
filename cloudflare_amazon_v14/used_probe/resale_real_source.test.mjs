import test from 'node:test';
import assert from 'node:assert/strict';
import {validResaleRealDestination,inspectRealResaleLanding} from './resale_real_source.js';
test('allows documented direct store but not prior node or unrelated pages',()=>{
  assert.equal(validResaleRealDestination('https://www.amazon.eg/l/27972173031'),true);
  assert.equal(validResaleRealDestination('https://www.amazon.eg/b?node=27972173031'),true);
  assert.equal(validResaleRealDestination('https://www.amazon.eg/s?rh=n%3A27972173031'),true);
  assert.equal(validResaleRealDestination('https://www.amazon.eg/b?node=27972175031'),false);
  assert.equal(validResaleRealDestination('https://evil.example/l/27972173031'),false);
  assert.equal(validResaleRealDestination('https://www.amazon.eg/ap/signin'),false);
});
test('single listing yields only an unverified ASIN with exact Amazon URL',()=>{
  const p=inspectRealResaleLanding({result:[{selector:'a[href*="/dp/"]',results:[{attributes:[{name:'href',value:'/dp/B0DYGHH7CY'}],text:'Used EGP25'}]}]});
  assert.equal(p.candidate_count,1);
  assert.equal(p.candidates[0].asin,'B0DYGHH7CY');
  assert.equal(p.candidates[0].used_price_verified,false);
  assert.equal(p.verified_used_offers,0);
});
test('does not turn external product links into Amazon ASIN',()=>{
  const p=inspectRealResaleLanding({result:[{selector:'a[href*="/dp/"]',results:[{href:'https://evil.example/dp/B0DYGHH7CY'}]}]});
  assert.equal(p.candidate_count,0);
});
test('recognized content navigation remains an unverified category candidate',()=>{
  const p=inspectRealResaleLanding({result:[{selector:'#mainContent a[href]',results:[{href:'/l/98765432101'},{href:'/ap/signin'},{href:'https://evil.example/l/98765432101'}]}]});
  assert.deepEqual(p.category_link_candidates,['https://www.amazon.eg/l/98765432101']);
});
test('empty/generic category and captcha accurately recorded',()=>{
  let p=inspectRealResaleLanding({result:[{selector:'title',results:[{text:'Category'}]},{selector:'a[href]',results:[{href:'/gp/help'}]}]});
  assert.equal(p.candidate_count,0);
  assert.equal(p.page_context[0].sample,'Category');
  p=inspectRealResaleLanding({result:[{selector:'#captchacharacters',results:[{text:''}]}]});
  assert.equal(p.has_captcha_elements,true);
});
