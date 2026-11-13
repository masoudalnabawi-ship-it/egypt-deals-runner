/** Conservative ASIN discovery from Amazon.eg Resale listing. Never confirms purchase. */
import {parseEgyptianMoney, classifyUsedCondition} from './offer_parser.js';

const ASIN=/^[A-Z0-9]{10}$/;
function textClean(t){return String(t||'').replace(/\s+/g,' ').trim();}
function asinFrom(item){
  const attrs=Array.isArray(item?.attributes)?item.attributes:[];
  for(const a of attrs){
    if(String(a?.name).toLowerCase()==='data-asin'){
      const id=String(a?.value||'').toUpperCase();
      if(ASIN.test(id))return id;
    }
  }
  // RESALE_LINK_ATTR_V7: browser scraper often returns href as an attribute, not HTML.
  const asAmazonProductHref=(value)=>{
    try{
      const u=new URL(String(value||''),'https://www.amazon.eg');
      if(u.protocol!=='https:' || u.hostname!=='www.amazon.eg' || u.username || u.password || u.port)return null;
      const m=u.pathname.match(/^\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:\/|$)/i);
      return m?m[1].toUpperCase():null;
    }catch{return null;}
  };
  const hrefs=[item?.href,
    Array.isArray(item?.attributes)?item.attributes.find(x=>String(x?.name||'').toLowerCase()==='href')?.value:null,
    !Array.isArray(item?.attributes)?item?.attributes?.href:null];
  for(const h of hrefs){const asin=asAmazonProductHref(h);if(asin)return asin;}
  const html=String(item?.html||'');
  const data=html.match(/\bdata-asin\s*=\s*["']([A-Z0-9]{10})["']/i);
  if(data)return data[1].toUpperCase();
  const href=html.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[\/?#"'&]|$)/i);
  return href?href[1].toUpperCase():null;
}
export function extractResaleListing(scrapeResult, limit=24){
  const unique=new Map();
  const groups=Array.isArray(scrapeResult?.result)?scrapeResult.result:[];
  let observed=0;
  for (const group of groups){
    if(!/data-asin|s-card-container|s-result-item|href\*=/i.test(String(group?.selector||'')))continue;
    for(const item of (Array.isArray(group?.results)?group.results:[]).slice(0,150)){
      observed++;
      const asin=asinFrom(item);
      if(!asin||unique.has(asin))continue;
      const clean=textClean(item?.text).slice(0,1200);
      // An ASIN discovered on a Resale landing is not yet proof of a USED offer.
      const prices=parseEgyptianMoney(clean).slice(0,6);
      const condition=classifyUsedCondition(clean);
      unique.set(asin,{
        asin,product_url:`https://www.amazon.eg/dp/${asin}`,
        display_price_candidates:prices,
        condition_signal:condition,
        text_sample:clean.slice(0,240),
        status:'RESALE_LISTING_CANDIDATE_ONLY',
        seller_verified:false,stock_verified:false,used_price_verified:false,
      });
      if(unique.size>=limit)return {inspected_elements:observed,products:[...unique.values()]};
    }
  }
  return {inspected_elements:observed,products:[...unique.values()]};
}
