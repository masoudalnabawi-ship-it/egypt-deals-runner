import type { DealCandidate, DealRow, Settings, V14Env } from "./types";
import { D1Repository } from "./db";
import { cleanText, isProtectedPage, parseNumber, pickAttr, safeJsonParse, stripTags } from "./util";

export class VerificationRejected extends Error {}

const BANK_OFFER_MARKERS = [
  "bank", "credit card", "debit card", "cardholder", "installment", "installments", "instalment", "instalments",
  "cib", "qnb", "nbk", "mashreq", "emirates nbd", "fab", "adib", "hsbc", "al ahly", "nbe", "banque misr",
  "بنك", "بطاقة ائتمان", "بطاقة خصم", "كارت ائتمان", "كارت خصم", "تقسيط", "أقساط", "اقساط",
];

function couponPercent(text: string): number {
  const normalized = String(text || "").replace(/[٠-٩]/g, d => String("٠١٢٣٤٥٦٧٨٩".indexOf(d))).replace(/٫/g, ".");
  const re = /(\d+(?:\.\d+)?)\s*%/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(normalized)) !== null) {
    const start = Math.max(0, m.index - 100);
    const end = Math.min(normalized.length, m.index + m[0].length + 100);
    const context = normalized.slice(start, end).toLowerCase();
    if (BANK_OFFER_MARKERS.some(x => context.includes(x))) continue;
    const v = Number(m[1]);
    if (v > 0 && v <= 90) return v;
  }
  return 0;
}

function extractExplicitAmazonCoupon(html: string): number {
  const regions: string[] = [];
  const patterns = [
    /<(?:div|span|label)\b[^>]*id=["']couponText[^"']*["'][^>]*>([\s\S]{0,2500}?)<\/(?:div|span|label)>/gi,
    /<(?:div|span)\b[^>]*id=["']couponFeature[^"']*["'][^>]*>([\s\S]{0,4000}?)<\/(?:div|span)>/gi,
    /<div\b[^>]*id=["']coupon_feature_div["'][^>]*>([\s\S]{0,5000}?)<\/div>/gi,
    /<[^>]*data-feature-name=["']coupon["'][^>]*>([\s\S]{0,4000}?)<\/[a-z0-9]+>/gi,
    /<[^>]*class=["'][^"']*(?:couponBadge|couponLabel)[^"']*["'][^>]*>([\s\S]{0,2000}?)<\/[a-z0-9]+>/gi,
  ];
  for (const re of patterns) {
    let m: RegExpExecArray | null;
    while ((m = re.exec(html)) !== null && regions.length < 20) regions.push(stripTags(m[1]));
  }
  let best = 0;
  for (const text of regions) {
    const low = text.toLowerCase();
    if (!["coupon","voucher","كوبون","قسيمة","قسيمة خصم"].some(x => low.includes(x))) continue;
    best = Math.max(best, couponPercent(text));
  }
  return best;
}

function collectPriceValues(html: string): number[] {
  const values: number[] = [];
  const markers = ["corePrice_feature_div","corePriceDisplay_desktop_feature_div","apexPriceToPay","priceToPay","price_inside_buybox","tp_price_block_total_price_ww","newBuyBoxPrice"];
  for (const marker of markers) {
    let pos = 0;
    while (true) {
      const idx = html.indexOf(marker, pos);
      if (idx < 0) break;
      const region = html.slice(Math.max(0, idx - 200), Math.min(html.length, idx + 2200));
      const re = /class=["'][^"']*a-offscreen[^"']*["'][^>]*>([^<]{1,120})</gi;
      let m: RegExpExecArray | null;
      while ((m = re.exec(region)) !== null) {
        const n = parseNumber(m[1]);
        if (n > 0) values.push(Math.round(n * 100) / 100);
      }
      pos = idx + marker.length;
      if (values.length > 50) break;
    }
  }
  if (!values.length) {
    for (const re of [
      /"priceAmount"\s*:\s*([0-9]+(?:\.[0-9]+)?)/gi,
      /"price"\s*:\s*"([0-9]+(?:\.[0-9]+)?)"/gi,
      /"displayPrice"\s*:\s*"[^0-9]*([0-9][0-9,]*(?:\.[0-9]+)?)/gi,
    ]) {
      let m: RegExpExecArray | null;
      while ((m = re.exec(html)) !== null && values.length < 50) {
        const n = parseNumber(m[1]);
        if (n > 0) values.push(n);
      }
    }
  }
  return values;
}

function mostFrequentPrice(values: number[]): {price: number; signals: number} {
  if (!values.length) return { price: 0, signals: 0 };
  const counts = new Map<number, number>();
  for (const v of values) counts.set(v, (counts.get(v) || 0) + 1);
  let price = values[0], signals = 0;
  for (const [v, n] of counts) if (n > signals) { price = v; signals = n; }
  return { price, signals };
}

function extractOldAmazonPrice(html: string, current: number): number {
  let old = 0;
  const patterns = [
    /(?:basisPrice|a-text-price|data-a-strike=["']true["'])[\s\S]{0,1200}?class=["'][^"']*a-offscreen[^"']*["'][^>]*>([^<]{1,120})</gi,
    /class=["'][^"']*a-text-price[^"']*["'][\s\S]{0,1000}?class=["'][^"']*a-offscreen[^"']*["'][^>]*>([^<]{1,120})</gi,
  ];
  for (const re of patterns) {
    let m: RegExpExecArray | null;
    while ((m = re.exec(html)) !== null) {
      const n = parseNumber(m[1]);
      if (n > current) old = Math.max(old, n);
    }
  }
  return old;
}

function extractSavingsPercent(html: string): number {
  let best = 0;
  const markers = ["savingsPercentage","priceBlockSavingsString","regularprice_savings","reinventPriceSavingsPercentageMargin"];
  for (const marker of markers) {
    let pos = 0;
    while (true) {
      const idx = html.indexOf(marker, pos);
      if (idx < 0) break;
      const region = stripTags(html.slice(Math.max(0, idx - 100), Math.min(html.length, idx + 500))).toLowerCase();
      if (!BANK_OFFER_MARKERS.some(x => region.includes(x))) {
        const m = region.match(/-?\s*(\d+(?:\.\d+)?)\s*%/);
        const pct = m ? Number(m[1]) : 0;
        if (pct >= 5 && pct <= 90) best = Math.max(best, pct);
      }
      pos = idx + marker.length;
    }
  }
  return best;
}

function extractAmazonTitle(html: string, fallback: string): string {
  const m = html.match(/<[^>]+id=["']productTitle["'][^>]*>([\s\S]{0,3000}?)<\/[a-z0-9]+>/i);
  return cleanText(m ? stripTags(m[1]) : fallback) || fallback;
}

function extractAmazonImage(html: string, fallback: string): string {
  const tag = html.match(/<img\b[^>]*id=["'](?:landingImage|imgBlkFront)["'][^>]*>/i)?.[0] || "";
  const get = (name: string) => tag.match(new RegExp(`${name}=["']([^"']+)["']`, "i"))?.[1] || "";
  return get("data-old-hires") || get("src") || fallback;
}

function amazonFromHtml(incoming: DealCandidate, html: string, via: string): {deal: DealCandidate; meta: Record<string, unknown>} {
  if (isProtectedPage(html)) throw new VerificationRejected("amazon_protected");
  const { price: current, signals: repeatedSignals } = mostFrequentPrice(collectPriceValues(html));
  if (!(current > 0)) throw new VerificationRejected("amazon_no_live_price");
  let old = extractOldAmazonPrice(html, current);
  const savings = extractSavingsPercent(html);
  let signalCount = Math.max(1, repeatedSignals);
  if (!(old > current) && savings >= 5 && savings <= 90) {
    const derived = current / (1 - savings / 100);
    if (derived >= current * 1.05 && derived <= current * 10) {
      old = Math.round(derived * 100) / 100;
      signalCount = Math.max(signalCount, 2);
    }
  }
  if (old > current) signalCount = Math.max(signalCount, 2);
  const coupon = extractExplicitAmazonCoupon(html);
  if (coupon > 0) signalCount = Math.max(signalCount, 2);
  const low = html.toLowerCase();
  const flash = ["limited time deal","lightning deal","deal of the day","عرض لفترة محدودة","صفقة لفترة محدودة","عرض محدود"].some(x => low.includes(x));
  const deal: DealCandidate = {
    ...incoming,
    title: extractAmazonTitle(html, incoming.title),
    current_price: current,
    old_price: old > current ? old : null,
    image_url: extractAmazonImage(html, incoming.image_url || ""),
  };
  return { deal, meta: { http_via: via, coupon_percent: coupon, coupon_source: coupon > 0 ? "explicit_product_coupon" : "", flash,
    amazon_savings_percent: savings, verification_signals: Math.max(1, signalCount) } };
}

async function canUseBrowser(repo: D1Repository, settings: Settings): Promise<boolean> {
  if (!settings.browser_daily_budget_ms) return false;
  const day = new Date().toISOString().slice(0, 10);
  const used = await repo.counterGet(`browser_ms:${day}`);
  return used < settings.browser_daily_budget_ms;
}

async function browserScrapeAmazon(env: V14Env, repo: D1Repository, settings: Settings, incoming: DealCandidate): Promise<{deal: DealCandidate; meta: Record<string, unknown>}> {
  if (!env.BROWSER || !(await canUseBrowser(repo, settings))) throw new VerificationRejected("browser_budget_unavailable");
  const response: Response = await env.BROWSER.quickAction("scrape", {
    url: incoming.url,
    elements: [
      { selector: "#corePrice_feature_div .a-price .a-offscreen" },
      { selector: "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen" },
      { selector: ".apexPriceToPay .a-offscreen" }, { selector: ".priceToPay .a-offscreen" },
      { selector: ".basisPrice .a-offscreen" }, { selector: ".a-text-price .a-offscreen" },
      { selector: ".savingsPercentage" }, { selector: "#couponText" }, { selector: "#couponFeature" },
      { selector: "#coupon_feature_div" }, { selector: "#productTitle" }, { selector: "#landingImage" },
    ],
    gotoOptions: { waitUntil: "domcontentloaded", timeout: 20000 },
    waitForTimeout: 700,
  });
  const ms = Number(response.headers.get("X-Browser-Ms-Used") || 0);
  if (ms > 0) await repo.counterAdd(`browser_ms:${new Date().toISOString().slice(0, 10)}`, ms);
  if (!response.ok) throw new VerificationRejected(`browser_http_${response.status}`);
  const payload: any = await response.json();
  if (!payload?.success || !Array.isArray(payload.result)) throw new VerificationRejected("browser_scrape_invalid");
  const bySelector = new Map<string, any[]>();
  for (const group of payload.result) bySelector.set(String(group.selector || ""), Array.isArray(group.results) ? group.results : []);
  const texts = (selectors: string[]) => selectors.flatMap(sel => (bySelector.get(sel) || []).map((x: any) => String(x.text || "")));
  const prices = texts(["#corePrice_feature_div .a-price .a-offscreen","#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",".apexPriceToPay .a-offscreen",".priceToPay .a-offscreen"]).map(parseNumber).filter((x: number) => x > 0);
  const { price: current, signals: repeated } = mostFrequentPrice(prices);
  if (!(current > 0)) throw new VerificationRejected("amazon_browser_no_price");
  let old = 0;
  for (const t of texts([".basisPrice .a-offscreen",".a-text-price .a-offscreen"])) { const n = parseNumber(t); if (n > current) old = Math.max(old, n); }
  let savings = 0;
  for (const t of texts([".savingsPercentage"])) { const m = t.match(/-?\s*(\d+(?:\.\d+)?)\s*%/); if (m) savings = Math.max(savings, Number(m[1])); }
  let signals = Math.max(1, repeated);
  if (!(old > current) && savings >= 5 && savings <= 90) { const d = current / (1 - savings/100); if (d >= current*1.05 && d <= current*10) { old = Math.round(d*100)/100; signals = Math.max(signals, 2); } }
  if (old > current) signals = Math.max(signals, 2);
  let coupon = 0;
  for (const t of texts(["#couponText","#couponFeature","#coupon_feature_div"])) {
    const low = t.toLowerCase();
    if (["coupon","voucher","كوبون","قسيمة"].some(x => low.includes(x))) coupon = Math.max(coupon, couponPercent(t));
  }
  if (coupon > 0) signals = Math.max(signals, 2);
  const title = cleanText(texts(["#productTitle"])[0] || incoming.title) || incoming.title;
  let image = incoming.image_url || "";
  const imageRows = bySelector.get("#landingImage") || [];
  if (imageRows[0]) image = pickAttr(imageRows[0].attributes, "data-old-hires") || pickAttr(imageRows[0].attributes, "src") || image;
  return { deal: { ...incoming, title, current_price: current, old_price: old > current ? old : null, image_url: image },
    meta: { http_via: "browser_run", browser_ms: ms, coupon_percent: coupon, coupon_source: coupon ? "explicit_product_coupon" : "", flash: false,
      amazon_savings_percent: savings, verification_signals: signals } };
}

async function fetchAmazonDirect(url: string): Promise<string> {
  const r = await fetch(url, { headers: {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "accept-language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
    "accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8", "cache-control": "no-cache",
  }, redirect: "follow" });
  const text = await r.text();
  if (!r.ok) throw new Error(`amazon_direct_http_${r.status}`);
  return text;
}

function validNoonTitle(title: string): boolean {
  const t = cleanText(title); if (t.length < 5) return false;
  if (["placeholder","product","item","unknown","none","null","n/a","na"].includes(t.toLowerCase())) return false;
  return /[A-Za-z\u0600-\u06FF]/.test(t);
}

async function verifyNoon(env: V14Env, repo: D1Repository, settings: Settings, incoming: DealCandidate): Promise<{deal: DealCandidate; meta: Record<string, unknown>}> {
  if (!incoming.external_id) throw new VerificationRejected("noon_sku_missing");
  const sku = encodeURIComponent(incoming.external_id);
  const api = `https://www.noon.com/_vs/nc/mp-customer-catalog-api/api/v3/product/${sku}`;
  const r = await fetch(api, { headers: {
    "accept": "application/json,text/plain,*/*", "accept-language": "en-EG,en;q=0.9,ar-EG;q=0.8,ar;q=0.7",
    "x-locale": "en-eg", "x-platform": "web", "x-mp": "noon", "x-mp-country": "eg", "x-country-code": "eg",
    "referer": "https://www.noon.com/egypt-en/", "origin": "https://www.noon.com",
  }, redirect: "follow" });
  if (!r.ok) throw new VerificationRejected(`noon_api_http_${r.status}`);
  let data: any; try { data = await r.json(); } catch { throw new VerificationRejected("noon_api_invalid_json"); }
  const product = data?.product;
  if (!product || typeof product !== "object") throw new VerificationRejected("noon_api_product_missing");
  const marketBlob = JSON.stringify({ meta: data?.meta, product: { currency: product?.currency, locale: product?.locale, country: product?.country } }).toLowerCase();
  if (["\"currency\":\"aed\"", "dubai", "abu dhabi", "united arab emirates", "\"country\":\"ae\""] .some(x => marketBlob.includes(x))) {
    throw new VerificationRejected("noon_wrong_market");
  }
  const requested = incoming.external_id.toUpperCase();
  const variants = Array.isArray(product.variants) ? product.variants.filter((x: any) => x && typeof x === "object") : [];
  let chosen = variants.find((v: any) => String(v.sku || "").toUpperCase() === requested) || variants[0];
  const offers = Array.isArray(chosen?.offers) ? chosen.offers.filter((x: any) => x && typeof x === "object") : [];
  const cur = (o: any) => parseNumber(o?.sale_price ?? o?.salePrice) || parseNumber(o?.price);
  const buyable = offers.filter((o: any) => o?.is_buyable !== false && cur(o) > 0);
  const pool = buyable.length ? buyable : offers.filter((o: any) => cur(o) > 0);
  if (!pool.length) throw new VerificationRejected("noon_no_live_price");
  pool.sort((a: any,b: any) => cur(a)-cur(b));
  const offer = pool[0]; const current = cur(offer); const listed = parseNumber(offer?.price); const old = listed > current ? listed : 0;
  const title = cleanText(product.product_title || product.name || product.title || incoming.title);
  if (!validNoonTitle(title)) throw new VerificationRejected("noon_invalid_product_title");
  let image = incoming.image_url || ""; if (Array.isArray(product.image_urls) && product.image_urls[0]) image = String(product.image_urls[0]);
  let brand: any = product.brand; if (brand && typeof brand === "object") brand = brand.name || brand.title || "";
  let ratingValue = 0, ratingCount = 0; if (product.product_rating && typeof product.product_rating === "object") { ratingValue = parseNumber(product.product_rating.value); ratingCount = Number(product.product_rating.count || 0) || 0; }
  let signals = 1; if (old > current) signals++; if (String(chosen?.sku || "").toUpperCase() === requested) signals++;
  const liveDiscount = old > current ? ((old-current)/old)*100 : 0;
  if (liveDiscount >= 50 && signals < 2) throw new VerificationRejected("noon_extreme_discount_unconfirmed");
  const raw = JSON.stringify(product).toLowerCase();
  const flash = ["flash","limited time","deal of the day"].some(x => raw.includes(x));

  // Browser budget is reserved for suspicious/extreme Noon drops. It never creates a deal;
  // it only confirms that the exact EGP price is visible on the live product page.
  if (liveDiscount >= 50 && env.BROWSER && await canUseBrowser(repo, settings)) {
    const response: Response = await env.BROWSER.quickAction("scrape", {
      url: incoming.url,
      elements: [
        { selector: '[data-qa*="price" i]' },
        { selector: '[data-testid*="price" i]' },
        { selector: '[class*="price" i]' },
        { selector: '[aria-label*="EGP" i]' },
        { selector: '[itemprop="price"]' }
      ],
      gotoOptions: { waitUntil: "domcontentloaded", timeout: 20000 },
      waitForTimeout: 800,
      userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    });
    const ms = Number(response.headers.get("X-Browser-Ms-Used") || 0);
    if (ms > 0) await repo.counterAdd(`browser_ms:${new Date().toISOString().slice(0,10)}`, ms);
    if (!response.ok) throw new VerificationRejected(`noon_browser_http_${response.status}`);
    const payload: any = await response.json();
    const seen: number[] = [];
    for (const group of Array.isArray(payload?.result) ? payload.result : []) {
      for (const item of Array.isArray(group?.results) ? group.results : []) {
        for (const value of [item?.text, item?.html, ...(Array.isArray(item?.attributes) ? item.attributes.map((a:any)=>a?.value) : [])]) {
          const n = parseNumber(value); if (n > 0) seen.push(n);
        }
      }
    }
    const tolerance = Math.max(1, current * 0.01);
    if (!seen.some(v => Math.abs(v-current) <= tolerance)) throw new VerificationRejected("noon_live_price_not_visible");
    signals = Math.max(signals, 2);
  }

  const deal: DealCandidate = { ...incoming, external_id: String(product.sku || incoming.external_id), title, current_price: current, old_price: old || null,
    image_url: image, metadata: { ...(incoming.metadata || {}), brand: String(brand || ""), seller: String(offer.store_name || ""),
      offer_code: String(offer.offer_code || product.offer_code || ""), in_stock: offer.is_buyable !== false, stock: offer.stock,
      rating: ratingValue, review_count: ratingCount, locale: "en-eg", currency: "EGP", noon_catalog_api: true } };
  return { deal, meta: { http_via: "direct:noon_catalog_api", coupon_percent: 0, flash, verification_signals: Math.min(signals,3) } };
}

export async function verifyRow(env: V14Env, repo: D1Repository, settings: Settings, row: DealRow): Promise<{deal: DealCandidate; meta: Record<string, unknown>}> {
  const incoming = repo.rowToCandidate(row);
  if (incoming.store === "noon") return verifyNoon(env, repo, settings, incoming);
  try {
    const html = await fetchAmazonDirect(incoming.url);
    return amazonFromHtml(incoming, html, "direct");
  } catch (error) {
    const meta = safeJsonParse<Record<string, unknown>>(row.metadata_json, {});
    const visible = Number(row.visible_discount || 0);
    const strong = visible >= 50 || Boolean(meta.coupon_probe || meta.coupon_hint || meta.flash_hint || meta.goldbox);
    if (!strong) throw error;
    return browserScrapeAmazon(env, repo, settings, incoming);
  }
}
