import type { DealCandidate, DealDecision, DealRow, Settings, Surface, V14Env } from './types';
import { AMAZON_SURFACES, fetchAmazonSurface, parseAmazon } from './amazon';
import { NOON_SURFACES, fetchNoonSurface, parseNoon } from './noon';
import { D1Repository } from './db';
import { acceptable, buildPriceProfile, evaluateDeal, preliminaryDecision } from './intelligence';
import { inspectDeal } from './shield';
import { titleSimilarity, compatibility, signature } from './identity';
import { discountPercent, safeJsonParse } from './util';
import { VerificationRejected, verifyRow } from './verifier';
import { answerCallback, clearButtons, sendPublic, sendReview, tokenForWebhook } from './telegram';

function workerId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID().slice(0, 8)}`;
}

/*
 * Dedicated Amazon Ultra discovery schedule.
 *
 * It deliberately gives more scanning weight to
 * the largest discount targets:
 *
 * 90% sources -> highest frequency
 * 75% sources -> next
 * 70% sources -> next
 * 65% sources -> safety floor
 *
 * This is discovery priority only.
 * A deal still cannot become Ultra until the
 * product-page verifier confirms >=65% REAL discount.
 */
const AMAZON_ULTRA_HUNTER_ORDER: string[] = [
  /*
   * Weighted from real V14 source performance.
   *
   * Proven historical Ultra producers get more
   * opportunities, while global percentage filters
   * remain as exploration/safety sources.
   *
   * Verification remains completely independent:
   * NO source can bypass the rendered Amazon
   * product-page Ultra proof.
   */

  "books",
  "books",
  "books",

  "tvs",
  "tvs",

  "shoes_65hot",
  "shoes_65hot",

  "goldbox",
  "goldbox",

  "networking_65hot",
  "gaming_65hot",
  "beauty_65hot",

  /*
   * Keep percentage filters for exploration,
   * but do not waste most cycles on sources that
   * frequently return zero usable results.
   */
  "90filter",
  "75filter",
  "70filter",
  "65filter",
];


async function fetchNoonSurfaceWithFallback(
  env: V14Env,
  repo: D1Repository,
  settings: Settings,
  surface: Surface,
): Promise<{text: string; latency: number}> {

  try {
    // Cheap path first. If Noon accepts normal Worker HTTP,
    // Browser Run is not used at all.
    return await fetchNoonSurface(surface);
  } catch (directError) {

    if (!env.BROWSER || settings.browser_daily_budget_ms <= 0) {
      throw directError;
    }

    const day = new Date().toISOString().slice(0, 10);
    const counterKey = `browser_ms:${day}`;
    const alreadyUsed = await repo.counterGet(counterKey);

    /*
     * Cloudflare Free Browser budget is precious.
     *
     * Noon may use at most the first 25% of the
     * shared daily browser budget. The remaining
     * 75% stays available for high-value Amazon
     * verification and real screenshots.
     */
    const noonBrowserLimit =
      Math.floor(
        settings.browser_daily_budget_ms *
        0.25
      );

    if (
      alreadyUsed >= noonBrowserLimit
    ) {
      throw new Error(
        `noon_browser_budget_reserved_for_amazon_ultra:${alreadyUsed}`
      );
    }

    const started = Date.now();

    const response: Response =
      await env.BROWSER.quickAction(
        "content",
        {
          url: surface.url,

          gotoOptions: {
            waitUntil: "networkidle2",
            timeout: 20000,
          },

          waitForTimeout: 900,

          userAgent:
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
            "AppleWebKit/537.36 (KHTML, like Gecko) " +
            "Chrome/140.0 Safari/537.36",

          setExtraHTTPHeaders: {
            "Accept-Language":
              "en-EG,en;q=0.9,ar-EG;q=0.8,ar;q=0.7",
            "x-locale": "en-eg",
            "x-platform": "web",
            "x-mp": "noon",
            "x-mp-country": "eg",
            "x-country-code": "eg",
          },

          // Product discovery needs HTML/JS, not heavy media.
          rejectResourceTypes: [
            "image",
            "font",
            "media",
          ],
        },
      );

    const browserMs = Number(
      response.headers.get("X-Browser-Ms-Used") || 0
    );

    if (browserMs > 0) {
      await repo.counterAdd(
        counterKey,
        browserMs,
      );
    }

    if (!response.ok) {
      throw new Error(
        `noon_browser_http_${response.status}`
      );
    }

    const text = await response.text();

    if (!text || text.length < 1000) {
      throw new Error(
        "noon_browser_empty_page"
      );
    }

    return {
      text,
      latency: Date.now() - started,
    };
  }
}

function bestCrossStoreMatch(deal: DealCandidate, rows: DealRow[]): { row: DealRow | null; similarity: number } {
  let best: DealRow | null = null; let bestSim = 0;
  const sig = signature(deal.title);
  for (const row of rows) {
    const [ok] = compatibility(sig, signature(String(row.title || ''))); if (!ok) continue;
    const sim = titleSimilarity(deal.title, String(row.title || ''));
    if (sim > bestSim) { best = row; bestSim = sim; }
  }
  if (bestSim < 0.72) return { row: null, similarity: bestSim };
  return { row: best, similarity: bestSim };
}

async function admitAmazon(repo: D1Repository, settings: Settings, surface: Surface, deals: DealCandidate[]): Promise<number> {
  let queued = 0;
  let probeId = '';
  if (deals.length && !['goldbox','limited_time','clearance'].includes(surface.name)) {
    const eligible = deals.filter(x => x.current_price > 0);
    if (eligible.length) {
      const c = await repo.counterAdd(`coupon_probe:${surface.name}`, 1);
      probeId = eligible[(c - 1) % eligible.length].external_id;
    }
  }

  const ranked = deals.slice().sort((a,b) => discountPercent(b)-discountPercent(a));
  for (const base of ranked.slice(0, Math.max(settings.amazon_discovery_limit, 1) * 2)) {
    if (!(base.current_price > 0)) continue;
    const deal: DealCandidate = { ...base, metadata: { ...(base.metadata || {}) } };
    const isProbe = Boolean(probeId && deal.external_id === probeId);
    if (isProbe) Object.assign(deal.metadata!, { coupon_probe: true, coupon_probe_surface: surface.name });
    const meta = deal.metadata || {};
    const goldbox = surface.name === 'goldbox' || Boolean(meta.goldbox);
    const promo = Boolean(meta.promo_hint || meta.coupon_hint || meta.flash_hint);
    const visible = discountPercent(deal) >= settings.normal_min_discount;
    if (!(isProbe || goldbox || promo || visible)) continue;
    const prelim = preliminaryDecision(settings, deal);
    if (isProbe) {
      prelim.score = Math.max(prelim.score, 87);
      if (!prelim.reasons.includes('amazon_coupon_probe')) prelim.reasons.push('amazon_coupon_probe');
    }
    const result = await repo.upsertCandidate(deal, prelim);
    if (result.new_or_reopened) queued++;
    if (queued >= settings.amazon_discovery_limit) break;
  }
  return queued;
}

async function admitNoon(repo: D1Repository, settings: Settings, deals: DealCandidate[]): Promise<number> {
  let queued = 0;
  const ranked = deals.slice().sort((a,b) => discountPercent(b)-discountPercent(a));
  for (const deal of ranked) {
    if (!(deal.current_price > 0)) continue;
    const visible = discountPercent(deal);
    // Normal Noon path only. We still allow one no-discount candidate per scan so
    // trusted history can mature, but never route it to Ultra.
    if (visible < settings.normal_min_discount && queued > 0) continue;
    const prelim = preliminaryDecision(settings, deal);
    prelim.lane = 'normal';
    const result = await repo.upsertCandidate(deal, prelim);
    if (result.new_or_reopened) queued++;
    if (queued >= settings.noon_discovery_limit) break;
  }
  return queued;
}

async function scanAmazonSurface(repo: D1Repository, settings: Settings, surface: Surface): Promise<Record<string, unknown>> {
  let fetched = 0, queued = 0, latency = 0, error = '';
  try {
    const result = await fetchAmazonSurface(surface); latency = result.latency;
    const deals = parseAmazon(result.text, surface); fetched = deals.length;
    queued = await admitAmazon(repo, settings, surface, deals);
  } catch (e) { error = `${e instanceof Error ? e.name : 'Error'}:${e instanceof Error ? e.message : String(e)}`; }
  await repo.sourceResult('amazon', surface.name, surface.category, fetched, queued, latency, error);
  return { store: 'amazon', source: surface.name, fetched, queued, error: Boolean(error) };
}

async function scanNoonSurface(env: V14Env, repo: D1Repository, settings: Settings, surface: Surface): Promise<Record<string, unknown>> {
  let fetched = 0, queued = 0, latency = 0, error = '';
  try {
    const result = await fetchNoonSurfaceWithFallback(env, repo, settings, surface); latency = result.latency;
    const deals = parseNoon(result.text, surface); fetched = deals.length;
    queued = await admitNoon(repo, settings, deals);
  } catch (e) { error = `${e instanceof Error ? e.name : 'Error'}:${e instanceof Error ? e.message : String(e)}`; }
  await repo.sourceResult('noon', surface.name, surface.category, fetched, queued, latency, error);
  return { store: 'noon', source: surface.name, fetched, queued, error: Boolean(error) };
}

async function discoveryStep(
  env: V14Env,
  repo: D1Repository,
  settings: Settings,
): Promise<Record<string, unknown>[]> {

  const cycle = await repo.counterAdd(
    "cycle_count",
    1,
  );

  const aCur = await repo.counterAdd(
    "amazon_surface_cursor",
    1,
  );

  const ultraHunterNames =
    new Set<string>(
      AMAZON_ULTRA_HUNTER_ORDER
    );

  /*
   * General Amazon discovery remains active,
   * but dedicated Ultra-global sources are removed
   * here to avoid pointless duplicate scans.
   */
  const amazonRegular =
    AMAZON_SURFACES.filter(
      x =>
        x.name !== "goldbox" &&
        !ultraHunterNames.has(x.name)
    );

  const aSurface =
    amazonRegular[
      (aCur - 1)
      % amazonRegular.length
    ];

  /*
   * Separate Ultra hunter runs every cycle.
   * Its schedule is weighted toward 90% first.
   */
  const ultraCursor =
    await repo.counterAdd(
      "amazon_ultra_surface_cursor",
      1,
    );

  const ultraSourceName =
    AMAZON_ULTRA_HUNTER_ORDER[
      (ultraCursor - 1)
      % AMAZON_ULTRA_HUNTER_ORDER.length
    ];

  const ultraSurface =
    AMAZON_SURFACES.find(
      x => x.name === ultraSourceName
    );

  const tasks:
    Promise<Record<string, unknown>>[] = [];

  if (ultraSurface) {
    tasks.push(
      scanAmazonSurface(
        repo,
        settings,
        ultraSurface,
      ),
    );
  }

  /*
   * Keep broad category coverage in parallel.
   */
  if (aSurface) {
    tasks.push(
      scanAmazonSurface(
        repo,
        settings,
        aSurface,
      ),
    );
  }

  /*
   * Noon discovery disabled intentionally.
   * Cloudflare resources are reserved for Amazon,
   * with Amazon Ultra having absolute priority.
   */

  // Today's Deals remains a frequent Amazon safety net.
  if (cycle % 2 === 0) {
    const goldbox =
      AMAZON_SURFACES.find(
        x => x.name === "goldbox"
      );

    if (
      goldbox &&
      goldbox.name !== ultraSurface?.name
    ) {
      tasks.push(
        scanAmazonSurface(
          repo,
          settings,
          goldbox,
        ),
      );
    }
  }

  return Promise.all(tasks);
}

async function verifyOne(env: V14Env, repo: D1Repository, settings: Settings): Promise<Record<string, unknown> | null> {
  /*
   * HYBRID V14:
   * Cloudflare verifies Amazon Normal.
   * GitHub Playwright verifies Amazon Ultra using
   * the fully rendered Amazon product page.
   */
  const order: Array<['amazon','normal']> = [
    ['amazon','normal'],
  ];
  let row: DealRow | null = null;
  for (const [store,lane] of order) {
    row = await repo.claimForVerification(store, lane, workerId(`verify-${store}-${lane}`), settings.lease_seconds);
    if (row) break;
  }
  if (!row) return null;

  const discoveryStrongUltra =
    row.store === 'amazon' &&
    Number(row.visible_discount || 0)
      >= settings.ultra_min_discount;

  try {
    const incoming = repo.rowToCandidate(row);
    const { deal: verified, meta } = await verifyRow(env, repo, settings, row);
    const history = await repo.recentPrices(row.deal_key);
    const profile = buildPriceProfile(history, verified.current_price);
    const shield = inspectDeal(incoming, verified, meta, profile);
    if (shield.hard_block) {
      const reason = `anti_fake:${shield.reasons.join(',')}`;
      await repo.markRejected(row.deal_key, reason);
      return { deal: row.deal_key.slice(0,10), state: 'rejected', reason };
    }

    const others = await repo.recentOtherStore(verified.store);
    const cross = bestCrossStoreMatch(verified, others);
    const incomingMeta = incoming.metadata || {};
    const decision = evaluateDeal(settings, verified, {
      verified: true,
      coupon_percent: Number(meta.coupon_percent || 0),
      flash: Boolean(meta.flash),
      anomaly: Boolean(incomingMeta.price_anomaly),
      history,
      verification_signals: Number(meta.verification_signals || 0),
      price_profile: profile,
      cross_store_price: cross.row ? Number(cross.row.current_price || 0) : null,
      cross_store_store: cross.row?.store || null,
      cross_store_similarity: cross.similarity,
    });
    const [ok, reason] =
      acceptable(settings, decision);

    if (!ok) {
      /*
       * A discovery >=65% with incomplete live evidence
       * is not automatically fake.
       *
       * Retry it with increasing delay.
       */
      if (
        discoveryStrongUltra &&
        [
          'discount_below_normal_threshold',
          'normal_confidence_low',
          'ultra_confidence_low',
        ].includes(reason)
      ) {
        const retryReason =
          `strong_ultra_inconclusive:${reason}`;

        await repo.markStrongRetry(
          row.deal_key,
          retryReason,
          1800,
          8,
        );

        return {
          deal: row.deal_key.slice(0,10),
          state: 'retry',
          reason: retryReason,
        };
      }

      await repo.markRejected(
        row.deal_key,
        reason,
      );

      return {
        deal: row.deal_key.slice(0,10),
        state:'rejected',
        reason
      };
    }

    const signals = Number(meta.verification_signals || 0);
    const requiredSignals = Math.max(2, shield.required_signals);
    let hot = false;
    if (verified.store === 'noon') {
      decision.lane = 'normal';
      if (!decision.reasons.includes('noon_normal_only')) decision.reasons.push('noon_normal_only');
    } else if (decision.real_discount >= settings.ultra_hot_discount) {
      if (!(signals >= requiredSignals && decision.confidence >= settings.min_confidence_ultra)) {
        await repo.markStrongRetry(
          row.deal_key,
          'amazon_75_needs_stronger_verification',
          1800,
          8,
        );

        return {
          deal: row.deal_key.slice(0,10),
          state:'retry',
          reason:'amazon_75_needs_stronger_verification'
        };
      }
      decision.lane = 'ultra'; decision.score = 100; hot = true;
      if (!decision.reasons.includes('amazon_ultra_max_75')) decision.reasons.push('amazon_ultra_max_75');
    } else if (decision.real_discount >= settings.ultra_min_discount) {
      if (!(signals >= requiredSignals && decision.confidence >= settings.min_confidence_ultra)) {
        await repo.markStrongRetry(
          row.deal_key,
          'amazon_65_needs_stronger_verification',
          1800,
          8,
        );

        return {
          deal: row.deal_key.slice(0,10),
          state:'retry',
          reason:'amazon_65_needs_stronger_verification'
        };
      }
      decision.lane = 'ultra'; decision.score = Math.max(decision.score, 94);
      if (!decision.reasons.includes('amazon_ultra_65')) decision.reasons.push('amazon_ultra_65');
    } else {
      decision.lane = 'normal';
      if (!decision.reasons.includes('amazon_below_ultra_65')) decision.reasons.push('amazon_below_ultra_65');
    }

    const outMeta: Record<string, unknown> = { ...(verified.metadata || {}), ...meta,
      decision_reasons: decision.reasons, verified_route: decision.lane, exceptional_priority: hot, hot_priority: hot,
      price_intelligence: profile, deal_score_breakdown: decision.score_breakdown,
      anti_fake_shield: { risk_score: shield.risk_score, required_signals: requiredSignals, reasons: shield.reasons },
    };
    if (cross.row) outMeta.cross_store = { store: cross.row.store, price: cross.row.current_price, similarity: Math.round(cross.similarity*1000)/1000 };
    await repo.markVerified(row.deal_key, verified, decision, outMeta);
    return { deal: row.deal_key.slice(0,10), state:'verified', store: verified.store, lane: decision.lane, discount: decision.real_discount, confidence: decision.confidence, score: decision.score };
  } catch (e) {
    if (e instanceof VerificationRejected) {
      const reason = e.message;

      const technicalStrongFailure =
        discoveryStrongUltra &&
        (
          reason.startsWith('browser_') ||
          reason === 'amazon_protected' ||
          reason === 'amazon_no_live_price' ||
          reason === 'amazon_browser_no_price'
        );

      if (technicalStrongFailure) {
        const baseDelay =
          (
            reason.includes('429') ||
            reason.includes('budget')
          )
            ? 3600
            : 1800;

        await repo.markStrongRetry(
          row.deal_key,
          reason,
          baseDelay,
          8,
        );

        return {
          deal: row.deal_key.slice(0,10),
          state:'retry',
          reason
        };
      }

      await repo.markRejected(
        row.deal_key,
        reason
      );

      return {
        deal: row.deal_key.slice(0,10),
        state:'rejected',
        reason
      };
    }

    const reason =
      `${e instanceof Error ? e.name : 'Error'}:${
        e instanceof Error
          ? e.message
          : String(e)
      }`;

    if (discoveryStrongUltra) {
      await repo.markStrongRetry(
        row.deal_key,
        reason,
        1800,
        8,
      );
    } else {
      await repo.markRetry(
        row.deal_key,
        reason,
        settings.retry_base_seconds,
        settings.max_attempts,
      );
    }

    return {
      deal: row.deal_key.slice(0,10),
      state:'retry',
      reason
    };
  }
}

async function deliveryStep(
  env: V14Env,
  repo: D1Repository,
  settings: Settings,
): Promise<Record<string, unknown>[]> {

  /*
   * V14 HYBRID DELIVERY
   *
   * Cloudflare:
   * discovery + verification + intelligence + D1
   *
   * GitHub Playwright:
   * every automatic Amazon review delivery
   * with a REAL product-page screenshot.
   *
   * Do not let Cloudflare race the screenshot worker.
   */
  void env;
  void repo;
  void settings;

  return [];
}

export async function runCycle(env: V14Env, settings: Settings): Promise<Record<string, unknown>> {
  const repo = new D1Repository(env.egypt_deals_v14_db);
  const stale = await repo.releaseStaleLeases();
  const discovery = await discoveryStep(env, repo, settings);
  const verified: Record<string, unknown>[] = [];
  for (let i=0;i<3;i++) { const x = await verifyOne(env, repo, settings); if (!x) break; verified.push(x); }
  const delivered = await deliveryStep(env, repo, settings);
  const stats = await repo.stats();
  const result = { event:'v14_cycle', stale_released: stale, discovery, verified, delivered, stats };
  console.log(JSON.stringify(result));
  return result;
}

async function callbackAllowed(
  env: V14Env,
  repo: D1Repository,
  chatId: string,
): Promise<boolean> {
  const allowed = new Set([
    String(
      env.V13_NORMAL_REVIEW_CHAT_ID ||
      env.REVIEW_CHAT_ID ||
      env.AMAZON_NORMAL_REVIEW_CHAT_ID ||
      ""
    ),
    String(
      env.V13_ULTRA_REVIEW_CHAT_ID ||
      env.AMAZON_REVIEW_GROUP_ID ||
      ""
    ),
    String(
      env.NOON_REVIEW_BOT_CHAT_ID ||
      env.NOON_NORMAL_REVIEW_CHAT_ID ||
      ""
    ),
  ].filter(Boolean));

  const runtimeNoonChat =
    await repo.counterGet("noon_review_chat_id");

  if (runtimeNoonChat) {
    allowed.add(String(runtimeNoonChat));
  }

  return Boolean(
    chatId &&
    allowed.has(chatId)
  );
}

export async function handleTelegramUpdate(env: V14Env, route: 'main'|'noon', update: any): Promise<Response> {
  const cb = update?.callback_query;
  if (!cb) return new Response('ok');
  const message = cb.message || {};
  const chatId = String(message?.chat?.id || "");
  const token = tokenForWebhook(env, route);
  const cbId = String(cb.id || "");

  const repo =
    new D1Repository(env.egypt_deals_v14_db);

  if (!(await callbackAllowed(env, repo, chatId))) {
    await answerCallback(
      token,
      cbId,
      "غير مصرح",
      true,
    );
    return new Response("ok");
  }

  const parts =
    String(cb.data || "").split(":");

  if (
    parts.length !== 3 ||
    parts[0] !== "v14"
  ) {
    return new Response("ok");
  }

  const [_, action, shortKey] = parts;
  const row = await repo.findByPrefix(shortKey);
  if (!row) { await answerCallback(token, cbId, 'العرض غير موجود في قاعدة V14', true); return new Response('ok'); }

  if (action === 'r') {
    await repo.event('manual_reject', row.store, row.deal_key, {action:'reject'});
    await answerCallback(token, cbId, 'تم رفض العرض ❌');
  } else if (action === 'p' || action === 'u') {
    if (await repo.hasEvent(row.deal_key, 'manual_publish')) { await answerCallback(token, cbId, 'تم نشر العرض بالفعل'); return new Response('ok'); }
    try {
      const settings = (await import('./config')).getSettings(env);
      const { deal: fresh } = await verifyRow(env, repo, settings, row);
      const reviewed = Number(row.current_price || 0), freshPrice = Number(fresh.current_price || 0);
      if (reviewed > 0 && freshPrice > reviewed * 1.02) { await answerCallback(token, cbId, 'السعر ارتفع منذ المراجعة؛ لم يتم النشر', true); return new Response('ok'); }
      const publicRow: DealRow = { ...row, title: fresh.title || row.title, url: fresh.url || row.url, image_url: fresh.image_url || row.image_url,
        current_price: freshPrice || reviewed, old_price: fresh.old_price ?? row.old_price };
      await sendPublic(env, publicRow, action === 'u', repo);
      await repo.event('manual_publish', row.store, row.deal_key, {urgent: action === 'u'});
      await answerCallback(token, cbId, action === 'u' ? 'تم النشر العاجل 🚀' : 'تم النشر ✅');
    } catch (e) {
      await answerCallback(token, cbId, e instanceof VerificationRejected ? 'العرض لم يعد يحقق شروط التحقق' : 'تعذر إعادة التحقق الآن، جرّب مرة أخرى', true);
      return new Response('ok');
    }
  } else return new Response('ok');
  try { await clearButtons(token, chatId, Number(message.message_id)); } catch {}
  return new Response('ok');
}
