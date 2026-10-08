import type { DealCandidate, Store } from "./types";

export const nowTs = (): number => Math.floor(Date.now() / 1000);

export function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

export function round2(n: number): number {
  return Math.round((n + Number.EPSILON) * 100) / 100;
}

export function cleanText(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

export function htmlEscape(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

export function decodeEntities(value: string): string {
  return value
    .replace(/&nbsp;|&#160;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">");
}

export function stripTags(value: string): string {
  return cleanText(decodeEntities(String(value || "").replace(/<[^>]+>/g, " ")));
}

export function parseNumber(value: unknown): number {
  if (value == null || typeof value === "boolean") return 0;
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  if (Array.isArray(value)) {
    for (const item of value) {
      const n = parseNumber(item);
      if (n > 0) return n;
    }
    return 0;
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const keys = [
      "amount", "price", "final_price", "finalPrice", "sale_price", "salePrice",
      "lowPrice", "formatted_value", "formattedValue", "display_value", "displayValue",
      "value", "min", "max",
    ];
    for (const key of keys) {
      if (!(key in obj)) continue;
      const n = parseNumber(obj[key]);
      if (n > 0) return n;
    }
    return 0;
  }
  const normalized = String(value)
    .replace(/[٠-٩]/g, d => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)))
    .replace(/٫/g, ".")
    .replace(/٬/g, ",")
    .replace(/,/g, "");
  const m = normalized.match(/(\d+(?:\.\d+)?)/);
  if (!m) return 0;
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : 0;
}

export function canonicalUrl(url: string): string {
  try {
    const u = new URL(String(url || "").trim());
    u.hash = "";
    u.search = "";
    u.hostname = u.hostname.toLowerCase();
    u.pathname = u.pathname.replace(/\/$/, "");
    return u.toString().replace(/\/$/, "");
  } catch {
    return String(url || "").trim();
  }
}

export function normalizeExternalId(store: Store, externalId: string, url = ""): string {
  const value = cleanText(externalId).toUpperCase();
  if (value) return value;
  if (store === "amazon") {
    const m = url.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[/?]|$)/i);
    if (m) return m[1].toUpperCase();
  }
  if (store === "noon") {
    const m = url.match(/\/([A-Z0-9]{8,24})\/p\/?(?:\?|$)/i);
    if (m) return m[1].toUpperCase();
  }
  return "";
}

export function normalizeCandidate(input: DealCandidate): DealCandidate {
  const current = Number(input.current_price || 0);
  const oldRaw = input.old_price == null ? null : Number(input.old_price);
  const old = oldRaw && oldRaw > current ? oldRaw : null;
  return {
    ...input,
    store: String(input.store).toLowerCase().trim() as Store,
    external_id: normalizeExternalId(input.store, input.external_id || "", input.url || ""),
    title: cleanText(input.title),
    url: String(input.url || "").trim(),
    image_url: String(input.image_url || "").trim(),
    category: cleanText(input.category || "unknown") || "unknown",
    source: cleanText(input.source || ""),
    current_price: Number.isFinite(current) ? current : 0,
    old_price: old,
    discovered_at: input.discovered_at || nowTs(),
    metadata: input.metadata || {},
  };
}

export function discountPercent(deal: DealCandidate): number {
  const old = Number(deal.old_price || 0);
  const cur = Number(deal.current_price || 0);
  if (!(old > cur && cur > 0)) return 0;
  return round2(((old - cur) / old) * 100);
}

export async function sha256Hex(text: string): Promise<string> {
  const data = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, "0")).join("");
}

export async function dealKey(deal: DealCandidate): Promise<string> {
  const identity = deal.external_id || canonicalUrl(deal.url) || deal.title.toLowerCase();
  return sha256Hex(`${deal.store}|${identity}`);
}

export function safeJsonParse<T = Record<string, unknown>>(raw: unknown, fallback: T): T {
  try {
    const value = JSON.parse(String(raw ?? ""));
    return value as T;
  } catch {
    return fallback;
  }
}

export function isProtectedPage(text: string): boolean {
  const low = String(text || "").toLowerCase();
  return [
    "robot check",
    "enter the characters you see below",
    "captcha",
    "sorry, we just need to make sure",
    "access denied",
    "unusual traffic",
  ].some(x => low.includes(x));
}

export function extractBalancedObject(text: string, start: number): string | null {
  if (text[start] !== "{") return null;
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') { inString = true; continue; }
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  return null;
}

export function pickAttr(attrs: Array<{name?: string; value?: string}> | undefined, name: string): string {
  const item = (attrs || []).find(a => String(a.name || "").toLowerCase() === name.toLowerCase());
  return String(item?.value || "");
}
