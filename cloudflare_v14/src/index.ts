import type { DealCandidate, JobMessage, V14Env } from './types';
import { getSettings } from './config';
import { D1Repository } from './db';
import { handleTelegramUpdate, runCycle } from './engine';
import { setWebhook } from './telegram';
import { acceptable, buildPriceProfile, evaluateDeal, preliminaryDecision } from './intelligence';
import { inspectDeal } from './shield';


function json(data: unknown, status = 200): Response {
  return Response.json(data, { status, headers: { 'cache-control': 'no-store' } });
}

function bearer(request: Request): string {
  const h = request.headers.get('authorization') || '';
  return h.toLowerCase().startsWith('bearer ') ? h.slice(7).trim() : '';
}

function adminAllowed(request: Request, env: V14Env): boolean {
  const expected = String(env.V14_ADMIN_KEY || '').trim();
  if (!expected) return false;
  const url = new URL(request.url);
  return bearer(request) === expected || url.searchParams.get('key') === expected;
}

async function hmacHex(
  secret: string,
  message: string
): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    {
      name: "HMAC",
      hash: "SHA-256",
    },
    false,
    ["sign"],
  );

  const signature =
    await crypto.subtle.sign(
      "HMAC",
      key,
      new TextEncoder().encode(message),
    );

  return [...new Uint8Array(signature)]
    .map(x => x.toString(16).padStart(2, "0"))
    .join("");
}

function secureEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;

  let diff = 0;

  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }

  return diff === 0;
}

async function importNoonRoute(
  request: Request,
  env: V14Env
): Promise<Response> {
  const token =
    String(env.TELEGRAM_BOT_TOKEN || "").trim();

  if (!token) {
    return json(
      {ok:false,error:"main_bot_missing"},
      500,
    );
  }

  let body: any = {};

  try {
    body = await request.json();
  } catch {
    return json(
      {ok:false,error:"invalid_json"},
      400,
    );
  }

  const chatId =
    String(body?.chat_id || "").trim();

  const ts =
    Math.floor(Number(body?.ts || 0));

  const signature =
    String(body?.signature || "")
      .trim()
      .toLowerCase();

  const numericChat =
    Number(chatId);

  if (
    !/^-?\d{6,20}$/.test(chatId) ||
    !Number.isSafeInteger(numericChat)
  ) {
    return json(
      {ok:false,error:"invalid_chat"},
      400,
    );
  }

  const now =
    Math.floor(Date.now() / 1000);

  if (
    !ts ||
    Math.abs(now - ts) > 300
  ) {
    return json(
      {ok:false,error:"expired_request"},
      401,
    );
  }

  const expected =
    await hmacHex(
      token,
      `${chatId}|${ts}`,
    );

  if (!secureEqual(signature, expected)) {
    return json(
      {ok:false,error:"bad_signature"},
      401,
    );
  }

  // Verify the CURRENT V14 bot can actually access
  // the old Noon review group before saving it.
  const probe = await fetch(
    `https://api.telegram.org/bot${token}/getChat`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify({
        chat_id: chatId,
      }),
    },
  );

  let telegram: any = {};

  try {
    telegram = await probe.json();
  } catch {}

  if (!probe.ok || !telegram?.ok) {
    return json(
      {
        ok:false,
        error:"main_bot_cannot_access_noon_chat",
      },
      409,
    );
  }

  const repo =
    new D1Repository(env.egypt_deals_v14_db);

  await repo.counterSet(
    "noon_review_chat_id",
    numericChat,
  );

  return json({
    ok:true,
    route:"noon_normal_only",
    main_bot_access:true,
  });
}



async function claimPlaywrightVerification(
  request: Request,
  env: V14Env,
): Promise<Response> {
  let body: any = {};

  try {
    body = await request.json();
  } catch {}

  const workerId =
    String(
      body?.worker_id ||
      `gha-verify-${crypto.randomUUID().slice(0,8)}`
    ).slice(0,80);

  const repo =
    new D1Repository(
      env.egypt_deals_v14_db
    );

  /*
   * GitHub Playwright now acts as the expensive
   * rendered verifier for strong Amazon Ultra leads.
   */
  const row =
    await repo.claimForVerification(
      "amazon",
      "ultra",
      workerId,
      300,
    );

  if (!row) {
    return json({
      ok:true,
      job:null,
    });
  }

  return json({
    ok:true,
    job:{
      deal_key:row.deal_key,
      external_id:row.external_id,
      title:row.title,
      url:row.url,
      current_price:row.current_price,
      old_price:row.old_price,
      visible_discount:row.visible_discount,
      category:row.category,
      source:row.source,
    },
  });
}


async function completePlaywrightVerification(
  request: Request,
  env: V14Env,
): Promise<Response> {
  let body: any = {};

  try {
    body = await request.json();
  } catch {
    return json(
      {ok:false,error:"invalid_json"},
      400,
    );
  }

  const dealKey =
    String(body?.deal_key || "").trim();

  const status =
    String(body?.status || "").trim();

  const repo =
    new D1Repository(
      env.egypt_deals_v14_db
    );

  const row =
    await repo.findByKey(dealKey);

  if (
    !row ||
    row.store !== "amazon"
  ) {
    return json(
      {ok:false,error:"deal_not_found"},
      404,
    );
  }

  if (status !== "verified") {
    const reason =
      String(
        body?.reason ||
        "playwright_verification_failed"
      ).slice(0,350);

    await repo.markStrongRetry(
      row.deal_key,
      `playwright_verify:${reason}`,
      900,
      8,
    );

    return json({
      ok:true,
      state:"retry",
    });
  }

  const current =
    Number(body?.current_price || 0);

  let old =
    Number(body?.old_price || 0);

  const savings =
    Math.max(
      0,
      Math.min(
        99,
        Number(body?.savings_percent || 0)
      )
    );

  const coupon =
    Math.max(
      0,
      Math.min(
        99,
        Number(body?.coupon_percent || 0)
      )
    );

  /*
   * ULTRA_ASIN_VARIANT_LOCK_V2
   *
   * Amazon may redirect or switch a selected variant.
   * Ultra evidence must belong to the exact ASIN that
   * discovery requested.
   */
  const pageAsin =
    String(
      body?.page_asin || ""
    )
      .trim()
      .toUpperCase();

  const expectedAsin =
    String(
      row.external_id || ""
    )
      .trim()
      .toUpperCase();

  const canonicalUrl =
    String(
      body?.canonical_url || ""
    ).slice(0,1000);

  const discoveredPrice =
    Number(row.current_price || 0);

  /*
   * Permanent audit trail for every rendered Amazon
   * Ultra observation. This lets us distinguish a
   * genuinely expired deal from a selector/parser issue
   * without weakening any safety gate.
   */
  await repo.event(
    "github_playwright_observation",
    "amazon",
    row.deal_key,
    {
      external_id: row.external_id,
      page_asin:pageAsin,
      canonical_url:canonicalUrl,
      discovery_current: discoveredPrice,
      discovery_old: Number(row.old_price || 0),
      discovery_discount: Number(row.visible_discount || 0),
      live_current: current,
      live_old: old,
      discovery_current_match:
        discoveredPrice > 0 &&
        Math.abs(current - discoveredPrice)
          / discoveredPrice <= 0.015,
      live_savings_percent: savings,
      live_coupon_percent: coupon,
    },
  );

  /*
   * Exact product/variant identity gate.
   *
   * If Amazon says the rendered page belongs to another
   * ASIN, no price from that page may qualify this lead.
   */
  if (
    pageAsin &&
    expectedAsin &&
    pageAsin !== expectedAsin
  ) {
    const reason =
      `amazon_variant_asin_mismatch:${expectedAsin}:${pageAsin}`;

    await repo.markRejected(
      row.deal_key,
      reason,
    );

    await repo.event(
      "ultra_variant_mismatch",
      "amazon",
      row.deal_key,
      {
        expected_asin:expectedAsin,
        page_asin:pageAsin,
        canonical_url:canonicalUrl,
      },
    );

    return json({
      ok:true,
      state:"rejected",
      reason,
    });
  }

  if (!(current > 0)) {
    await repo.markStrongRetry(
      row.deal_key,
      "playwright_verify:no_live_current_price",
      900,
      8,
    );

    return json({
      ok:true,
      state:"retry",
    });
  }

  /*
   * Price may improve, but a material increase means
   * the old discovery snapshot is stale.
   */
  if (
    discoveredPrice > 0 &&
    current > discoveredPrice * 1.03
  ) {
    await repo.markStrongRetry(
      row.deal_key,
      "playwright_verify:live_price_increased",
      900,
      8,
    );

    return json({
      ok:true,
      state:"retry",
    });
  }

  /*
   * AMAZON CROSS-PAGE CORROBORATION
   *
   * Amazon search/deals already supplied old+current.
   * If the rendered product page independently confirms
   * that exact current price within 1.5%, we may preserve
   * Amazon's discovery old price even when the product DOM
   * dynamically hides the struck-through price.
   */
  const discoveryOld =
    Number(row.old_price || 0);

  const liveCurrentMatchesDiscovery =
    discoveredPrice > 0 &&
    Math.abs(current - discoveredPrice)
      / discoveredPrice <= 0.015;

  /*
   * IMPORTANT ULTRA SAFETY RULE
   *
   * A matching current price on Amazon is useful
   * corroboration, but it is NOT proof that the
   * discovery old price belongs to the currently
   * selected offer/variant.
   *
   * Therefore discoveryOld is audit-only here.
   * It must never become the verified old_price.
   *
   * Ultra must be proven by the rendered product page:
   * - live struck/list price, or
   * - live Amazon savings percentage, or
   * - explicit product coupon.
   */
  const crossPageProof =
    Boolean(
      !(old > current) &&
      liveCurrentMatchesDiscovery &&
      discoveryOld > current
    );

  /*
   * Amazon sometimes exposes savings % but hides the
   * struck-through price. Derive the old price only
   * from Amazon's LIVE rendered savings evidence.
   */
  if (
    !(old > current) &&
    savings >= 5 &&
    savings <= 99
  ) {
    const derived =
      current /
      (1 - savings / 100);

    if (
      derived >= current * 1.05 &&
      derived <= current * 105
    ) {
      old =
        Math.round(
          derived * 100
        ) / 100;
    }
  }

  if (
    old > 0 &&
    (
      old <= current ||
      old > current * 105
    )
  ) {
    old = 0;
  }

  /*
   * Independent LIVE discount calculation.
   *
   * History, discovery old price and cross-store data are
   * intentionally absent from this calculation.
   */
  const liveOldDiscount =
    old > current && current > 0
      ? (
          (old - current)
          / old
        ) * 100
      : 0;

  const liveBaseDiscount =
    Math.max(
      liveOldDiscount,
      savings,
    );

  const liveEffectiveDiscount =
    Math.max(
      0,
      Math.min(
        99,
        coupon > 0
          ? (
              100 *
              (
                1
                -
                (1 - liveBaseDiscount / 100)
                *
                (1 - coupon / 100)
              )
            )
          : liveBaseDiscount
      )
    );

  const incoming =
    repo.rowToCandidate(row);

  const verified: DealCandidate = {
    ...incoming,
    title:
      String(body?.title || "").trim()
      || incoming.title,
    current_price:current,
    old_price:
      old > current
        ? old
        : null,
    image_url:
      String(body?.image_url || "").trim()
      || incoming.image_url,
  };

  const history =
    await repo.recentPrices(
      row.deal_key
    );

  const profile =
    buildPriceProfile(
      history,
      current
    );

  /*
   * Three independent live signals:
   * rendered product page + live price + live
   * old/savings structure.
   */
  const signals =
    old > current || savings >= 5
      ? 3
      : 2;

  const meta: Record<string,unknown> = {
    http_via:"github_playwright",
    rendered_dom:true,
    github_playwright_verified:true,
    amazon_cross_page_proof:
      crossPageProof,
    amazon_live_current_match:
      liveCurrentMatchesDiscovery,
    amazon_page_asin:pageAsin,
    amazon_canonical_url:canonicalUrl,
    amazon_live_effective_discount:
      Math.round(
        liveEffectiveDiscount * 100
      ) / 100,
    verification_signals:signals,
    amazon_savings_percent:savings,
    coupon_percent:coupon,
    coupon_source:
      coupon > 0
        ? "explicit_product_coupon"
        : "",
  };

  const shield =
    inspectDeal(
      incoming,
      verified,
      meta,
      profile,
    );

  if (shield.hard_block) {
    const reason =
      `anti_fake:${shield.reasons.join(",")}`;

    await repo.markRejected(
      row.deal_key,
      reason,
    );

    return json({
      ok:true,
      state:"rejected",
      reason,
    });
  }

  const settings =
    getSettings(env);

  const decision =
    evaluateDeal(
      settings,
      verified,
      {
        verified:true,
        coupon_percent:coupon,
        history,
        verification_signals:signals,
        price_profile:profile,
      },
    );

  const [ok, reason] =
    acceptable(
      settings,
      decision,
    );

  if (!ok) {
    /*
     * A search result may advertise a huge crossed price
     * that does not belong to the currently selected
     * Amazon offer/variant.
     *
     * Record that semantic failure separately so the
     * queue can LEARN which discovery sources repeatedly
     * waste Ultra verification time.
     */
    const noLiveUltraEvidence =
      row.lane === "ultra" &&
      current > 0 &&
      !(old > current) &&
      savings < 5 &&
      coupon <= 0;

    const rejectReason =
      noLiveUltraEvidence
        ? "ultra_no_live_discount_evidence"
        : reason;

    if (noLiveUltraEvidence) {
      await repo.event(
        "ultra_false_discovery",
        "amazon",
        row.deal_key,
        {
          external_id:row.external_id,
          source:row.source,
          discovery_discount:
            Number(row.visible_discount || 0),
          discovery_current:
            Number(row.current_price || 0),
          discovery_old:
            Number(row.old_price || 0),
          live_current:current,
          live_old:old,
          live_savings_percent:savings,
          live_coupon_percent:coupon,
        },
      );
    }

    await repo.markRejected(
      row.deal_key,
      rejectReason,
    );

    return json({
      ok:true,
      state:"rejected",
      reason:rejectReason,
      discount:decision.real_discount,
    });
  }

  /*
   * AMAZON_HUNTER_V3_LIVE_ULTRA_ROUTE
   *
   * Ultra routing is decided ONLY from the rendered,
   * live Amazon page evidence calculated above.
   *
   * Price history may improve intelligence/score,
   * but can never promote a product into Ultra.
   */
  const verifiedLiveDiscount =
    Math.round(
      liveEffectiveDiscount * 100
    ) / 100;

  decision.real_discount =
    verifiedLiveDiscount;

  if (
    verifiedLiveDiscount >=
      settings.ultra_hot_discount
    &&
    decision.confidence >=
      settings.min_confidence_ultra
  ) {
    decision.lane = "ultra";
    decision.score = 100;

  } else if (
    verifiedLiveDiscount >=
      settings.ultra_min_discount
    &&
    decision.confidence >=
      settings.min_confidence_ultra
  ) {
    decision.lane = "ultra";
    decision.score =
      Math.max(
        decision.score,
        94,
      );

  } else {

    /*
     * A discovery Ultra that is still a genuine
     * >=normal deal is downgraded safely.
     *
     * If the rendered discount is below even the
     * normal threshold, do not waste the review queue.
     */
    if (
      verifiedLiveDiscount <
      settings.normal_min_discount
    ) {
      const rejectReason =
        "playwright_live_discount_below_normal";

      await repo.markRejected(
        row.deal_key,
        rejectReason,
      );

      return json({
        ok:true,
        state:"rejected",
        reason:rejectReason,
        discount:
          verifiedLiveDiscount,
      });
    }

    decision.lane = "normal";
  }

  const outMeta = {
    ...(verified.metadata || {}),
    ...meta,
    decision_reasons:
      decision.reasons,
    verified_route:
      decision.lane,
    price_intelligence:
      profile,
    anti_fake_shield:{
      risk_score:
        shield.risk_score,
      required_signals:
        shield.required_signals,
      reasons:
        shield.reasons,
    },
  };

  await repo.markVerified(
    row.deal_key,
    verified,
    decision,
    outMeta,
  );

  await repo.event(
    "github_playwright_verified",
    "amazon",
    row.deal_key,
    {
      lane:decision.lane,
      discount:
        decision.real_discount,
    },
  );

  return json({
    ok:true,
    state:"verified",
    lane:decision.lane,
    discount:
      decision.real_discount,
    confidence:
      decision.confidence,
  });
}


async function claimScreenshotJob(
  request: Request,
  env: V14Env,
): Promise<Response> {
  let body: any = {};

  try {
    body = await request.json();
  } catch {}

  const lane =
    body?.lane === "normal"
      ? "normal"
      : "ultra";

  const workerId =
    String(
      body?.worker_id ||
      `gha-${crypto.randomUUID().slice(0, 8)}`
    ).slice(0, 80);

  const repo =
    new D1Repository(
      env.egypt_deals_v14_db
    );

  /*
   * Give Playwright enough time to open Amazon,
   * capture, upload to Telegram, then acknowledge.
   */
  const row =
    await repo.claimAmazonForScreenshot(
      lane,
      workerId,
      300,
    );

  if (!row) {
    return json({
      ok: true,
      job: null,
    });
  }

  /*
   * Final Ultra safety gate BEFORE the external
   * screenshot worker sees the job.
   */
  if (
    row.lane === "ultra" &&
    (
      Number(row.real_discount || 0) < 65 ||
      Number(row.confidence || 0) < 0.76
    )
  ) {
    await repo.markRejected(
      row.deal_key,
      "screenshot_gate_invalid_ultra",
    );

    return json({
      ok: true,
      job: null,
    });
  }

  return json({
    ok: true,
    job: {
      deal_key: row.deal_key,
      store: row.store,
      lane: row.lane,
      external_id: row.external_id,
      title: row.title,
      url: row.url,
      current_price: row.current_price,
      old_price: row.old_price,
      effective_price: row.effective_price,
      real_discount: row.real_discount,
      score: row.score,
      confidence: row.confidence,
      category: row.category,
    },
  });
}


async function completeScreenshotJob(
  request: Request,
  env: V14Env,
): Promise<Response> {
  let body: any = {};

  try {
    body = await request.json();
  } catch {
    return json(
      {ok:false,error:"invalid_json"},
      400,
    );
  }

  const dealKey =
    String(body?.deal_key || "").trim();

  const status =
    String(body?.status || "").trim();

  const reason =
    String(
      body?.reason ||
      "playwright_delivery_failed"
    ).slice(0, 400);

  if (
    !dealKey ||
    dealKey.length > 128
  ) {
    return json(
      {ok:false,error:"invalid_deal_key"},
      400,
    );
  }

  const repo =
    new D1Repository(
      env.egypt_deals_v14_db
    );

  const row =
    await repo.findByKey(dealKey);

  if (!row) {
    return json(
      {ok:false,error:"deal_not_found"},
      404,
    );
  }

  const proof =
    body?.proof &&
    typeof body.proof === "object"
      ? body.proof
      : {};

  const liveDiscount =
    Number(body?.live_discount || 0);

  /*
   * Final safety gate at the exact delivery moment.
   *
   * Even a previously verified Ultra is rejected if
   * Amazon no longer visibly proves >=65% immediately
   * before Telegram delivery.
   */
  if (
    status === "invalid_ultra" ||
    (
      status === "sent" &&
      row.lane === "ultra" &&
      !(liveDiscount >= 65)
    )
  ) {
    const blockReason =
      status === "invalid_ultra"
        ? reason
        : "missing_or_below_65_live_delivery_proof";

    await repo.markRejected(
      dealKey,
      `delivery_live_gate:${blockReason}`,
    );

    await repo.event(
      "playwright_ultra_blocked_live",
      "amazon",
      dealKey,
      {
        reason:blockReason,
        live_discount:liveDiscount,
        proof,
      },
    );

    return json({
      ok:true,
      state:"rejected",
      reason:blockReason,
    });
  }

  if (status === "sent") {
    await repo.markSent(dealKey);

    await repo.event(
      "playwright_screenshot_sent",
      "amazon",
      dealKey,
      {
        live_discount:liveDiscount,
        proof,
      },
    );

    return json({
      ok:true,
      state:"sent",
    });
  }

  await repo.deliveryRetry(
    dealKey,
    `playwright:${reason}`,
    30,
    8,
  );

  await repo.event(
    "playwright_screenshot_retry",
    "amazon",
    dealKey,
    {reason},
  );

  return json({
    ok:true,
    state:"verified_retry",
  });
}

async function ingestNoonPlaywright(
  request: Request,
  env: V14Env,
): Promise<Response> {
  if (!adminAllowed(request, env)) {
    return json(
      {ok:false,error:"unauthorized"},
      401,
    );
  }

  let body: any = {};

  try {
    body = await request.json();
  } catch {
    return json(
      {ok:false,error:"invalid_json"},
      400,
    );
  }

  const rows =
    Array.isArray(body?.deals)
      ? body.deals.slice(0, 30)
      : [];

  const source =
    String(
      body?.source || "rendered"
    )
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "_")
      .slice(0, 40)
      || "rendered";

  const category =
    String(
      body?.category || "general"
    )
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "_")
      .slice(0, 40)
      || "general";

  const sourceName =
    `gha_noon_${source}`;

  const fetched =
    Math.max(
      rows.length,
      Math.min(
        100,
        Math.floor(
          Number(body?.seen || 0)
        )
      )
    );

  const latency =
    Math.max(
      0,
      Math.min(
        120000,
        Math.floor(
          Number(body?.latency_ms || 0)
        )
      )
    );

  const scanError =
    String(
      body?.error || ""
    ).slice(0, 400);

  const repo =
    new D1Repository(
      env.egypt_deals_v14_db
    );

  const settings =
    getSettings(env);

  let accepted = 0;
  let queued = 0;

  for (const raw of rows) {
    const sku =
      String(
        raw?.external_id ||
        raw?.sku ||
        ""
      )
        .trim()
        .slice(0, 80);

    const title =
      String(raw?.title || "")
        .trim()
        .slice(0, 300);

    const url =
      String(raw?.url || "")
        .trim()
        .slice(0, 1000);

    const current =
      Number(
        raw?.current_price || 0
      );

    let old =
      Number(
        raw?.old_price || 0
      );

    if (
      !sku ||
      title.length < 5 ||
      !(current > 0)
    ) {
      continue;
    }

    let parsed: URL;

    try {
      parsed = new URL(url);
    } catch {
      continue;
    }

    if (
      parsed.protocol !== "https:" ||
      !(
        parsed.hostname === "www.noon.com" ||
        parsed.hostname === "noon.com"
      ) ||
      !(
        parsed.pathname.includes("/egypt-en/") ||
        parsed.pathname.includes("/egypt-ar/")
      )
    ) {
      continue;
    }

    if (!(old > current)) {
      old = 0;
    }

    const visible =
      old > current
        ? (
            (old - current)
            / old
          ) * 100
        : 0;

    /*
     * The rendered discovery worker is a lead generator.
     * We keep only worthwhile Noon candidates here;
     * Cloudflare still performs independent product API
     * verification before Telegram delivery.
     */
    if (
      visible <
      settings.normal_min_discount
    ) {
      continue;
    }

    const deal: DealCandidate = {
      store:"noon",
      external_id:sku,
      title,
      url,
      current_price:current,
      old_price:
        old > current
          ? old
          : null,
      image_url:
        String(
          raw?.image_url || ""
        ).slice(0, 1500),
      category,
      source:sourceName,
      metadata:{
        github_playwright_noon_discovery:true,
        rendered_search_page:true,
        locale:"en-eg",
        currency:"EGP",
      },
    };

    const preliminary =
      preliminaryDecision(
        settings,
        deal,
      );

    preliminary.lane =
      "normal";

    const result =
      await repo.upsertCandidate(
        deal,
        preliminary,
      );

    accepted++;

    if (result.new_or_reopened) {
      queued++;
    }
  }

  await repo.sourceResult(
    "noon",
    sourceName,
    category,
    fetched,
    queued,
    latency,
    scanError,
  );

  await repo.event(
    "github_noon_ingest",
    "noon",
    "",
    {
      source:sourceName,
      fetched,
      accepted,
      queued,
      error:scanError,
    },
  );

  return json({
    ok:true,
    source:sourceName,
    fetched,
    accepted,
    queued,
  });
}


async function bootstrap(request: Request, env: V14Env): Promise<Response> {
  if (!adminAllowed(request, env)) return json({ok:false,error:'unauthorized'}, 401);

  const base = new URL(request.url).origin;

  const mainToken = String(env.TELEGRAM_BOT_TOKEN || '').trim();
  const noonToken = String(env.NOON_REVIEW_BOT_TOKEN || mainToken).trim();

  const mainSecret = String(env.TELEGRAM_WEBHOOK_SECRET || '').trim();
  const noonSecret = String(env.NOON_TELEGRAM_WEBHOOK_SECRET || mainSecret).trim();

  if (!mainToken || !mainSecret) {
    return json({ok:false,error:'telegram_secrets_missing'}, 400);
  }

  await setWebhook(
    mainToken,
    `${base}/telegram/main`,
    mainSecret
  );

  const separateNoonBot =
    Boolean(noonToken && noonToken !== mainToken);

  if (separateNoonBot) {
    await setWebhook(
      noonToken,
      `${base}/telegram/noon`,
      noonSecret
    );
  }

  return json({
    ok: true,
    webhooks: separateNoonBot
      ? ['main','noon']
      : ['main'],
    noon_mode: separateNoonBot
      ? 'separate_bot'
      : 'main_bot_normal_lane_only'
  });
}


export default {
  async fetch(request: Request, env: V14Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === 'GET' && url.pathname === '/') {
      return json({ service:'egypt-deals-v14', status:'ok', mode:'cloudflare', policy:{amazon_ultra_min:65,amazon_hot_min:75,noon_ultra:false} });
    }
    if (request.method === 'GET' && url.pathname === '/health') {
      const repo = new D1Repository(env.egypt_deals_v14_db);
      return json({
        ok:true,
        stats:await repo.stats(),
        browser_ms_today:
          await repo.counterGet(
            `browser_ms:${new Date().toISOString().slice(0,10)}`
          ),
        noon_route_ready:
          Boolean(
            await repo.counterGet("noon_review_chat_id")
          ),
      });
    }
    if (request.method === 'POST' && url.pathname === '/telegram/main') {
      if ((request.headers.get('x-telegram-bot-api-secret-token') || '') !== String(env.TELEGRAM_WEBHOOK_SECRET || '')) return new Response('forbidden',{status:403});
      return handleTelegramUpdate(env,'main',await request.json());
    }
    if (request.method === 'POST' && url.pathname === '/telegram/noon') {
      const expected = String(env.NOON_TELEGRAM_WEBHOOK_SECRET || env.TELEGRAM_WEBHOOK_SECRET || '');
      if ((request.headers.get('x-telegram-bot-api-secret-token') || '') !== expected) return new Response('forbidden',{status:403});
      return handleTelegramUpdate(env,'noon',await request.json());
    }
    if (
      request.method === "POST" &&
      url.pathname === "/internal/import-noon-route"
    ) {
      return importNoonRoute(request, env);
    }

    if (
      request.method === "POST" &&
      url.pathname === "/admin/noon-ingest"
    ) {
      return ingestNoonPlaywright(
        request,
        env,
      );
    }

    if (
      request.method === "POST" &&
      url.pathname === "/admin/playwright-verify/claim"
    ) {
      if (!adminAllowed(request, env)) {
        return json(
          {ok:false,error:"unauthorized"},
          401,
        );
      }

      return claimPlaywrightVerification(
        request,
        env,
      );
    }

    if (
      request.method === "POST" &&
      url.pathname === "/admin/playwright-verify/complete"
    ) {
      if (!adminAllowed(request, env)) {
        return json(
          {ok:false,error:"unauthorized"},
          401,
        );
      }

      return completePlaywrightVerification(
        request,
        env,
      );
    }

    if (
      request.method === "POST" &&
      url.pathname === "/admin/screenshot/claim"
    ) {
      if (!adminAllowed(request, env)) {
        return json(
          {ok:false,error:"unauthorized"},
          401,
        );
      }

      return claimScreenshotJob(
        request,
        env,
      );
    }

    if (
      request.method === "POST" &&
      url.pathname === "/admin/screenshot/complete"
    ) {
      if (!adminAllowed(request, env)) {
        return json(
          {ok:false,error:"unauthorized"},
          401,
        );
      }

      return completeScreenshotJob(
        request,
        env,
      );
    }

    if (request.method === 'POST' && url.pathname === '/admin/bootstrap') return bootstrap(request, env);
    if (request.method === 'POST' && url.pathname === '/admin/run') {
      if (!adminAllowed(request, env)) return json({ok:false,error:'unauthorized'},401);
      return json(await runCycle(env,getSettings(env)));
    }
    return json({ok:false,error:'not_found'},404);
  },

  async scheduled(controller: ScheduledController, env: V14Env, ctx: ExecutionContext): Promise<void> {
    const job: JobMessage = { type:'cycle', scheduled_at: controller.scheduledTime };
    ctx.waitUntil(env.JOBS.send(job));
  },

  async queue(batch: MessageBatch<JobMessage>, env: V14Env): Promise<void> {
    const settings = getSettings(env);
    for (const message of batch.messages) {
      if (message.body?.type !== 'cycle') { message.ack(); continue; }
      try {
        await runCycle(env, settings);
        message.ack();
      } catch (e) {
        console.error(JSON.stringify({event:'cycle_error',error:e instanceof Error ? `${e.name}:${e.message}` : String(e)}));
        message.retry({delaySeconds:30});
      }
    }
  },
} satisfies ExportedHandler<V14Env, JobMessage>;
