import type { DealCandidate, DealRow, Settings, V14Env } from "./types";
import { D1Repository } from "./db";
import { parseNoon } from "./noon";
import { cleanText, discountPercent, isProtectedPage, parseNumber, pickAttr, safeJsonParse, stripTags } from "./util";

export class VerificationRejected extends Error {}

const BANK_OFFER_MARKERS = [
  "bank", "credit card", "debit card", "cardholder", "installment", "installments", "instalment", "instalments",
  "cib", "qnb", "nbk", "enbd", "visa", "mastercard", "mashreq", "emirates nbd", "fab", "adib", "hsbc", "al ahly", "nbe", "banque misr",
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
    if (v > 0 && v <= 99) return v;
  }
  return 0;
}

function couponEquivalentPercent(
  text: string,
  current: number,
): number {
  const normalized =
    String(text || "")
      .replace(
        /[٠-٩]/g,
        d =>
          String(
            "٠١٢٣٤٥٦٧٨٩".indexOf(d)
          )
      )
      .replace(/٫/g, ".")
      .replace(/٬/g, ",");

  let best =
    couponPercent(normalized);

  if (!(current > 0)) {
    return best;
  }

  const patterns = [
    /(?:EGP|جنيه(?:\s+مصري)?|ج\.?\s*م\.?)\s*([0-9][0-9,]*(?:\.[0-9]+)?)/gi,
    /([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:EGP|جنيه(?:\s+مصري)?|ج\.?\s*م\.?)/gi,
  ];

  for (const re of patterns) {
    let m: RegExpExecArray | null;

    while ((m = re.exec(normalized)) !== null) {
      const start =
        Math.max(0, m.index - 100);

      const end =
        Math.min(
          normalized.length,
          m.index + m[0].length + 100
        );

      const context =
        normalized
          .slice(start, end)
          .toLowerCase();

      /*
       * Fixed money only counts when it belongs
       * to an explicit product coupon/voucher.
       */
      if (
        ![
          "coupon",
          "voucher",
          "كوبون",
          "قسيمة",
          "خصم فوري",
        ].some(x => context.includes(x))
      ) {
        continue;
      }

      /*
       * Bank/card/installment offers are conditional,
       * never general product coupons.
       */
      if (
        BANK_OFFER_MARKERS.some(
          x => context.includes(x)
        )
      ) {
        continue;
      }

      const amount =
        parseNumber(m[1]);

      if (
        !(amount > 0) ||
        amount >= current * 0.95
      ) {
        continue;
      }

      const equivalent =
        (amount / current) * 100;

      if (
        equivalent > 0 &&
        equivalent <= 80
      ) {
        best =
          Math.max(
            best,
            equivalent
          );
      }
    }
  }

  return Math.min(
    99,
    Math.round(best * 100) / 100
  );
}


function extractExplicitAmazonCoupon(
  html: string,
  current: number,
): number {
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

    while (
      (m = re.exec(html)) !== null &&
      regions.length < 20
    ) {
      regions.push(
        stripTags(m[1])
      );
    }
  }

  let best = 0;

  for (const text of regions) {
    const low =
      text.toLowerCase();

    if (
      ![
        "coupon",
        "voucher",
        "كوبون",
        "قسيمة",
        "قسيمة خصم",
      ].some(x => low.includes(x))
    ) {
      continue;
    }

    best =
      Math.max(
        best,
        couponEquivalentPercent(
          text,
          current,
        ),
      );
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
        if (pct >= 5 && pct <= 99) best = Math.max(best, pct);
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
  const oldPriceWasLive = old > current;

  const savings = extractSavingsPercent(html);

  let signalCount =
    Math.max(1, repeatedSignals);

  if (
    !(old > current) &&
    savings >= 5 &&
    savings <= 99
  ) {
    const derived =
      current / (1 - savings / 100);

    if (
      derived >= current * 1.05 &&
      derived <= current * 105
    ) {
      old =
        Math.round(derived * 100) / 100;

      signalCount =
        Math.max(signalCount, 2);
    }
  }

  if (old > current) {
    signalCount =
      Math.max(signalCount, 2);
  }

  const liveDiscount =
    old > current
      ? ((old - current) / old) * 100
      : 0;

  /*
   * Strong Amazon-native proof:
   *
   * 1. current price exists on the product page
   * 2. struck/list price exists independently
   * 3. Amazon savings percentage agrees with both
   *
   * This is stronger than relying on a search result.
   */
  const savingsConsistent =
    oldPriceWasLive &&
    savings >= 5 &&
    Math.abs(savings - liveDiscount) <= 2.5;

  if (savingsConsistent) {
    signalCount =
      Math.max(signalCount, 3);
  }

  const coupon = extractExplicitAmazonCoupon(html, current);
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
    amazon_savings_percent: savings,
    amazon_old_price_live: oldPriceWasLive,
    amazon_savings_consistent: savingsConsistent,
    verification_signals: Math.max(1, signalCount) } };
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
      { selector: "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen" },
      { selector: "#buybox .a-price .a-offscreen" },
      { selector: "#price_inside_buybox" },
      { selector: "#newBuyBoxPrice" },
      { selector: ".a-price[data-a-size=\"xl\"] .a-offscreen" },
      { selector: ".apexPriceToPay .a-offscreen" },
      { selector: ".priceToPay .a-offscreen" },
      { selector: "#corePriceDisplay_desktop_feature_div .basisPrice .a-offscreen" },
      { selector: ".basisPrice .a-offscreen" },
      { selector: ".a-text-price .a-offscreen" },
      { selector: "#corePriceDisplay_desktop_feature_div .savingsPercentage" },
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
  const prices = texts([
    "#corePrice_feature_div .a-price .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen",
    "#buybox .a-price .a-offscreen",
    "#price_inside_buybox",
    "#newBuyBoxPrice",
    ".a-price[data-a-size=\"xl\"] .a-offscreen",
    ".apexPriceToPay .a-offscreen",
    ".priceToPay .a-offscreen",
  ]).map(parseNumber).filter((x: number) => x > 0);
  const { price: current, signals: repeated } = mostFrequentPrice(prices);
  if (!(current > 0)) throw new VerificationRejected("amazon_browser_no_price");
  let old = 0;

  for (
    const t of texts([
      "#corePriceDisplay_desktop_feature_div .basisPrice .a-offscreen",
      ".basisPrice .a-offscreen",
      ".a-text-price .a-offscreen"
    ])
  ) {
    const n = parseNumber(t);

    if (n > current) {
      old = Math.max(old, n);
    }
  }

  const oldPriceWasLive =
    old > current;

  let savings = 0;

  for (
    const t of texts([
      "#corePriceDisplay_desktop_feature_div .savingsPercentage",
      ".savingsPercentage"
    ])
  ) {
    const m =
      t.match(
        /-?\s*(\d+(?:\.\d+)?)\s*%/
      );

    if (m) {
      const pct = Number(m[1]);

      if (pct >= 5 && pct <= 99) {
        savings =
          Math.max(savings, pct);
      }
    }
  }

  let signals =
    Math.max(1, repeated);

  if (
    !(old > current) &&
    savings >= 5 &&
    savings <= 99
  ) {
    const d =
      current / (1 - savings / 100);

    if (
      d >= current * 1.05 &&
      d <= current * 105
    ) {
      old =
        Math.round(d * 100) / 100;

      signals =
        Math.max(signals, 2);
    }
  }

  if (old > current) {
    signals =
      Math.max(signals, 2);
  }

  const liveDiscount =
    old > current
      ? ((old - current) / old) * 100
      : 0;

  const savingsConsistent =
    oldPriceWasLive &&
    savings >= 5 &&
    Math.abs(savings - liveDiscount) <= 2.5;

  if (savingsConsistent) {
    signals =
      Math.max(signals, 3);
  }
  let coupon = 0;
  for (const t of texts(["#couponText","#couponFeature","#coupon_feature_div"])) {
    const low = t.toLowerCase();
    if (["coupon","voucher","كوبون","قسيمة"].some(x => low.includes(x))) coupon = Math.max(coupon, couponEquivalentPercent(t, current));
  }
  if (coupon > 0) signals = Math.max(signals, 2);
  const title = cleanText(texts(["#productTitle"])[0] || incoming.title) || incoming.title;
  let image = incoming.image_url || "";
  const imageRows = bySelector.get("#landingImage") || [];
  if (imageRows[0]) image = pickAttr(imageRows[0].attributes, "data-old-hires") || pickAttr(imageRows[0].attributes, "src") || image;
  return { deal: { ...incoming, title, current_price: current, old_price: old > current ? old : null, image_url: image },
    meta: { http_via: "browser_run", browser_ms: ms, coupon_percent: coupon, coupon_source: coupon ? "explicit_product_coupon" : "", flash: false,
      amazon_savings_percent: savings,
      amazon_old_price_live: oldPriceWasLive,
      amazon_savings_consistent: savingsConsistent,
      verification_signals: signals } };
}


async function browserRenderedAmazon(
  env: V14Env,
  repo: D1Repository,
  settings: Settings,
  incoming: DealCandidate,
): Promise<{
  deal: DealCandidate;
  meta: Record<string, unknown>;
}> {

  if (
    !env.BROWSER ||
    !(await canUseBrowser(repo, settings))
  ) {
    throw new VerificationRejected(
      "browser_budget_unavailable"
    );
  }

  const day =
    new Date().toISOString().slice(0, 10);

  const counterKey =
    `browser_ms:${day}`;

  let response: Response;

  try {
    response =
      await env.BROWSER.quickAction(
        "content",
        {
          url: incoming.url,

          gotoOptions: {
            waitUntil: "domcontentloaded",
            timeout: 20000,
          },

          waitForTimeout: 1200,

          userAgent:
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
            "AppleWebKit/537.36 (KHTML, like Gecko) " +
            "Chrome/140.0 Safari/537.36",

          setExtraHTTPHeaders: {
            "Accept-Language":
              "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
          },

          /*
           * We need DOM/text, not images.
           * This saves Browser Run budget.
           */
          rejectResourceTypes: [
            "image",
            "font",
            "media",
          ],
        },
      );
  } catch (e) {
    throw new VerificationRejected(
      `browser_content_error:${
        e instanceof Error
          ? e.message
          : String(e)
      }`
    );
  }

  const ms =
    Number(
      response.headers.get(
        "X-Browser-Ms-Used"
      ) || 0
    );

  if (ms > 0) {
    await repo.counterAdd(
      counterKey,
      ms,
    );
  }

  if (!response.ok) {
    throw new VerificationRejected(
      `browser_content_http_${response.status}`
    );
  }

  const html =
    await response.text();

  if (
    !html ||
    html.length < 1000
  ) {
    throw new VerificationRejected(
      "browser_content_empty"
    );
  }

  try {
    const parsed =
      amazonFromHtml(
        incoming,
        html,
        "browser_content",
      );

    return {
      deal: parsed.deal,

      meta: {
        ...parsed.meta,
        http_via: "browser_content",
        browser_ms: ms,
        rendered_dom: true,
      },
    };

  } catch (e) {
    if (e instanceof VerificationRejected) {
      throw new VerificationRejected(
        `browser_content_${e.message}`
      );
    }

    throw e;
  }
}

async function fetchAmazonDirect(url: string): Promise<string> {
  const r = await fetch(url, { headers: {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "accept-language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
    "accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8", "cache-control": "no-cache",
  },

  /*
   * AMAZON_DIRECT_VERIFY_TIMEOUT_V1
   */
  redirect: "follow",

  signal:
    AbortSignal.timeout(12000),

  });
  const text = await r.text();
  if (!r.ok) throw new Error(`amazon_direct_http_${r.status}`);
  return text;
}

function validNoonTitle(title: string): boolean {
  const t = cleanText(title); if (t.length < 5) return false;
  if (["placeholder","product","item","unknown","none","null","n/a","na"].includes(t.toLowerCase())) return false;
  return /[A-Za-z\u0600-\u06FF]/.test(t);
}

async function verifyNoon(
  env: V14Env,
  repo: D1Repository,
  settings: Settings,
  incoming: DealCandidate,
): Promise<{
  deal: DealCandidate;
  meta: Record<string, unknown>;
}> {

  void env;
  void repo;
  void settings;

  if (!incoming.external_id) {
    throw new VerificationRejected(
      "noon_sku_missing"
    );
  }

  let parsedUrl: URL;

  try {
    parsedUrl =
      new URL(incoming.url);
  } catch {
    throw new VerificationRejected(
      "noon_invalid_product_url"
    );
  }

  if (
    !(
      parsedUrl.hostname === "www.noon.com" ||
      parsedUrl.hostname === "noon.com"
    ) ||
    !(
      parsedUrl.pathname.includes("/egypt-en/") ||
      parsedUrl.pathname.includes("/egypt-ar/")
    )
  ) {
    throw new VerificationRejected(
      "noon_wrong_market"
    );
  }

  const r =
    await fetch(
      incoming.url,
      {
        headers: {
          "user-agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
            "AppleWebKit/537.36 (KHTML, like Gecko) " +
            "Chrome/140.0 Safari/537.36",

          "accept":
            "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",

          "accept-language":
            "en-EG,en;q=0.9,ar-EG;q=0.8,ar;q=0.7",

          "cache-control":
            "no-cache",
        },

        redirect:"follow",

        /*
         * NOON_PRODUCT_VERIFY_TIMEOUT_V1
         */
        signal:
          AbortSignal.timeout(12000),
      },
    );

  const html =
    await r.text();

  if (!r.ok) {
    throw new VerificationRejected(
      `noon_product_http_${r.status}`
    );
  }

  if (
    !html ||
    html.length < 1500
  ) {
    throw new VerificationRejected(
      "noon_product_empty"
    );
  }

  const low =
    html.toLowerCase();

  if (
    low.includes("access denied") ||
    low.includes("captcha") ||
    low.includes("unusual traffic")
  ) {
    throw new VerificationRejected(
      "noon_product_protected"
    );
  }

  const surface = {
    name:
      incoming.source ||
      "product_page",

    category:
      incoming.category ||
      "unknown",

    url:
      incoming.url,

    priority:1,
  };

  const parsed =
    parseNoon(
      html,
      surface,
    );

  const requested =
    incoming.external_id
      .trim()
      .toUpperCase();

  const exact =
    parsed.find(
      x =>
        String(
          x.external_id || ""
        )
          .trim()
          .toUpperCase()
        === requested
    );

  if (!exact) {
    throw new VerificationRejected(
      "noon_product_structured_data_missing"
    );
  }

  const current =
    Number(
      exact.current_price || 0
    );

  const old =
    Number(
      exact.old_price || 0
    );

  if (!(current > 0)) {
    throw new VerificationRejected(
      "noon_no_live_price"
    );
  }

  const title =
    cleanText(
      exact.title ||
      incoming.title
    );

  if (!validNoonTitle(title)) {
    throw new VerificationRejected(
      "noon_invalid_product_title"
    );
  }

  let signals = 2;

  if (old > current) {
    signals = 3;
  }

  const deal: DealCandidate = {
    ...incoming,

    external_id:
      requested,

    title,

    current_price:
      current,

    old_price:
      old > current
        ? old
        : null,

    image_url:
      exact.image_url ||
      incoming.image_url,

    metadata:{
      ...(incoming.metadata || {}),
      ...(exact.metadata || {}),
      noon_public_product_page:true,
      locale:"en-eg",
      currency:"EGP",
    },
  };

  return {
    deal,

    meta:{
      http_via:
        "direct:noon_public_product_page",

      rendered_dom:false,

      coupon_percent:0,

      flash:false,

      verification_signals:
        signals,
    },
  };
}

export async function verifyRow(
  env: V14Env,
  repo: D1Repository,
  settings: Settings,
  row: DealRow
): Promise<{
  deal: DealCandidate;
  meta: Record<string, unknown>;
}> {

  const incoming = repo.rowToCandidate(row);

  if (incoming.store === "noon") {
    return verifyNoon(
      env,
      repo,
      settings,
      incoming
    );
  }

  const discoveryMeta =
    safeJsonParse<Record<string, unknown>>(
      row.metadata_json,
      {}
    );

  const discoveryVisible =
    Number(row.visible_discount || 0);

  /*
   * Browser Run is reserved exclusively for Amazon Ultra.
   * Amazon Normal uses the cheap direct verification path only.
   */
  const strongUltraCandidate =
    discoveryVisible >=
      settings.ultra_min_discount;

  const strongCandidate =
    strongUltraCandidate;

  try {
    const html =
      await fetchAmazonDirect(incoming.url);

    const direct =
      amazonFromHtml(
        incoming,
        html,
        "direct"
      );

    const directVisible =
      discountPercent(direct.deal);

    const directCoupon =
      Number(
        direct.meta.coupon_percent || 0
      );

    const directSavings =
      Number(
        direct.meta.amazon_savings_percent
        || 0
      );

    /*
     * SMART CROSS-PAGE AMAZON PROOF
     *
     * Amazon frequently removes the crossed/list price
     * from the raw product HTML while keeping it visible
     * on search/deals surfaces.
     *
     * We may preserve that Amazon-origin old price ONLY
     * when:
     * - the discovery observation is fresh
     * - the exact product's live current price matches
     * - discovery had a genuine old > current pair
     * - the live product page does not contradict it
     *
     * >=90% remains stricter and still requires stronger
     * live/rendered evidence.
     */
    const discoveryCurrent =
      Number(incoming.current_price || 0);

    const discoveryOld =
      Number(incoming.old_price || 0);

    const directCurrent =
      Number(direct.deal.current_price || 0);

    const directOld =
      Number(direct.deal.old_price || 0);

    const currentGap =
      discoveryCurrent > 0 && directCurrent > 0
        ? Math.abs(
            directCurrent - discoveryCurrent
          ) / discoveryCurrent
        : 999;

    const discoveryAge =
      Math.max(
        0,
        Math.floor(Date.now() / 1000) -
          Number(row.updated_at || 0)
      );

    const crossPageProof =
      discoveryVisible >=
        settings.normal_min_discount &&
      discoveryVisible < 90 &&
      discoveryOld > discoveryCurrent &&
      discoveryCurrent > 0 &&
      directCurrent > 0 &&
      !(directOld > directCurrent) &&
      currentGap <= 0.015 &&
      discoveryAge <= 900;

    if (crossPageProof) {
      direct.deal.old_price =
        discoveryOld;

      direct.meta.verification_signals =
        Math.max(
          3,
          Number(
            direct.meta.verification_signals || 0
          )
        );

      direct.meta.amazon_cross_page_proof =
        true;

      direct.meta.amazon_live_current_match =
        true;

      direct.meta.amazon_discovery_discount =
        discoveryVisible;

      direct.meta.amazon_live_price_gap_pct =
        Math.round(
          currentGap * 10000
        ) / 100;

      return direct;
    }

    // Important:
    // Discovery discount is NEVER accepted as proof.
    // But a strong search/Goldbox lead should not be discarded just
    // because Amazon's first HTML response omitted dynamic savings.
    const directCouponCombined =
      100 -
      (
        (100 - Math.max(0, directVisible)) *
        (100 - Math.max(0, directCoupon))
      ) / 100;

    const directEffectiveEvidence =
      Math.max(
        directVisible,
        directSavings,
        directCouponCombined,
      );

    /*
     * A candidate discovered as Ultra must still
     * prove >=65% effective discount.
     * A 20% live discount may never silently pass
     * as proof of a discovered 70/80/90% offer.
     */
    const weakDirectEvidence =
      directEffectiveEvidence <
        (
          strongUltraCandidate
            ? settings.ultra_min_discount
            : settings.normal_min_discount
        );

    if (
      strongCandidate &&
      weakDirectEvidence
    ) {

      if (
        !env.BROWSER ||
        !(await canUseBrowser(
          repo,
          settings
        ))
      ) {
        if (strongUltraCandidate) {
          throw new VerificationRejected(
            "browser_budget_unavailable"
          );
        }

        return direct;
      }

      try {
        /*
         * For strong candidates use the fully rendered
         * Amazon DOM. This sees dynamic list-price /
         * savings blocks that raw Worker HTML may omit.
         */
        return await browserScrapeAmazon(
          env,
          repo,
          settings,
          incoming,
        );

      } catch (e) {

        /*
         * Never downgrade a >=65% candidate merely
         * because Browser/Amazon was temporarily
         * unavailable.
         */
        if (strongUltraCandidate) {
          throw e;
        }

        return direct;
      }
    }

    return direct;

  } catch (error) {

    if (!strongCandidate) {
      throw error;
    }

    // Strong candidate whose direct page was
    // protected/incomplete: use rendered DOM.
    return browserScrapeAmazon(
      env,
      repo,
      settings,
      incoming
    );
  }
}
