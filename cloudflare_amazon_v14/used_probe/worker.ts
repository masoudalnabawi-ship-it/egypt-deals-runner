import {AUDIT_URL,validAuditDestination,auditResaleLinks} from './resale_link_audit.js';
import {SOURCE_URL as RESALE_SNAPSHOT_URL, sameResalePage, analyzeResaleSnapshot} from './resale_snapshot.js';
import {extractUsedOffers, extractUsedFromProductPage, parseEgyptianMoney} from './offer_parser.js';
import {extractResaleListing} from './resale_source.js';
import {analyzeResaleNavigation} from './resale_navigation.js';
import {FIXED_SEARCH_URL,validResaleSearchDestination,inspectSearchData} from './resale_search.js';
import {RESALE_REAL_URL, validResaleRealDestination, inspectRealResaleLanding} from './resale_real_source.js';

interface Env {
  BROWSER: any;
  PROBE_KEY: string;
}

type Row = {selector: string; matches: number; samples: string[]};

const PRODUCT_SELECTORS = [
  '#productTitle', '#corePrice_feature_div .a-price .a-offscreen',
  '#newBuyBoxPrice', '#price_inside_buybox', '#usedBuyBox', '#usedBuyBoxPrice',
  '#usedAccordionRow', '#usedAccordionRow .a-price .a-offscreen',
  '#usedBuyBox .a-price .a-offscreen', '#buybox-used',
  '#buybox-used .a-price .a-offscreen', '#usedOffer',
  '#usedOffer .a-price .a-offscreen',
  '#olp_feature_div', '#buybox-see-all-buying-choices', '#availability',
  'form[action*="validateCaptcha"]', '#captchacharacters'
];
const OFFER_SELECTORS = [
  '#aod-offer', '.aod-offer', '.olpOffer',
  '#aod-offer-list .aod-offer', '#aod-filter-offer-count-string',
  '#aod-offer-list', '#olpOfferList',
  'form[action*="validateCaptcha"]', '#captchacharacters'
];

// AMAZON_EGYPT_RESALE_SOURCE_V5: one read of a known storefront candidate.
// Listing cards are discovery evidence only: no confirmed seller/stock/checkout.
const RESALE_URL = 'https://www.amazon.eg/b?node=27972175031';
async function probeResaleSource(env: Env): Promise<any> {
  const result: any = {source_url:RESALE_URL, verified_offers:0,
    public_posting_enabled:false, candidates:[]};
  const page: Response = await env.BROWSER.quickAction('scrape',{
    url: RESALE_URL,
    elements: [
      {selector:'h1'},
      {selector:'div[data-asin]'},
      {selector:'[data-component-type="s-search-result"]'},
      {selector:'div.s-card-container'},
      {selector:'a[href*="/dp/"]'},
    ],gotoOptions:{waitUntil:'domcontentloaded',timeout:20000},waitForTimeout:800
  });
  result.browser_http = page.status;
  if(!page.ok){result.status=page.status===429?'SOURCE_RATE_LIMITED':'SOURCE_BROWSER_ERROR';return result;}
  const data:any=await page.json();
  const originStatus=Number(data?.meta?.status||200);
  result.source_http=originStatus;
  result.final_url=String(data?.meta?.finalUrl||RESALE_URL).slice(0,400);
  if(originStatus===429){result.status='SOURCE_RATE_LIMITED';return result;}
  if(originStatus>=400){result.status='SOURCE_HTTP_ERROR';return result;}
  try {
    const final=new URL(result.final_url);
    if(final.hostname!=='www.amazon.eg' || !/^\/b\/?$/.test(final.pathname) ||
       final.searchParams.get('node')!=='27972175031'){
      result.status='SOURCE_REDIRECT_UNVERIFIED';return result;
    }
  }catch {result.status='SOURCE_REDIRECT_UNVERIFIED';return result;}
  const evidence=extractResaleListing(data,24);
  result.inspected_elements=evidence.inspected_elements;
  result.candidates=evidence.products;
  result.candidate_count=evidence.products.length;
  result.status=evidence.products.length?'RESALE_LISTING_CANDIDATES_NEED_VALIDATION':'SOURCE_ACCESSIBLE_NO_LISTINGS';
  return result;
}

// AMAZON_RESALE_NAV_V6: one storefront inspection plus at most one evident category page.
// No retry, identity rotation, CAPTCHA handling, inventory or checkout claims.
const RESALE_NAV_SELECTORS = [
  'title', 'h1', '#mainContent', '#desktop-grid',
  'main a[href]', '#mainContent a[href]', '#desktop-grid a[href]',
  '.bxc-grid a[href]', '#zg_browseRoot a[href]', 'a[href]',
  'div[data-asin]', '[data-component-type="s-search-result"]',
  'div.s-card-container', 'a[href*="/dp/"]',
  'form[action*="validateCaptcha"]', '#captchacharacters'
];
async function probeResaleNavigation(env: Env): Promise<any> {
  const result: any = {source_url:RESALE_URL, status:'UNINSPECTED',
    public_posting_enabled:false, verified_offers:0, used_prices_verified:0};
  const scrapeOne = async (url: string, selectors: string[]) => {
    const response: Response = await env.BROWSER.quickAction('scrape', {
      url, elements:selectors.map(selector=>({selector})),
      gotoOptions:{waitUntil:'domcontentloaded',timeout:20000}, waitForTimeout:900
    });
    if (!response.ok) return {browser_http:response.status, source_http:null, final_url:null, data:null};
    const data:any = await response.json();
    return {browser_http:response.status, source_http:Number(data?.meta?.status||200),
      final_url:String(data?.meta?.finalUrl||url), data};
  };
  const first = await scrapeOne(RESALE_URL, RESALE_NAV_SELECTORS);
  result.browser_http=first.browser_http;
  result.source_http=first.source_http;
  result.final_url=first.final_url;
  if (first.browser_http===429 || first.source_http===429) {
    result.status='SOURCE_RATE_LIMITED';return result;
  }
  if (!first.data || (first.source_http!==null && first.source_http>=400)) {
    result.status='SOURCE_FETCH_FAILED';return result;
  }
  // A 200 response with an unexpected redirect is not a confirmed Resale page.
  if (first.final_url!==RESALE_URL) {
    result.status='SOURCE_REDIRECT_UNVERIFIED';return result;
  }
  const overview=analyzeResaleNavigation(first.data, RESALE_URL);
  result.navigation=overview;
  result.category_urls_discovered=overview.navigation_total_found;
  result.product_candidates_on_landing=overview.product_count;
  if (overview.has_captcha_elements) {
    result.status='SOURCE_CAPTCHA_REQUIRES_MANUAL_REVIEW';return result;
  }
  if (!overview.category_probe_url) {
    result.status=overview.product_count?'LANDING_PRODUCT_CANDIDATES_ONLY':'SOURCE_NO_CATEGORY_NAV_OBSERVED';
    return result;
  }
  // Only follow a single main-content category link with a valid Amazon.eg browse/search path.
  const second=await scrapeOne(overview.category_probe_url, RESALE_NAV_SELECTORS);
  const category:any={requested_url:overview.category_probe_url,browser_http:second.browser_http,
    source_http:second.source_http,final_url:second.final_url,
    verified_used_offers:0};
  result.category_probe=category;
  if (second.browser_http===429 || second.source_http===429) {
    result.status='CATEGORY_RATE_LIMITED';return result;
  }
  if (!second.data || (second.source_http!==null && second.source_http>=400)) {
    result.status='CATEGORY_FETCH_FAILED';return result;
  }
  if (second.final_url!==overview.category_probe_url) {
    result.status='CATEGORY_REDIRECT_UNVERIFIED';return result;
  }
  const details=analyzeResaleNavigation(second.data, overview.category_probe_url);
  category.page_context=details.body_context;
  category.product_count=details.product_count;
  category.candidates=details.product_candidates.slice(0,12);
  category.has_captcha_elements=details.has_captcha_elements;
  result.status=details.has_captcha_elements?'CATEGORY_CAPTCHA_REQUIRES_MANUAL_REVIEW'
    :(details.product_count?'CATEGORY_PRODUCT_CANDIDATES_ONLY':'CATEGORY_ACCESSIBLE_NO_PRODUCTS_OBSERVED');
  return result;
}

// AMAZON_RESALE_SEARCH_V7: try the exact Resale browse node as constrained search.
// One read only; no offer listing, no retry, no public posting.
const SEARCH_SELECTORS = [
  'title','h1','#search','div[data-asin]','div.s-result-item[data-asin]',
  '[data-component-type="s-search-result"]','div.s-card-container',
  '#search a[href*="/dp/"]','a[href*="/dp/"]',
  'form[action*="validateCaptcha"]','#captchacharacters'
];
async function probeResaleSearch(env: Env): Promise<any> {
  const result:any={requested_url:FIXED_SEARCH_URL,public_posting_enabled:false,
    verified_offers:0,used_prices_verified:0,candidate_count:0};
  const response:Response=await env.BROWSER.quickAction('scrape',{
    url:FIXED_SEARCH_URL,elements:SEARCH_SELECTORS.map(selector=>({selector})),
    gotoOptions:{waitUntil:'domcontentloaded',timeout:20000},waitForTimeout:900
  });
  result.browser_http=response.status;
  if(!response.ok){result.status=response.status===429?'SEARCH_RATE_LIMITED':'SEARCH_FETCH_FAILED';return result;}
  const data:any=await response.json();
  const origin=Number(data?.meta?.status||200);
  const finalUrl=String(data?.meta?.finalUrl||FIXED_SEARCH_URL);
  result.source_http=origin;result.final_url=finalUrl.slice(0,400);
  if(origin===429){result.status='SEARCH_RATE_LIMITED';return result;}
  if(origin>=400){result.status='SEARCH_FETCH_FAILED';return result;}
  if(!validResaleSearchDestination(finalUrl)){
    result.status='SEARCH_REDIRECT_UNVERIFIED';return result;
  }
  const x=inspectSearchData(data);
  result.page_context=x.page_context;
  result.has_captcha_elements=x.has_captcha_elements;
  result.inspected_elements=x.inspected_elements;
  if(x.has_captcha_elements){result.status='SEARCH_CAPTCHA_REQUIRES_REVIEW';return result;}
  result.candidate_count=x.product_count;
  result.candidates=x.product_candidates;
  result.status=x.product_count?'SEARCH_PRODUCT_CANDIDATES_UNVERIFIED':'SEARCH_ACCESSIBLE_NO_PRODUCTS_OBSERVED';
  return result;
}

// AMAZON_RESALE_REAL_V8: one read of an independently referenced Resale /l/ landing.
// Discovery only. No listing confirmations, offer retries, or public alerts.
const REAL_RESALE_SELECTORS = [
  'title', 'h1', '#mainContent', '#desktop-grid', '#search',
  '#mainContent a[href]', '#desktop-grid a[href]', '.bxc-grid a[href]',
  'a[href*="/dp/"]', 'a[href*="/gp/product/"]',
  'a[href*="/l/"]', 'div[data-asin]',
  '[data-component-type="s-search-result"]', 'div.s-card-container',
  'form[action*="validateCaptcha"]', '#captchacharacters'
];
async function probeRealResaleSourceV8(env: Env): Promise<any> {
  const result: any = {requested_url: RESALE_REAL_URL, public_posting_enabled: false,
    verified_used_offers: 0, candidate_count: 0, category_count: 0};
  const response: Response = await env.BROWSER.quickAction('scrape', {
    url: RESALE_REAL_URL,
    elements: REAL_RESALE_SELECTORS.map(selector => ({selector})),
    gotoOptions: {waitUntil: 'domcontentloaded', timeout: 20000},
    waitForTimeout: 900
  });
  result.browser_http = response.status;
  if (!response.ok) {
    result.status = response.status === 429 ? 'REAL_SOURCE_RATE_LIMITED' : 'REAL_SOURCE_FETCH_FAILED';
    return result;
  }
  const data: any = await response.json();
  const originStatus = Number(data?.meta?.status || 200);
  const finalURL = String(data?.meta?.finalUrl || RESALE_REAL_URL);
  result.source_http = originStatus;
  result.final_url = finalURL.slice(0, 400);
  if (originStatus === 429) {result.status = 'REAL_SOURCE_RATE_LIMITED'; return result;}
  if (originStatus >= 400) {result.status = 'REAL_SOURCE_FETCH_FAILED'; return result;}
  if (!validResaleRealDestination(finalURL)) {
    result.status = 'REAL_SOURCE_REDIRECT_UNVERIFIED'; return result;
  }
  const seen = inspectRealResaleLanding(data);
  result.page_context = seen.page_context;
  result.inspected_elements = seen.inspected_elements;
  result.anchors_with_href = seen.anchors_with_href;
  result.has_captcha_elements = seen.has_captcha_elements;
  if (seen.has_captcha_elements) {
    result.status = 'REAL_SOURCE_CAPTCHA_REQUIRES_REVIEW'; return result;
  }
  result.candidate_count = seen.candidate_count;
  result.candidates = seen.candidates;
  result.category_count = seen.category_count;
  result.category_link_candidates = seen.category_link_candidates;
  result.status = seen.candidate_count ? 'REAL_SOURCE_PRODUCT_CANDIDATES_UNVERIFIED'
    : seen.category_count ? 'REAL_SOURCE_CATEGORY_LINKS_UNVERIFIED'
      : 'REAL_SOURCE_ACCESSIBLE_NO_LISTINGS';
  return result;
}

// AMAZON_RESALE_SNAPSHOT_V11: one read, rendered markdown plus accessibility tree.
// No repeated scraping, no login/session tricks, no offer confirmation.
async function probeResaleSnapshotV11(env: Env): Promise<any> {
  const result: any = {requested_url:RESALE_SNAPSHOT_URL, verified_used_offers:0,
    public_posting_enabled:false, product_candidate_count:0, category_link_count:0};
  const response:Response=await env.BROWSER.quickAction('snapshot', {
    url:RESALE_SNAPSHOT_URL, formats:['markdown','accessibilityTree'],
    gotoOptions:{waitUntil:'domcontentloaded', timeout:20000}, waitForTimeout:1000
  });
  result.browser_http=response.status;
  if (!response.ok) {result.status=response.status===429?'SOURCE_RATE_LIMITED':'SOURCE_SNAPSHOT_FAILED';return result;}
  const data:any=await response.json();
  result.source_http=Number(data?.meta?.status||200);
  result.final_url=String(data?.meta?.finalUrl||RESALE_SNAPSHOT_URL).slice(0,400);
  if (result.source_http===429) {result.status='SOURCE_RATE_LIMITED';return result;}
  if (result.source_http>=400) {result.status='SOURCE_SNAPSHOT_FAILED';return result;}
  if (!sameResalePage(result.final_url)) {result.status='SOURCE_REDIRECT_UNVERIFIED';return result;}
  const seen=analyzeResaleSnapshot(data);
  Object.assign(result,seen);
  result.status=seen.captcha_text_signal?'SOURCE_CAPTCHA_REQUIRES_REVIEW':
    seen.product_candidate_count?'SOURCE_PRODUCT_LINKS_UNVERIFIED':
      seen.category_link_count?'SOURCE_CATEGORY_LINKS_UNVERIFIED':
        seen.markdown_length<100 && seen.accessibility_nodes_seen<10?'SOURCE_GENERIC_SHELL_ONLY':'SOURCE_NO_PRODUCT_LINKS_OBSERVED';
  return result;
}

// AMAZON_RESALE_LINK_AUDIT_V12: one fixed source snapshot for safe link-shape diagnosis.
// No login, retries, rate-limit bypasses, offer-listing pages, or publication.
async function probeResaleLinkAuditV12(env: Env): Promise<any> {
  const result: any = {requested_url:AUDIT_URL, verified_used_offers:0,
    public_posting_enabled:false, product_candidate_count:0, category_candidate_count:0};
  const response:Response=await env.BROWSER.quickAction('snapshot', {
    url:AUDIT_URL, formats:['markdown','accessibilityTree'],
    gotoOptions:{waitUntil:'domcontentloaded',timeout:20000},waitForTimeout:1100
  });
  result.browser_http=response.status;
  if(!response.ok){result.status=response.status===429?'SOURCE_RATE_LIMITED':'SOURCE_LINK_AUDIT_FAILED';return result;}
  const data:any=await response.json();
  result.source_http=Number(data?.meta?.status||200);
  result.final_url=String(data?.meta?.finalUrl||AUDIT_URL).slice(0,400);
  if(result.source_http===429){result.status='SOURCE_RATE_LIMITED';return result;}
  if(result.source_http>=400){result.status='SOURCE_LINK_AUDIT_FAILED';return result;}
  if(!validAuditDestination(result.final_url)){result.status='SOURCE_REDIRECT_UNVERIFIED';return result;}
  const details=auditResaleLinks(data);
  Object.assign(result,details);
  result.status=details.captcha_text_signal?'SOURCE_CAPTCHA_REQUIRES_REVIEW':'LINK_AUDIT_DIAGNOSTIC_ONLY';
  return result;
}

function safeRows(data: any): Row[] {
  return (Array.isArray(data?.result) ? data.result : []).map((group: any) => ({
    selector: String(group?.selector ?? ''),
    matches: Array.isArray(group?.results) ? group.results.length : 0,
    samples: (Array.isArray(group?.results) ? group.results : []).slice(0, 6)
      .map((item: any) => String(item?.text || '').trim().slice(0, 1200)),
  })).filter((r: Row) => r.matches > 0);
}

async function scrape(env: Env, url: string, selectors: string[]) {
  const response: Response = await env.BROWSER.quickAction('scrape', {
    url, elements: selectors.map(selector => ({selector})),
    gotoOptions: {waitUntil: 'domcontentloaded', timeout: 20000},
    waitForTimeout: 900
  });
  if (!response.ok) return {ok: false, http: response.status, rows: [], cards: [], blocked: false};
  const data: any = await response.json();
  const rows = safeRows(data);
  const blocked = rows.some((r: Row) => /captcha/i.test(r.selector) && r.matches > 0);
  const cards: {text: string}[] = [];
  for (const group of (Array.isArray(data?.result) ? data.result : [])) {
    if (!/^#aod-offer$|^\.aod-offer$|^\.olpOffer$|^#aod-offer-list \.aod-offer$/i.test(String(group?.selector || ''))) continue;
    for (const item of (Array.isArray(group?.results) ? group.results : [])) {
      cards.push({text: String(item?.text || '')});
    }
  }
  const unique = [...new Map(cards.map(c => [c.text, c])).values()];
  return {ok: true, http: response.status, rows, cards: unique, blocked, final_url: data?.meta?.finalUrl || url};
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (!env.PROBE_KEY || request.headers.get('Authorization') !== `Bearer ${env.PROBE_KEY}`)
      return new Response('Unauthorized', {status: 401});
    const input = new URL(request.url);
    if (input.searchParams.get('mode') === 'resale_link_audit_v12') {
      try {return Response.json(await probeResaleLinkAuditV12(env));}
      catch(e) {return Response.json({status:'SOURCE_LINK_AUDIT_FAILED',
        error_type:String(e).slice(0,120),public_posting_enabled:false},{status:502});}
    }
    if (input.searchParams.get('mode') === 'resale_snapshot_v11') {
      try {return Response.json(await probeResaleSnapshotV11(env));}
      catch(e) {return Response.json({status:'SOURCE_SNAPSHOT_FAILED',error_type:String(e).slice(0,120),public_posting_enabled:false},{status:502});}
    }
    if (input.searchParams.get('mode') === 'resale_real_v8') {
      try {return Response.json(await probeRealResaleSourceV8(env));}
      catch (e) {return Response.json({status:'REAL_SOURCE_FETCH_FAILED',
        error_type:String(e).slice(0,120),public_posting_enabled:false},{status:502});}
    }
    if (input.searchParams.get('mode')==='resale_search') {
      try {return Response.json(await probeResaleSearch(env));}
      catch(e) {return Response.json({status:'SEARCH_FETCH_FAILED',error_type:String(e).slice(0,120),public_posting_enabled:false},{status:502});}
    }
    if (input.searchParams.get('mode')==='resale_nav') {
      try {return Response.json(await probeResaleNavigation(env));}
      catch(e) {return Response.json({status:'SOURCE_BROWSER_ERROR',error_type:String(e).slice(0,120),public_posting_enabled:false},{status:502});}
    }
    if (input.searchParams.get('mode')==='resale') {
      try {return Response.json(await probeResaleSource(env));}
      catch (e) {return Response.json({status:'SOURCE_BROWSER_ERROR', error_type:String(e).slice(0,100), public_posting_enabled:false}, {status:502});}
    }
    const asin = (input.searchParams.get('asin') || 'B0DYGHH7CY').toUpperCase();
    if (!/^[A-Z0-9]{10}$/.test(asin))
      return Response.json({error: 'INVALID_ASIN'}, {status: 400});
    // AMAZON_USED_PRODUCT_ONLY_ROTATION_V4: consent-respecting low-volume check.
    const productOnly = input.searchParams.get('main_only') === '1';
    const productUrl = `https://www.amazon.eg/dp/${asin}`;
    const offersUrl = `https://www.amazon.eg/gp/offer-listing/${asin}?condition=used`;
    const result: any = {asin, product_url: productUrl, used_offers_url: offersUrl,
      verified: false, public_posting_enabled: false};
    try {
      const product = await scrape(env, productUrl, PRODUCT_SELECTORS);
      result.product_page = {http: product.http, blocked: product.blocked,
        elements: product.rows, final_url: (product as any).final_url};
      if (!product.ok || product.blocked) {
        result.status = product.http === 429 ? 'PRODUCT_RATE_LIMITED'
          : (product.blocked ? 'BLOCKED_CAPTCHA' : 'PRODUCT_BROWSER_ERROR');
        return Response.json(result);
      }
      const priceSelectors = ['#corePrice_feature_div .a-price .a-offscreen', '#newBuyBoxPrice', '#price_inside_buybox'];
      const priceTexts = product.rows.filter(r => priceSelectors.includes(r.selector))
        .flatMap(r => r.samples);
      const prices = [...new Set(priceTexts.flatMap(parseEgyptianMoney))];
      result.new_price = prices.length === 1 ? prices[0] : null;
      result.new_price_status = prices.length === 1 ? 'OBSERVED' : 'UNVERIFIED';
      // AMAZON_USED_PRODUCT_PAGE_SAFE_V3: inspect used-specific containers first.
      // If they contain a single price, skip the rate-limited secondary page.
      // All amounts remain unverified seller candidates, never publication proof.
      const primaryCandidates = extractUsedFromProductPage(product.rows, productUrl);
      result.product_page_used_offers = primaryCandidates;
      if (primaryCandidates.length) {
        result.used_offers = primaryCandidates;
        const lowest = Math.min(...primaryCandidates.map(x => x.price));
        result.lowest_used_price_candidate = lowest;
        result.used_saving_vs_new_percent_candidate = (result.new_price && lowest < result.new_price)
          ? Math.round((1 - lowest / result.new_price) * 1000) / 10 : null;
        result.used_price_verified = false;
        result.offer_page = {skipped: true, reason: 'USED_CANDIDATE_ON_PRODUCT_PAGE'};
        result.status = 'PRODUCT_PAGE_USED_CANDIDATE_NEEDS_VERIFICATION';
        return Response.json(result);
      }
      if (productOnly) {
        result.used_offers = [];
        result.used_price_verified = false;
        result.offer_page = {skipped: true, reason: 'PRODUCT_PAGE_ONLY_RATE_LIMIT_SAFE'};
        result.status = 'USED_NOT_VISIBLE_ON_PRODUCT_PAGE';
        return Response.json(result);
      }
      const offers = await scrape(env, offersUrl, OFFER_SELECTORS);
      result.offer_page = {http: offers.http, blocked: offers.blocked,
        elements: offers.rows, final_url: (offers as any).final_url};
      if (!offers.ok || offers.blocked) {
        // HTTP 429 is a request-rate limit, not evidence that there are no used offers.
        // Do not retry, rotate identities, or auto-publish. Keep evidence unavailable.
        result.status = offers.http === 429 ? 'OFFER_RATE_LIMITED'
          : (offers.blocked ? 'BLOCKED_CAPTCHA' : 'OFFER_BROWSER_ERROR');
        result.used_price_verified = false;
        result.used_price_unavailable_reason = offers.http === 429
          ? 'Amazon rate-limited the offer-listing request. No retry attempted.'
          : 'Offer-listing request failed or needs human verification.';
        return Response.json(result);
      }
      result.used_offers = extractUsedOffers(offers.cards, offersUrl);
      const valid = result.used_offers.filter((x: any) => x.price !== null);
      const lowest = valid.length ? Math.min(...valid.map((x: any) => x.price)) : null;
      result.lowest_used_price_candidate = lowest;
      result.used_saving_vs_new_percent_candidate = (lowest && result.new_price && lowest < result.new_price)
        ? Math.round((1 - lowest / result.new_price) * 1000) / 10 : null;
      result.status = valid.length ? 'USED_PRICE_CANDIDATE_NEEDS_VERIFICATION' : 'USED_PRICE_NOT_CONFIRMED';
      return Response.json(result);
    } catch (e) {
      return Response.json({...result, status: 'ERROR', message: String(e).slice(0, 180)});
    }
  }
} satisfies ExportedHandler<Env>;
