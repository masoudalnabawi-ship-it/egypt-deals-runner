export interface WatchProductLink {
  store: "amazon" | "noon";
  externalId: string;
  url: string;
}

export function parseWatchLink(input: string): WatchProductLink {
  let url: URL;

  try {
    url = new URL(input.trim());
  } catch {
    throw new Error("invalid_product_url");
  }

  if (url.protocol !== "https:") {
    throw new Error("https_required");
  }

  const host = url.hostname.toLowerCase();

  if (host === "amazon.eg" || host === "www.amazon.eg") {
    const match = url.pathname.match(
      /\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:\/|$)/i
    );

    if (!match) throw new Error("amazon_asin_missing");

    const asin = match[1].toUpperCase();

    return {
      store: "amazon",
      externalId: asin,
      url: `https://www.amazon.eg/dp/${asin}`
    };
  }

  if (host === "noon.com" || host === "www.noon.com") {
    const match = url.pathname.match(
      /^\/egypt-(?:en|ar)\/.*\/([A-Z0-9]{8,20})\/p\/?$/i
    );

    if (!match) throw new Error("noon_product_sku_missing");

    const sku = match[1].toUpperCase();

    return {
      store: "noon",
      externalId: sku,
      url: `https://www.noon.com${url.pathname}`
    };
  }

  throw new Error("unsupported_store");
}

export async function resolveWatchLink(input: string): Promise<WatchProductLink> {
  const raw = new URL(input.trim());

  if (
    raw.protocol !== "https:" ||
    raw.hostname.toLowerCase() !== "amzn.eu"
  ) {
    return parseWatchLink(input);
  }

  if (!/^\/d\/[A-Za-z0-9]+\/?$/.test(raw.pathname)) {
    throw new Error("invalid_amazon_short_link");
  }

  const response = await fetch(raw.toString(), {
    method: "GET",
    redirect: "manual",
    signal: AbortSignal.timeout(12000)
  });

  try {
    if (![301, 302, 303, 307, 308].includes(response.status)) {
      throw new Error("short_link_redirect_missing");
    }

    const location = response.headers.get("location");
    if (!location) throw new Error("short_link_location_missing");

    return parseWatchLink(new URL(location, raw).toString());
  } finally {
    await response.body?.cancel();
  }
}
