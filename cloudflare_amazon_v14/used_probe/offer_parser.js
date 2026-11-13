/** Conservative Amazon Egypt offer-price parsing. No proof of checkout or stock. */

function normalizeArabicDigits(input) {
  return String(input ?? '').replace(/[٠-٩۰-۹]/g, ch => {
    const c = ch.charCodeAt(0);
    return String(c >= 0x6f0 ? c - 0x6f0 : c - 0x660);
  }).replace(/\u066c/g, ',').replace(/\u066b/g, '.');
}

export function parseEgyptianMoney(input) {
  const text = normalizeArabicDigits(input).replace(/\s+/g, ' ');
  const tokens = [...text.matchAll(/(?:\bEGP(?=\s*[\d])|ج\.?\s?م\.?|جنيه(?:اً|ا)?|ج\.م\.)\s*([\d,.]+)|([\d,.]+)\s*(?:\bEGP\b|ج\.?\s?م\.?|جنيه(?:اً|ا)?|ج\.م\.)/gi)];
  const values = [];
  for (const m of tokens) {
    let str = m[1] || m[2];
    // 2,950.00 and 2.950,00 are both handled; do not interpret ambiguous numbers as prices.
    if (str.includes(',') && str.includes('.')) {
      if (str.lastIndexOf('.') > str.lastIndexOf(',')) str = str.replace(/,/g, '');
      else str = str.replace(/\./g, '').replace(',', '.');
    } else if (str.includes(',')) {
      const chunks = str.split(',');
      if (chunks.length > 2 || chunks[chunks.length - 1].length === 3) str = str.replace(/,/g, '');
      else str = str.replace(',', '.');
    } else if (str.includes('.')) {
      const chunks = str.split('.');
      if (chunks.length > 2 || chunks[chunks.length - 1].length === 3) str = str.replace(/\./g, '');
    }
    const value = Number(str);
    if (Number.isFinite(value) && value > 0 && value < 1000000) values.push(Math.round(value * 100) / 100);
  }
  return [...new Set(values)];
}

export function classifyUsedCondition(text) {
  const s = normalizeArabicDigits(text).toLowerCase();
  if (!/(?:\bused\b|مستعمل|مستخدمة|مستعملة)/i.test(s)) return null;
  if (/(?:like\s+new|كالجديد|مثل الجديد|شبه جديد)/i.test(s)) return 'USED_LIKE_NEW';
  if (/(?:very\s+good|جيدة جدا|جيد جدا|جيدة جدًا|جيد جدًا)/i.test(s)) return 'USED_VERY_GOOD';
  if (/(?:acceptable|مقبولة|مقبول)/i.test(s)) return 'USED_ACCEPTABLE';
  if (/(?:\bgood\b|جيدة|جيد)/i.test(s)) return 'USED_GOOD';
  return 'USED_UNSPECIFIED';
}

/**
 * Each item must be ONE seller offer card; no cross-card combination of condition
 * and price, and no interpreting generic "new & used" navigation as proof.
 * Multi-price cards remain candidates without numeric price.
 */
export function extractUsedOffers(cards, sourceUrl) {
  const matches = [];
  for (const card of cards) {
    const text = String(card.text || '').replace(/\s+/g, ' ').trim();
    if (!text) continue;
    const condition = classifyUsedCondition(text);
    if (!condition || /(?:new\s*[&+]\s*used|الجديد\s*والمستعمل)/i.test(text.slice(0, 120))) continue;
    const prices = parseEgyptianMoney(text);
    matches.push({
      condition,
      price: prices.length === 1 ? prices[0] : null,
      price_candidates: prices.length <= 5 ? prices : prices.slice(0, 5),
      status: prices.length === 1 ? 'USED_PRICE_CANDIDATE' : 'PRICE_AMBIGUOUS',
      source: sourceUrl,
      evidence: text.slice(0, 240),
      verified_checkout: false,
    });
  }
  return matches;
}
