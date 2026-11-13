/** Diagnostic-only discovery from rendered markdown + accessibility tree.
 * No user authentication, retries, CAPTCHA handling or offer publication.
 */
export const SOURCE_URL = 'https://www.amazon.eg/b?node=27972173031';
const BASE = 'https://www.amazon.eg';
const ROOT_NODE = '27972173031';
const ID = /^[A-Z0-9]{10}$/i;

export function sameResalePage(value) {
  try {
    const u = new URL(value);
    return u.protocol === 'https:' && u.hostname === 'www.amazon.eg' && !u.username && !u.password && !u.port && (
      (/^\/b\/?$/.test(u.pathname) && u.searchParams.get('node') === ROOT_NODE) ||
      (/^\/l\/27972173031\/?$/.test(u.pathname)) ||
      (/^\/s\/?$/.test(u.pathname) && (u.searchParams.get('rh')||'').split(',').includes('n:'+ROOT_NODE))
    );
  } catch { return false; }
}

function classifyHref(raw) {
  try {
    const u = new URL(String(raw || '').replace(/&amp;/gi,'&'), BASE);
    if (u.protocol !== 'https:' || !['www.amazon.eg','amazon.eg'].includes(u.hostname) || u.username || u.password || u.port) return null;
    const m = u.pathname.match(/^\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:\/|$)/i);
    if (m && ID.test(m[1])) return {type:'product', id:m[1].toUpperCase(),url:`${BASE}/dp/${m[1].toUpperCase()}`};
    const node = /^\/b\/?$/.test(u.pathname) || /^\/gp\/browse\.html$/.test(u.pathname) ? u.searchParams.get('node') : null;
    if (node && /^\d{6,20}$/.test(node) && node!==ROOT_NODE) return {type:'category', id:node, url:`${BASE}/b?node=${node}`};
    const l = u.pathname.match(/^\/l\/(\d{6,20})\/?$/);
    if (l && l[1] !== ROOT_NODE) return {type:'category', id:l[1], url:`${BASE}/l/${l[1]}`};
  } catch {}
  return null;
}

export function analyzeResaleSnapshot(data) {
  const result = data?.result || {};
  const markdown = typeof result?.markdown === 'string' ? result.markdown.slice(0,500_000) : '';
  const tree = result?.accessibilityTree;
  const links = new Map();
  let visited = 0, accessibilityLinks = 0;
  const stack = tree && typeof tree === 'object' ? [tree] : [];
  while (stack.length && visited < 12000) {
    const cur = stack.pop(); visited++;
    if (!cur || typeof cur !== 'object') continue;
    if (String(cur.role || '').toLowerCase() === 'link') accessibilityLinks++;
    for (const candidate of [cur.url,cur.href]) {
      const parsed = classifyHref(candidate);
      if (parsed) links.set(parsed.type+':'+parsed.id, parsed);
    }
    const children = Array.isArray(cur.children) ? cur.children : [];
    for (let i=children.length-1;i>=0;i--) stack.push(children[i]);
  }
  // Markdown links may be rendered even when the CSS scrape returns empty product nodes.
  const mdLinks = markdown.matchAll(/\]\((https?:\/\/[^\s)]+|\/[^\s)]+)\)/gi);
  for (const match of mdLinks) {
    const parsed = classifyHref(match[1]);
    if (parsed) links.set(parsed.type+':'+parsed.id, parsed);
  }
  const products = [...links.values()].filter(x=>x.type==='product').slice(0,20);
  const categories = [...links.values()].filter(x=>x.type==='category').slice(0,20);
  const title = String(data?.meta?.title || tree?.name || '').slice(0,140);
  const likelyResale = /amazon\s*(?:resale|warehouse)|أمازون\s*المستعمل|مستعمل|مفتوح(?:ة)?\s*العلبة/i.test(markdown.slice(0,15000)+' '+title);
  const captcha = /(?:captcha|enter the characters|أدخل الحروف|اكتب الأحرف)/i.test(markdown.slice(0,3000)+' '+title);
  return {
    source_title:title, markdown_length:markdown.length,
    markdown_excerpt:markdown.replace(/\s+/g,' ').slice(0,340),
    accessibility_nodes_seen:visited, accessibility_links_seen:accessibilityLinks,
    resale_text_signal:likelyResale, captcha_text_signal:captcha,
    product_candidates:products.map(x=>({asin:x.id,url:x.url,used_offer_verified:false})),
    category_link_candidates:categories.map(x=>x.url),
    product_candidate_count:products.length,
    category_link_count:categories.length,
    verified_used_offers:0, public_posting_enabled:false,
  };
}
