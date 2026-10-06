const STOP = new Set([
  'the','and','with','for','from','new','original','official','edition','version',
  'black','white','blue','red','green','silver','gold','gray','grey','pink',
  'لون','مع','من','في','على','الى','إلى','اصلي','أصلي','جديد','نسخة','اصدار','إصدار',
]);

const BRANDS = new Set([
  'samsung','apple','xiaomi','redmi','poco','oppo','realme','honor','huawei','nokia','motorola',
  'lenovo','dell','hp','asus','acer','msi','sony','lg','tcl','hisense','philips','anker','jbl',
  'bosch','beko','fresh','tornado','sharp','toshiba','midea','ariston','braun','tefal',
  'سامسونج','ابل','آبل','شاومي','ريدمي','بوكو','اوبو','أوبو','ريلمي','هونر','هواوي',
]);

const MODEL_RE = /\b(?:[A-Z]{1,6}[- ]?\d{2,7}[A-Z0-9-]*|\d{2,4}[A-Z]{1,4})\b/gi;
const CAPACITY_RE = /\b(\d+(?:\.\d+)?)\s*(TB|GB|MB|تيرا|جيجا)\b/gi;
const SIZE_RE = /\b(\d+(?:\.\d+)?)\s*(?:inch|inches|in|بوصة|")\b/gi;
const RAM_RE = /\b(?:ram\s*)?(\d+)\s*(?:gb|جيجا)\s*(?:ram|رام)\b|\b(\d+)\s*(?:gb|جيجا)\s*ram\b/gi;
const PACK_RE = /\b(?:pack of|set of|عدد|عبوة)\s*(\d+)\b/gi;

export interface ProductSignature {
  brand: string;
  models: Set<string>;
  capacities_gb: Set<number>;
  sizes_in: Set<number>;
  ram_gb: Set<number>;
  pack_counts: Set<number>;
  tokens: Set<string>;
}

function norm(text: string): string {
  return String(text || '').normalize('NFKC').toLowerCase().replace(/×/g, 'x').replace(/[^\p{L}\p{N}_.+-]+/gu, ' ').replace(/\s+/g, ' ').trim();
}

export function signature(title: string): ProductSignature {
  const raw = String(title || '');
  const n = norm(raw);
  const words = n.split(' ').filter(w => w.length >= 2 && !STOP.has(w) && !/^\d+$/.test(w));
  const brand = words.find(w => BRANDS.has(w)) || '';
  const models = new Set<string>();
  for (const match of raw.matchAll(MODEL_RE)) {
    const model = String(match[0] || '').toUpperCase().replace(/[\s-]+/g, '');
    if (!model) continue;
    if (/^\d+(?:GB|TB|MB)$/i.test(model)) continue;
    if (/^\d+(?:GB|جيجا)?RAM$/i.test(model)) continue;
    models.add(model);
  }
  const capacities = new Set<number>();
  for (const m of raw.matchAll(CAPACITY_RE)) {
    let v = Number(m[1]); const unit = String(m[2] || '').toLowerCase();
    if (unit === 'tb' || unit === 'تيرا') v *= 1024;
    else if (unit === 'mb') v /= 1024;
    v = Math.round(v); if (v >= 1 && v <= 32768) capacities.add(v);
  }
  const sizes = new Set<number>();
  for (const m of raw.matchAll(SIZE_RE)) { const v = Math.round(Number(m[1]) * 10) / 10; if (v >= 1 && v <= 150) sizes.add(v); }
  const ram = new Set<number>();
  for (const m of raw.matchAll(RAM_RE)) { const v = Number(m[1] || m[2] || 0); if (v >= 1 && v <= 256) ram.add(v); }
  const packs = new Set<number>();
  for (const m of raw.matchAll(PACK_RE)) { const v = Number(m[1] || 0); if (v >= 2 && v <= 100) packs.add(v); }
  return { brand, models, capacities_gb: capacities, sizes_in: sizes, ram_gb: ram, pack_counts: packs, tokens: new Set(words) };
}

function intersects<T>(a: Set<T>, b: Set<T>): boolean { for (const x of a) if (b.has(x)) return true; return false; }

export function compatibility(a: ProductSignature, b: ProductSignature): [boolean, string[]] {
  const reasons: string[] = [];
  if (a.brand && b.brand && a.brand !== b.brand) return [false, ['brand_mismatch']];
  if (a.models.size && b.models.size && !intersects(a.models, b.models)) return [false, ['model_mismatch']];
  if (a.capacities_gb.size && b.capacities_gb.size && !intersects(a.capacities_gb, b.capacities_gb)) return [false, ['capacity_mismatch']];
  if (a.ram_gb.size && b.ram_gb.size && !intersects(a.ram_gb, b.ram_gb)) return [false, ['ram_mismatch']];
  if (a.sizes_in.size && b.sizes_in.size) {
    let min = Infinity; for (const x of a.sizes_in) for (const y of b.sizes_in) min = Math.min(min, Math.abs(x-y));
    if (min > 0.6) return [false, ['size_mismatch']];
  }
  if (a.pack_counts.size && b.pack_counts.size && !intersects(a.pack_counts, b.pack_counts)) return [false, ['pack_mismatch']];
  if (a.models.size && b.models.size && intersects(a.models,b.models)) reasons.push('model_match');
  if (a.capacities_gb.size && b.capacities_gb.size && intersects(a.capacities_gb,b.capacities_gb)) reasons.push('capacity_match');
  return [true, reasons];
}

export function titleSimilarity(aText: string, bText: string): number {
  const a = signature(aText), b = signature(bText);
  const [ok, evidence] = compatibility(a,b); if (!ok) return 0;
  const ta = a.tokens, tb = b.tokens; if (!ta.size || !tb.size) return 0;
  let inter = 0; for (const t of ta) if (tb.has(t)) inter++;
  const union = new Set([...ta, ...tb]).size;
  let score = inter / Math.max(1, union);
  if (evidence.includes('model_match')) score += 0.22;
  if (evidence.includes('capacity_match')) score += 0.08;
  if (a.brand && b.brand && a.brand === b.brand) score += 0.05;
  return Math.max(0, Math.min(1, score));
}
