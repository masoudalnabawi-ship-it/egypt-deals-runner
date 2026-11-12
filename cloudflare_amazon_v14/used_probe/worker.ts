interface Env {
  BROWSER: any;
  PROBE_KEY: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    
    if (!env.PROBE_KEY ||
        request.headers.get("Authorization") !==
        `Bearer ${env.PROBE_KEY}`) {
      return new Response("Unauthorized", {status: 401});
    }
    const input = new URL(request.url);
    const asin = (input.searchParams.get("asin") || "B0DYGHH7CY").toUpperCase();

    if (!/^[A-Z0-9]{10}$/.test(asin)) {
      return Response.json({ error: "INVALID_ASIN" }, { status: 400 });
    }

    const url = `https://www.amazon.eg/dp/${asin}`;

    const selectors = [
      "#productTitle",
      "#corePrice_feature_div .a-price .a-offscreen",
      "#newBuyBoxPrice",
      "#usedBuyBox",
      "#usedBuyBoxPrice",
      "#aod-offer",
      "#olp_feature_div",
      "#buybox-see-all-buying-choices",
      "#availability",
      "form[action*='validateCaptcha']",
      "#captchacharacters"
    ];

    try {
      const response: Response = await env.BROWSER.quickAction(
        "scrape",
        {
          url,
          elements: selectors.map(selector => ({ selector })),
          gotoOptions: {
            waitUntil: "domcontentloaded",
            timeout: 20000
          },
          waitForTimeout: 800
        }
      );

      if (!response.ok) {
        return Response.json({
          asin,
          status: "BROWSER_ERROR",
          http: response.status
        });
      }

      const data: any = await response.json();
      const rows = (data.result || []).map((group: any) => ({
        selector: group.selector,
        matches: (group.results || []).length,
        samples: (group.results || []).slice(0, 3).map(
          (item: any) => String(item.text || "").trim().slice(0, 350)
        )
      }));

      const captcha = rows.some(
        (r: any) =>
          r.selector.toLowerCase().includes("captcha") &&
          r.matches > 0
      );

      return Response.json({
        asin,
        url,
        status: captcha ? "BLOCKED_CAPTCHA" : "INSPECTED_UNVERIFIED",
        browser_ms: Number(response.headers.get("X-Browser-Ms-Used") || 0),
        elements: rows.filter((r: any) => r.matches > 0),
        verified: false
      });
    } catch (error) {
      return Response.json({
        asin,
        status: "ERROR",
        message: String(error).slice(0, 200),
        verified: false
      });
    }
  }
} satisfies ExportedHandler<Env>;
