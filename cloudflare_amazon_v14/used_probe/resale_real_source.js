/** Inspect evidence from a documented Amazon Egypt Resale /l/ landing.
 * A link/ASIN found here is not proof of an active used offer. */
export const RESALE_REAL_URL = 'https://www.amazon.eg/b?node=27972173031';
const ORIGIN = 'https://www.amazon.eg';
const ASIN_RE = /^[A-Z0-9]{10}$/;

export function validResaleRealDestination(value) {
  try {
    const u = new URL(String(value));
    if (u.protocol !== 'https:' || u.hostname !== 'www.amazon.eg' || u.username || u.password || u.port) return false;
    if (u.pathname === '/l/27972173031' || u.pathname === '/l/27972173031/') return true;
    if (/^\/b\/?$/.test(u.pathname) && u.searchParams.get('node') === '27972173031') return true;
    if (/^\/s\/?$/.test(u.pathname) && (u.searchParams.get('rh') || '').split(',').includes('n:27972173031')) return true;
    return false;
  } catch { return false; }
}

function field(item, key) {
  if (typeof item?.[key] === 'string') return item[key];
  if (Array.isArray(item?.attributes)) {
    const found = item.attributes.find(x => String(x?.name || '').toLowerCase() === key);
    if (found) return String(found.value || '');
  } else if (item?.attributes && typeof item.attributes === 'object') {
    for (const [name,value] of Object.entries(item.attributes))
      if (name.toLowerCase() === key) return String(value || '');
  }
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const found = String(item?.html || '').match(new RegExp('\\b'+escaped+'\\s*=\\s*(["\\\'])(.*?)\\1','i'));
  return found ? found[2].replace(/&amp;/gi, '&') : '';
}
function productAsin(item) {
  const direct = field(item, 'data-asin').toUpperCase();
  if (ASIN_RE.test(direct)) return direct;
  const h = field(item, 'href');
  try {
    const u = new URL(h, ORIGIN);
    if (u.protocol !== 'https:' || u.hostname !== 'www.amazon.eg') return null;
    const x = u.pathname.match(/^\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:\/|$)/i);
    return x ? x[1].toUpperCase() : null;
  } catch { return null; }
}
function categoryLink(item) {
  try {
    const h = field(item,'href');
    if (!h) return null;
    const u = new URL(h, RESALE_REAL_URL);
    if (u.protocol !== 'https:' || u.hostname !== 'www.amazon.eg' || u.username || u.password || u.port) return null;
    if (/^\/l\/\d{6,20}\/?$/.test(u.pathname) && u.pathname !== '/l/27972173031') return ORIGIN + u.pathname;
    if (/^\/b\/?$/.test(u.pathname) && /^\d{6,20}$/.test(u.searchParams.get('node')||'')) return `${ORIGIN}/b?node=${u.searchParams.get('node')}`;
    return null;
  } catch { return null; }
}
export function inspectRealResaleLanding(data) {
  const groups = Array.isArray(data?.result) ? data.result : [];
  const products = new Set(), categories = new Set(), context = [];
  let elements = 0, links = 0, captcha = false;
  for (const g of groups) {
    const selector = String(g?.selector || '');
    const items = Array.isArray(g?.results) ? g.results.slice(0,250) : [];
    if (/captcha|captchacharacters/i.test(selector) && items.length) captcha = true;
    if (/^(title|h1|#mainContent|#search|#desktop-grid)$/.test(selector) && items.length) {
      const t = String(items[0]?.text || '').replace(/\s+/g,' ').trim();
      if (t) context.push({selector, sample:t.slice(0,260)});
    }
    if (!/data-asin|s-card-container|s-search-result|href/i.test(selector)) continue;
    for (const item of items) {
      elements++;
      const href = field(item,'href');
      if (href) links++;
      const asin = productAsin(item);
      if (asin && products.size < 30) products.add(asin);
      // Browsing navigation is only a candidate; never follow sitewide links automatically.
      if (/^#mainContent|^#desktop-grid|^\.bxc-grid/.test(selector)) {
        const c = categoryLink(item);
        if (c && categories.size < 30) categories.add(c);
      }
    }
  }
  return {
    inspected_elements:elements,
    anchors_with_href:links,
    has_captcha_elements:captcha,
    page_context:context.slice(0,5),
    candidate_count:products.size,
    candidates:[...products].map(asin=>({asin,product_url:`${ORIGIN}/dp/${asin}`,used_price_verified:false,seller_verified:false,stock_verified:false,status:'SOURCE_PRODUCT_CANDIDATE_ONLY'})),
    category_link_candidates:[...categories],category_count:categories.size,
    verified_used_offers:0,
  };
}
