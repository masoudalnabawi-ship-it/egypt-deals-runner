/** Inspect one constrained Amazon Egypt search surface. Discovery != used-stock proof. */
import {extractResaleListing} from './resale_source.js';

export const FIXED_SEARCH_URL = 'https://www.amazon.eg/s?rh=n%3A27972175031';
export function validResaleSearchDestination(value) {
  try {
    const u=new URL(String(value));
    return u.protocol==='https:' && u.hostname==='www.amazon.eg' && !u.username && !u.password && !u.port
      && /^\/s\/?$/.test(u.pathname)
      && (u.searchParams.get('rh')||'').split(',').includes('n:27972175031');
  } catch { return false; }
}
export function inspectSearchData(data){
  const groups=Array.isArray(data?.result)?data.result:[];
  const hasCaptcha=groups.some(g=>/captcha|captchacharacters/i.test(String(g?.selector||'')) && g?.results?.length>0);
  const context=[];
  for(const g of groups){
    if(!/^(title|h1|#search|#search\.main-slot|#search\.s-desktop-content)$/.test(String(g?.selector||'')))continue;
    for(const entry of (Array.isArray(g?.results)?g.results:[]).slice(0,1)){
      const v=String(entry?.text||'').replace(/\s+/g,' ').trim();
      if(v)context.push({selector:g.selector,sample:v.slice(0,240)});
    }
  }
  const found=extractResaleListing(data,24);
  return {has_captcha_elements:hasCaptcha, inspected_elements:found.inspected_elements,
    product_count:found.products.length,
    product_candidates:found.products.slice(0,24),page_context:context.slice(0,5),
    // A constrained search URL alone cannot establish a Resale seller, condition or stock.
    verified_used_offers:0};
}
