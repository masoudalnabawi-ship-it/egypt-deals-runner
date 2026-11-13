import {extractUsedOffers, parseEgyptianMoney} from './offer_parser.js';

interface Env {
  BROWSER: any;
  PROBE_KEY: string;
}

type Row = {selector: string; matches: number; samples: string[]};

const PRODUCT_SELECTORS = [
  '#productTitle', '#corePrice_feature_div .a-price .a-offscreen',
  '#newBuyBoxPrice', '#price_inside_buybox', '#usedBuyBox', '#usedBuyBoxPrice',
  '#olp_feature_div', '#buybox-see-all-buying-choices', '#availability',
  'form[action*="validateCaptcha"]', '#captchacharacters'
];
const OFFER_SELECTORS = [
  '#aod-offer', '.aod-offer', '.olpOffer',
  '#aod-offer-list .aod-offer', '#aod-filter-offer-count-string',
  '#aod-offer-list', '#olpOfferList',
  'form[action*="validateCaptcha"]', '#captchacharacters'
];

function safeRows(data: any): Row[] {
  return (Array.isArray(data?.result) ? data.result : []).map((group: any) => ({
    selector: String(group?.selector ?? ''),
    matches: Array.isArray(group?.results) ? group.results.length : 0,
    samples: (Array.isArray(group?.results) ? group.results : []).slice(0, 6)
      .map((item: any) => String(item?.text || '').trim().slice(0, 450)),
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
    const asin = (input.searchParams.get('asin') || 'B0DYGHH7CY').toUpperCase();
    if (!/^[A-Z0-9]{10}$/.test(asin))
      return Response.json({error: 'INVALID_ASIN'}, {status: 400});
    const productUrl = `https://www.amazon.eg/dp/${asin}`;
    const offersUrl = `https://www.amazon.eg/gp/offer-listing/${asin}?condition=used`;
    const result: any = {asin, product_url: productUrl, used_offers_url: offersUrl,
      verified: false, public_posting_enabled: false};
    try {
      const product = await scrape(env, productUrl, PRODUCT_SELECTORS);
      result.product_page = {http: product.http, blocked: product.blocked,
        elements: product.rows, final_url: (product as any).final_url};
      if (!product.ok || product.blocked) {
        result.status = product.blocked ? 'BLOCKED_CAPTCHA' : 'PRODUCT_BROWSER_ERROR';
        return Response.json(result);
      }
      const priceSelectors = ['#corePrice_feature_div .a-price .a-offscreen', '#newBuyBoxPrice', '#price_inside_buybox'];
      const priceTexts = product.rows.filter(r => priceSelectors.includes(r.selector))
        .flatMap(r => r.samples);
      const prices = [...new Set(priceTexts.flatMap(parseEgyptianMoney))];
      result.new_price = prices.length === 1 ? prices[0] : null;
      result.new_price_status = prices.length === 1 ? 'OBSERVED' : 'UNVERIFIED';
      const offers = await scrape(env, offersUrl, OFFER_SELECTORS);
      result.offer_page = {http: offers.http, blocked: offers.blocked,
        elements: offers.rows, final_url: (offers as any).final_url};
      if (!offers.ok || offers.blocked) {
        result.status = offers.blocked ? 'BLOCKED_CAPTCHA' : 'OFFER_BROWSER_ERROR';
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
