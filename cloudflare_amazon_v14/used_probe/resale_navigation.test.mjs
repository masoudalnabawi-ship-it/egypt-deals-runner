import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeAmazonCategoryLink, analyzeResaleNavigation} from './resale_navigation.js';
const base = 'https://www.amazon.eg/b?node=27972175031';

test('category node links allowed, storefront self and external links excluded', () => {
  assert.equal(normalizeAmazonCategoryLink('/b?node=1234567890', base)?.kind, 'browse_node');
  assert.equal(normalizeAmazonCategoryLink('/gp/browse.html?node=1234567890', base)?.kind, 'browse_node');
  assert.equal(normalizeAmazonCategoryLink('/b?node=27972175031', base), null);
  assert.equal(normalizeAmazonCategoryLink('https://other.example/b?node=12345', base), null);
  assert.equal(normalizeAmazonCategoryLink('http://www.amazon.eg/b?node=12345', base), null);
  assert.equal(normalizeAmazonCategoryLink('/ap/signin?node=12345', base), null);
});

test('only constrained result pages allowed', () => {
  assert.equal(normalizeAmazonCategoryLink('/s?rh=n%3A123456789&ref=x', base)?.kind, 'category_results');
  assert.equal(normalizeAmazonCategoryLink('/s?k=computer', base), null);
  assert.equal(normalizeAmazonCategoryLink('/dp/B0DYGHH7CY', base), null);
});

test('parses attrs, HTML href, dedupes, avoids header-only category follow', () => {
  const data={result:[
    {selector:'h1', results:[{text:'Amazon Resale'}]},
    {selector:'a[href]',results:[{attributes:[{name:'href',value:'/b?node=1234567890'}],text:'Header toys'}]},
    {selector:'main a[href]',results:[{html:'<a href="/b?node=5555555555&ref=nav">Home & Kitchen</a>',text:'Home & Kitchen'},
      {attributes:{href:'/b?node=5555555555'},text:'Same'}]},
  ]};
  const x=analyzeResaleNavigation(data, base);
  assert.equal(x.anchor_elements,3);
  assert.equal(x.navigation_total_found,2);
  assert.equal(x.category_probe_url,'https://www.amazon.eg/b?node=5555555555');
  assert.equal(x.product_count,0);
});

test('no anchors is honest empty diagnostic, never proof of empty Amazon catalog', () => {
  const x=analyzeResaleNavigation({result:[{selector:'h1',results:[{text:'Hello'}]}]},base);
  assert.equal(x.navigation_total_found,0);
  assert.equal(x.category_probe_url,null);
  assert.equal(x.has_captcha_elements,false);
});

test('captcha elements detected, no category followed', () => {
  const x=analyzeResaleNavigation({result:[{selector:'#captchacharacters',results:[{text:''}]}]},base);
  assert.equal(x.has_captcha_elements,true);
  assert.equal(x.category_probe_url,null);
});
