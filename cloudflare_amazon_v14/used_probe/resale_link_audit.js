/** One-read, metadata-safe diagnostic of Amazon Resale snapshot link shapes.
 * No login, checkout, retries, scraping bypasses, or public offer claims.
 */
export const AUDIT_URL = 'https://www.amazon.eg/b?node=27972173031';
const ROOT = '27972173031';
const HOST = 'www.amazon.eg';
const TOKEN = /^[A-Z0-9]{10}$/i;

export function validAuditDestination(raw) {
  try {
    const u = new URL(String(raw));
    if (u.protocol!=='https:' || u.hostname!==HOST || u.username || u.password || u.port) return false;
    return (/^\/b\/?$/.test(u.pathname) && u.searchParams.get('node')===ROOT)
      || /^\/l\/27972173031\/?$/.test(u.pathname)
      || (/^\/s\/?$/.test(u.pathname) && (u.searchParams.get('rh')||'').split(',').includes('n:'+ROOT));
  } catch { return false; }
}
function target(raw){
  try {
    const u = new URL(String(raw||'').replace(/&amp;/gi,'&'), 'https://www.amazon.eg');
    if(u.protocol !== 'https:' || !['www.amazon.eg','amazon.eg'].includes(u.hostname) || u.username || u.password || u.port)return {kind:'external'};
    const path = u.pathname;
    // Amazon commonly prefixes the /dp/<ASIN> route with a product-name slug.
    const match=path.match(/(?:^|\/)dp\/([A-Z0-9]{10})(?:\/|$)|(?:^|\/)gp\/product\/([A-Z0-9]{10})(?:\/|$)|(?:^|\/)gp\/aw\/d\/([A-Z0-9]{10})(?:\/|$)/i);
    const asin=(match?.[1]||match?.[2]||match?.[3]||'').toUpperCase();
    if(TOKEN.test(asin))return {kind:'product',asin,url:`https://www.amazon.eg/dp/${asin}`};
    if (/^\/b\/?$/.test(path) || /^\/gp\/browse\.html$/.test(path)) {
      const node=u.searchParams.get('node')||'';
      if(/^\d{6,20}$/.test(node) && node!==ROOT)return {kind:'category',url:`https://www.amazon.eg/b?node=${node}`};
    }
    const m=path.match(/^\/l\/(\d{6,20})\/?$/);
    if(m && m[1]!==ROOT)return {kind:'category',url:`https://www.amazon.eg/l/${m[1]}`};
    if(/^\/s\/?$/.test(path))return {kind:'search_general'};
    const prefix=path.split('/').filter(Boolean).slice(0,2).join('/');
    // Only path family, never query values, cookies, full URLs or user identifiers.
    if (/^\/gp\//.test(path))return {kind:'navigation_gp'};
    if(/^\/ap\//.test(path))return {kind:'account'};
    if(/^\/b\/?$/.test(path)||/^\/l\//.test(path))return {kind:'navigation_section'};
    return {kind:prefix ? 'other_amazon_path' : 'amazon_root'};
  } catch {return {kind:'invalid_url'};}
}
function markdownUrls(text) {
  const out=[];
  // Markdown often wraps product URLs in ordinary link syntax; include bare absolute URLs as audit-only.
  for(const m of text.matchAll(/\]\((https?:\/\/[^\s)]+|\/[^\s)]+)\)/gi)) out.push(m[1]);
  return out;
}
export function auditResaleLinks(data){
  const result=data?.result||{};
  const markdown=typeof result.markdown==='string'?result.markdown.slice(0,500000):'';
  const front=markdown.match(/^---\s*\n([\s\S]*?)\n---\s*\n/);
  const meta=front?front[1]:'';
  const body=front?markdown.slice(front[0].length):markdown;
  const keyShapes={};const kinds={};const products=new Map();const categories=new Set();
  let linkRoles=0,withHref=0,visited=0;
  const stack=result.accessibilityTree&&typeof result.accessibilityTree==='object'?[result.accessibilityTree]:[];
  const register=(href)=>{
    if(!href)return;
    const x=target(href);
    kinds[x.kind]=(kinds[x.kind]||0)+1;
    if(x.kind==='product' && products.size<20)products.set(x.asin,x.url);
    if(x.kind==='category' && categories.size<20)categories.add(x.url);
  };
  while(stack.length && visited<15000){
    const n=stack.pop();visited++;
    if(!n || typeof n!=='object')continue;
    if(String(n.role||'').toLowerCase()==='link'){
      linkRoles++;
      const present=['href','url','link','target'].filter(k=>typeof n[k]==='string' && n[k].length>0);
      const shape=present.length?present.sort().join('+'):'NO_LINK_TARGET';
      keyShapes[shape]=(keyShapes[shape]||0)+1;
      if(present.length)withHref++;
      for(const k of present)register(n[k]);
    }
    const children=Array.isArray(n.children)?n.children:[];
    for(let i=children.length-1;i>=0;i--) stack.push(children[i]);
  }
  const md=markdownUrls(markdown);
  for(const href of md)register(href);
  // SAFE_RESALE_CONTEXT_V13: read the SAME already-loaded source markdown only.
  // A price marker or "used" in the same markdown line is not seller/stock proof.
  const contexts=new Map();
  for(const match of body.matchAll(/\[([^\]\n]{1,160})\]\(((?:https?:\/\/|\/)[^\s)]+)\)/gi)) {
    const route=target(match[2]);
    if(route.kind!=='product')continue;
    const begin=body.lastIndexOf('\n',match.index-1)+1;
    const finish=body.indexOf('\n',match.index+match[0].length);
    const line=body.slice(begin,finish<0?Math.min(body.length,begin+1600):finish).slice(0,1600);
    const used=/(?:\bused\b|amazon\s*resale|مستعمل(?:ة)?|مفتوح(?:ة)?\s*العلبة|open[ -]?box)/i.test(line);
    const currency=/(?:\bEGP\b|جنيه|ج\s*\.?\s*م\.?)/i.test(line);
    const previous=contexts.get(route.asin);
    const score=Number(used)+Number(currency);
    if(!previous||score>previous.score)contexts.set(route.asin,{
      label:match[1].replace(/[<>]/g,'').slice(0,100),used,currency,score
    });
  }
  const resale=/amazon\s*(?:resale|warehouse)|أمازون\s*المستعمل|مستعمل|مفتوح(?:ة)?\s*العلبة/i;
  const metadataResale=resale.test(meta);
  const bodyResale=resale.test(body);
  const captcha=/(?:captcha|enter the characters|أدخل الحروف|اكتب الأحرف)/i.test(body.slice(0,5000));
  const diagnosis=products.size?'POSSIBLE_PRODUCT_ROUTES_REVIEW_ONLY':categories.size?'POSSIBLE_CATEGORY_ROUTES_REVIEW_ONLY'
    : (!bodyResale && metadataResale?'RESALE_KEYWORD_METADATA_ONLY_NO_LISTING_PROOF':
      !withHref && linkRoles?'ACCESSIBILITY_LINKS_HAVE_NO_HREF':
      'SNAPSHOT_NO_RESALE_LISTING_LINKS');
  return {diagnosis,markdown_length:markdown.length,front_matter_length:meta.length,
    resale_keyword_in_metadata:metadataResale,resale_keyword_in_body:bodyResale, captcha_text_signal:captcha,
    accessibility_nodes_seen:visited,accessibility_link_roles:linkRoles,
    accessibility_link_roles_with_target:withHref,accessibility_link_property_shapes:keyShapes,
    markdown_links_seen:md.length,link_kind_counts:kinds,
    product_candidate_count:products.size,category_candidate_count:categories.size,
    product_candidates:[...products].map(([asin,url])=>({
      asin,url,used_verified:false,
      listing_link_label:contexts.get(asin)?.label || null,
      same_line_used_keyword:Boolean(contexts.get(asin)?.used),
      same_line_currency_marker:Boolean(contexts.get(asin)?.currency),
      context_is_diagnostic_only:true
    })),
    product_links_with_used_keyword:[...products.keys()].filter(k=>contexts.get(k)?.used).length,
    product_links_with_currency_marker:[...products.keys()].filter(k=>contexts.get(k)?.currency).length,
    product_links_with_both_signals:[...products.keys()].filter(k=>contexts.get(k)?.used&&contexts.get(k)?.currency).length,
    category_candidates:[...categories],verified_used_offers:0,public_posting_enabled:false};
}
