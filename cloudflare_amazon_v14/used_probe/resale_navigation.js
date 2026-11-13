/**
 * Read-only Amazon.eg Resale storefront navigation diagnostics.
 * A link or product identifier is discovery evidence, NOT a used offer or purchase proof.
 */
import {extractResaleListing} from './resale_source.js';

const ORIGIN = 'https://www.amazon.eg';
const RESALE_NODE = '27972175031';

function rawAttribute(item, name) {
  const direct = item?.[name];
  if (typeof direct === 'string') return direct;
  const attrs = item?.attributes;
  if (Array.isArray(attrs)) {
    const match = attrs.find(a => String(a?.name || '').toLowerCase() === name);
    if (match) return String(match.value || '');
  } else if (attrs && typeof attrs === 'object') {
    for (const key of Object.keys(attrs)) {
      if (key.toLowerCase() === name) return String(attrs[key] || '');
    }
  }
  const html = String(item?.html || '');
  const match = html.match(new RegExp('\\b' + name + '\\s*=\s*(["\'])(.*?)\\1', 'i'));
  return match ? match[2].replace(/&amp;/gi, '&') : '';
}

export function normalizeAmazonCategoryLink(href, base = `${ORIGIN}/b?node=${RESALE_NODE}`) {
  let u;
  try { u = new URL(String(href || ''), base); } catch { return null; }
  if (u.protocol !== 'https:' || !['www.amazon.eg', 'amazon.eg'].includes(u.hostname)) return null;
  if (u.username || u.password || u.port) return null;
  // Category links only; never a login, basket, redirect, product purchase or third-party page.
  let type = '';
  if (/^\/b\/?$/.test(u.pathname)) {
    const node = u.searchParams.get('node');
    if (!/^\d{4,20}$/.test(node || '') || node === RESALE_NODE) return null;
    type = 'browse_node';
  } else if (/^\/gp\/browse\.html$/.test(u.pathname)) {
    const node = u.searchParams.get('node');
    if (!/^\d{4,20}$/.test(node || '') || node === RESALE_NODE) return null;
    type = 'browse_node';
  } else if (/^\/s\/?$/.test(u.pathname)) {
    const rh = u.searchParams.get('rh') || '';
    const node = u.searchParams.get('node') || '';
    // Search result categories must have actual category constraints, not a general search.
    if (!/(?:^|[,;])n:\d{4,20}/.test(rh) && !/^\d{4,20}$/.test(node)) return null;
    type = 'category_results';
  } else return null;
  // Strip unnecessary tracking/search params; preserve only constrained navigation parameters.
  const clean = new URL(`${ORIGIN}${u.pathname}`);
  for (const k of ['node', 'rh', 'i']) {
    if (u.searchParams.has(k)) clean.searchParams.set(k, u.searchParams.get(k));
  }
  return {url: clean.toString(), kind: type};
}

export function analyzeResaleNavigation(data, base, limit = 18) {
  const groups = Array.isArray(data?.result) ? data.result : [];
  const context = [];
  const candidates = new Map();
  let anchorElements = 0;
  let linkElementsWithHref = 0;
  let captcha = false;
  for (const group of groups) {
    const selector = String(group?.selector || '');
    const items = Array.isArray(group?.results) ? group.results : [];
    if (/captcha|captchacharacters/i.test(selector) && items.length) captcha = true;
    if (/^(?:h1|title|body|#mainContent|#desktop-grid)$/.test(selector)) {
      for (const item of items.slice(0, 2)) {
        const t = String(item?.text || '').replace(/\s+/g, ' ').trim();
        if (t) context.push({selector, sample: t.slice(0, selector === 'body' ? 300 : 180)});
      }
    }
    if (!/a\[href|a\[|\sa$|^a$/.test(selector)) continue;
    for (const item of items.slice(0, 350)) {
      anchorElements++;
      const href = rawAttribute(item, 'href');
      if (href) linkElementsWithHref++;
      const link = normalizeAmazonCategoryLink(href, base);
      if (!link) continue;
      const label = String(item?.text || '').replace(/\s+/g, ' ').trim().slice(0, 85);
      if (!candidates.has(link.url)) candidates.set(link.url, {url: link.url, kind: link.kind, label, source_selector:selector, verified_category: false});
    }
  }
  const listing = extractResaleListing(data, 20);
  const all = [...candidates.values()];
  // A broad anchor scan may include sitewide navigation: prioritize navigation inside main content.
  const isMain = s => /#main|#desktop-grid|\.bxc-grid|main |#zg_browseRoot/.test(s);
  all.sort((a,b) => Number(isMain(b.source_selector)) - Number(isMain(a.source_selector)));
  return {
    inspected_groups:groups.length,
    anchor_elements: anchorElements,
    anchors_with_href: linkElementsWithHref,
    body_context:context.slice(0,5),
    has_captcha_elements:captcha,
    navigation_candidates:all.slice(0, limit),
    navigation_total_found:all.length,
    product_candidates:listing.products,
    product_count:listing.products.length,
    // One follow-up page only, and ONLY when a main-content category link is available.
    category_probe_url: all.find(x => isMain(x.source_selector))?.url || null,
  };
}
