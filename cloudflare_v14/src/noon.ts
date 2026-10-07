import type { DealCandidate, Surface } from "./types";
import { cleanText, extractBalancedObject, parseNumber } from "./util";

const BASE = "https://www.noon.com";
const SEARCH = `${BASE}/egypt-en/search/`;
const PUBLIC: Record<string, string> = {
  mobiles: `${BASE}/egypt-en/electronics-and-mobiles/mobiles-and-accessories/mobiles-20905/category/?isCarouselView=false&limit=50`,
  laptops: `${BASE}/egypt-en/electronics-and-mobiles/computers-and-accessories/computers-new/laptops/all-products-eg/?isCarouselView=false&limit=50`,
  appliances: `${BASE}/egypt-en/home-and-kitchen/home-appliances-31235/home-appliances-31235/?isCarouselView=false&limit=50`,
};

const s = (name: string, category: string, query: string, priority = 1): Surface => ({
  name, category, priority,
  url: PUBLIC[name] || `${SEARCH}?q=${encodeURIComponent(query)}&isCarouselView=false&limit=50`,
});

export const NOON_SURFACES: Surface[] = [
  s("mobiles","mobiles","mobile phones",1.7), s("laptops","computers","laptops",1.7), s("appliances","appliances","home appliances",1.6),
  s("tablets","computers","tablets",1.35), s("tvs","electronics","televisions",1.35), s("audio","electronics","headphones earbuds speakers",1.25),
  s("gaming","electronics","gaming",1.2), s("smartwatches","electronics","smart watches",1.15), s("mobile_accessories","mobiles","mobile accessories"),
  s("computer_accessories","computers","computer accessories"), s("kitchen","kitchen","kitchen appliances",1.25), s("small_appliances","appliances","small appliances",1.15),
  s("home","home","home decor"), s("tools","tools","tools home improvement"), s("beauty","beauty","beauty"), s("personal_care","beauty","personal care"),
  s("men_fashion","fashion","men fashion",1.05), s("women_fashion","fashion","women fashion",1.05), s("kids_fashion","fashion","kids fashion"),
  s("shoes","fashion","shoes"), s("bags","fashion","bags",0.95), s("watches","fashion","watches",0.95), s("sports","sports","sports fitness"),
  s("toys","toys","toys",0.95), s("baby","baby","baby",0.95), s("grocery","grocery","grocery"), s("coffee","grocery","coffee",0.9),
  s("detergents","grocery","detergent cleaning",0.9), s("automotive","automotive","car accessories",0.9), s("office","office","office supplies",0.85),
];

function first(obj: Record<string, any>, keys: string[]): any {
  for (const key of keys) {
    const v = obj?.[key];
    if (v !== undefined && v !== null && v !== "" && !(Array.isArray(v) && !v.length)) return v;
  }
  return undefined;
}

function canonicalProductUrl(hit: Record<string, any>, sku: string): string {
  const raw = String(first(hit, ["url","url_slug","urlKey","canonical_url"]) || "").trim();
  if (raw.startsWith("http")) {
    const m = raw.match(/\/(?:uae|saudi|egypt)-en\/([^/]+)\/[A-Z0-9]+\/p\/?/i);
    return m ? `${BASE}/egypt-en/${m[1]}/${sku}/p/` : raw;
  }
  let slug = raw.replace(/^\/+|\/+$/g, "");
  if (slug.includes("/")) {
    const parts = slug.split("/").filter(Boolean);
    if (parts.at(-1)?.toLowerCase() === "p") parts.pop();
    if (parts.at(-1)?.toUpperCase() === sku.toUpperCase()) parts.pop();
    slug = parts.at(-1) || "";
  }
  return slug ? `${BASE}/egypt-en/${slug}/${sku}/p/` : `${BASE}/egypt-en/${sku}/p/`;
}

function candidateFromHit(hit: Record<string, any>, surface: Surface): DealCandidate | null {
  const sku = cleanText(first(hit, ["sku","catalog_sku","sku_config","product_sku","id"]) || "");
  const title = cleanText(first(hit, ["name","title","product_name","productName","product_title","productTitle"]) || "");
  let old = parseNumber(first(hit, ["price","old_price","oldPrice","regular_price","regularPrice"]));
  let current = parseNumber(first(hit, ["sale_price","salePrice","offer_price","offerPrice"]));
  if (!(current > 0)) current = old;
  if (!sku || !title || !(current > 0)) return null;
  if (!(old > current)) old = 0;
  if (hit?.is_buyable === false) return null;
  let image: any = first(hit, ["image_url","imageUrl","thumbnailUrl","primaryImage","image"]);
  if (image && typeof image === "object" && !Array.isArray(image)) image = first(image, ["url","src"]);
  else if (Array.isArray(image) && image.length) image = typeof image[0] === "object" ? first(image[0], ["url","src"]) : image[0];
  let brand: any = first(hit, ["brand","brand_name","brandName"]);
  if (brand && typeof brand === "object") brand = first(brand, ["name","title"]);
  const rating = hit?.product_rating;
  const ratingValue = rating && typeof rating === "object" ? parseNumber(rating.value) : 0;
  const ratingCount = rating && typeof rating === "object" ? Number(rating.count || 0) : 0;
  return {
    store: "noon", external_id: sku, title, url: canonicalProductUrl(hit, sku), current_price: current,
    old_price: old || null, image_url: String(image || ""), category: surface.category, source: surface.name,
    metadata: { api_source: true, locale: "en-eg", currency: "EGP", brand: String(brand || ""),
      offer_code: String(hit?.offer_code || ""), rating: ratingValue, review_count: Number.isFinite(ratingCount) ? ratingCount : 0,
      in_stock: hit?.is_buyable == null ? true : Boolean(hit.is_buyable) },
  };
}

function recursiveCandidates(obj: any, surface: Surface, out: DealCandidate[], seen: Set<string>, depth = 0): void {
  if (depth > 14 || out.length >= 60) return;
  if (Array.isArray(obj)) {
    for (const v of obj) recursiveCandidates(v, surface, out, seen, depth + 1);
    return;
  }
  if (!obj || typeof obj !== "object") return;
  const hit = candidateFromHit(obj, surface);
  if (hit && !seen.has(hit.external_id)) { seen.add(hit.external_id); out.push(hit); }
  for (const v of Object.values(obj)) recursiveCandidates(v, surface, out, seen, depth + 1);
}

function parseDirectJson(
  text: string,
  surface: Surface
): DealCandidate[] | null {

  const raw = text.trimStart();

  if (!(raw.startsWith("{") || raw.startsWith("["))) {
    return null;
  }

  try {
    const data = JSON.parse(raw);

    const out: DealCandidate[] = [];
    const seen = new Set<string>();

    const add = (candidate: DealCandidate | null) => {
      if (!candidate) return;

      const id = String(candidate.external_id || "").trim();

      if (!id || seen.has(id)) return;

      seen.add(id);
      out.push(candidate);
    };

    if (
      data
      && typeof data === "object"
      && !Array.isArray(data)
      && Array.isArray(data.hits)
    ) {
      const metaText =
        JSON.stringify(data.meta || {}).toLowerCase();

      if (
        metaText.includes("dubai")
        || metaText.includes("abu dhabi")
        || metaText.includes("united arab emirates")
        || metaText.includes('"country":"ae"')
      ) {
        return [];
      }

      /*
       * Noon usually exposes a flat hit:
       *   sku/name/price/sale_price/...
       *
       * But some responses wrap those fields deeper inside each hit.
       * Try the direct shape first, then recursively inspect that hit.
       */
      for (const hit of data.hits) {
        if (out.length >= 60) break;

        if (hit && typeof hit === "object") {
          add(candidateFromHit(hit, surface));

          recursiveCandidates(
            hit,
            surface,
            out,
            seen
          );
        }
      }

      return out;
    }

    recursiveCandidates(
      data,
      surface,
      out,
      seen
    );

    return out;

  } catch {
    return null;
  }
}
export function parseNoon(text: string, surface: Surface): DealCandidate[] {
  const direct = parseDirectJson(text, surface);
  if (direct !== null) return direct;
  const out: DealCandidate[] = []; const seen = new Set<string>();
  const scriptRe = /<script\b[^>]*(?:type=["'](?:application\/json|application\/ld\+json)["']|id=["'][^"']*__NEXT_DATA__[^"']*["'])[^>]*>([\s\S]*?)<\/script>/gi;
  let m: RegExpExecArray | null;
  while ((m = scriptRe.exec(text)) !== null && out.length < 60) {
    const raw = m[1].trim();
    if (!raw || raw.length > 1_800_000) continue;
    try { recursiveCandidates(JSON.parse(raw), surface, out, seen); } catch {}
  }
  if (out.length) return out;

  // Last-resort structured-object extraction around known SKU markers.
  let pos = 0;
  const marker = '"sku"';
  while (out.length < 30) {
    const idx = text.indexOf(marker, pos);
    if (idx < 0) break;
    const start = text.lastIndexOf("{", idx);
    if (start >= 0 && idx - start < 8000) {
      const raw = extractBalancedObject(text, start);
      if (raw && raw.length < 60000) {
        try { recursiveCandidates(JSON.parse(raw), surface, out, seen); } catch {}
      }
    }
    pos = idx + marker.length;
  }
  return out;
}


const NOON_QUERY_BY_SOURCE: Record<string, string> = {
  mobiles: "mobile phones",
  laptops: "laptops",
  appliances: "home appliances",
  tablets: "tablets",
  tvs: "televisions",
  audio: "headphones earbuds speakers",
  gaming: "gaming",
  smartwatches: "smart watches",
  mobile_accessories: "mobile accessories",
  computer_accessories: "computer accessories",
  kitchen: "kitchen appliances",
  small_appliances: "small appliances",
  home: "home decor",
  tools: "tools home improvement",
  beauty: "beauty",
  personal_care: "personal care",
  men_fashion: "men fashion",
  women_fashion: "women fashion",
  kids_fashion: "kids fashion",
  shoes: "shoes",
  bags: "bags",
  watches: "watches",
  sports: "sports fitness",
  toys: "toys",
  baby: "baby",
  grocery: "grocery",
  coffee: "coffee",
  detergents: "detergent cleaning",
  automotive: "car accessories",
  office: "office supplies",
};

function noonSurfaceQuery(surface: Surface): string {
  try {
    const u = new URL(surface.url);
    const q = String(u.searchParams.get("q") || "").trim();
    if (q) return q;
  } catch {}

  return NOON_QUERY_BY_SOURCE[surface.name] || surface.name;
}

async function fetchNoonApiUrl(url: string): Promise<string> {
  const res = await fetch(url, {
    headers: {
      "accept": "application/json,text/plain,*/*",
      "x-locale": "en-eg",
      "x-mp-country": "eg",
      "referer": "https://www.noon.com/egypt-en/",
    },
    redirect: "follow",
  });

  const text = await res.text();

  if (!res.ok) {
    throw new Error(`noon_api_http_${res.status}`);
  }

  const trimmed = text.trimStart();

  if (!(trimmed.startsWith("{") || trimmed.startsWith("["))) {
    throw new Error("noon_api_not_json");
  }

  let data: any;

  try {
    data = JSON.parse(trimmed);
  } catch {
    throw new Error("noon_api_invalid_json");
  }

  const metaText = JSON.stringify(
    data?.meta || {}
  ).toLowerCase();

  if (
    metaText.includes("dubai") ||
    metaText.includes("abu dhabi") ||
    metaText.includes("united arab emirates") ||
    metaText.includes('"country":"ae"')
  ) {
    throw new Error("noon_api_wrong_market");
  }

  if (!Array.isArray(data?.hits)) {
    throw new Error("noon_api_hits_missing");
  }

  // For the broad discovery queries used by V14, zero hits usually means
  // the request was not routed to the intended Egypt catalog.
  if (!data.hits.length) {
    throw new Error("noon_api_empty_hits");
  }

  return text;
}

export async function fetchNoonSurface(
  surface: Surface
): Promise<{text: string; latency: number}> {

  const started = Date.now();

  /*
   * Public catalog pages only.
   *
   * Noon currently rejects the internal /_vs API
   * from Cloudflare, so V14 no longer depends on it.
   */
  if (
    surface.url.includes("/search/") ||
    surface.url.includes("/_vs/")
  ) {
    throw new Error(
      "noon_public_catalog_surface_required"
    );
  }

  const res = await fetch(
    surface.url,
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
    },
  );

  const text =
    await res.text();

  if (!res.ok) {
    throw new Error(
      `noon_public_http_${res.status}`
    );
  }

  if (
    !text ||
    text.length < 2000
  ) {
    throw new Error(
      "noon_public_empty_page"
    );
  }

  const low =
    text.toLowerCase();

  if (
    low.includes("access denied") ||
    low.includes("captcha") ||
    low.includes("unusual traffic")
  ) {
    throw new Error(
      "noon_public_protected"
    );
  }

  return {
    text,
    latency:
      Date.now() - started,
  };
}
