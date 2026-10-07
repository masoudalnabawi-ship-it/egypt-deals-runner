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

  /*
   * shoes_65hot repeatedly produced misleading
   * discovery old-prices with no live Amazon proof.
   * Replace its premium slots with higher-quality
   * deal surfaces. It remains available in broad scan.
   */
  "limited_time",
  "clearance",

  "goldbox",
  "goldbox",

  "networking_65hot",
  "gaming_65hot",
  "beauty_65hot",

  /*
   * FULL-DEPARTMENT ULTRA EXPLORATION.
   *
   * These get one slot each. Proven sources such as
   * books/tvs/goldbox remain weighted above them.
   */
  "electronics_65hot",
  "appliances_65hot",
  "mobiles_65hot",
  "laptops_65hot",
  "tablets_65hot",
  "audio_65hot",
  "cameras_65hot",
  "smart_home_65hot",

  "kitchen_65hot",
  "home_65hot",
  "furniture_65hot",
  "tools_65hot",
  "cleaning_65hot",

  "personal_care_65hot",
  "health_65hot",
  "perfumes_65hot",
  "fashion_65hot",
  "bags_65hot",
  "watches_65hot",
  "jewelry_65hot",

  "sports_65hot",
  "outdoor_65hot",
  "toys_65hot",
  "baby_65hot",

  "grocery_65hot",
  "supermarket_65hot",
  "food_beverage_65hot",
  "snacks_65hot",
  "coffee_tea_65hot",
  "household_essentials_65hot",
  "laundry_65hot",

  "skincare_65hot",
  "haircare_65hot",
  "oral_care_65hot",

  "storage_65hot",
  "bedding_65hot",
  "lighting_65hot",
  "garden_65hot",

  "pet_65hot",
  "pet_food_65hot",

  "office_65hot",
  "stationery_65hot",
  "printers_65hot",
  "books_65hot",

  "automotive_65hot",
  "car_care_65hot",
  "music_65hot",

  "fitness_65hot",
  "cycling_65hot",

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


/*
 * AMAZON_ULTRA_V4_EXCEPTIONAL_HUNTER
 *
 * Separate radar dedicated to >=80% discovery.
 * Highest discount Amazon filters are explored first,
 * then the historically productive categories.
 *
 * Final qualification still requires rendered live proof.
 */
const AMAZON_EXCEPTIONAL_HUNTER_ORDER = [
  "95filter",
  "90filter",
  "85filter",
  "80filter",

  "95off",
  "90off",
  "85off",
  "80off",

  "goldbox",
  "limited_time",
  "clearance",

  /*
   * Strong historical V14 categories first.
   */
  "automotive_80filter",
  "personal_care_80filter",
  "beauty_80filter",
  "pet_food_80filter",
  "snacks_80filter",
  "chocolate_80filter",

  "tvs_80filter",
  "computer_accessories_80filter",
  "gaming_80filter",
  "smart_home_80filter",
  "electronics_80filter",

  "appliances_80filter",
  "home_80filter",

  "books_80filter",
  "baby_80filter",
  "grocery_80filter",
  "shoes_80filter",
  "sports_80filter",
  "office_80filter",
];


/*
 * Dedicated supermarket rotation.
 *
 * One supermarket surface every 3 cycles keeps grocery
 * coverage fresh without flooding Amazon with requests.
 */
const AMAZON_SUPERMARKET_SWEEP_ORDER = [
  "supermarket",
  "grocery",
  "pantry",
  "snacks",
  "chocolate",
  "biscuits",
  "breakfast",
  "rice_pasta",
  "canned_food",
  "sauces",
  "spices",
  "oils_ghee",
  "baking",
  "coffee",
  "tea",
  "beverages",
  "water",
  "juices",
  "soft_drinks",
  "energy_drinks",
  "household_essentials",
  "laundry",
  "dishwashing",
  "paper_tissues",
  "trash_bags",
  "air_fresheners",
  "pet_food",
];


/*
 * Cross-department sweep.
 *
 * This is separate from the normal generic rotation so
 * large Amazon departments cannot starve smaller ones.
 */
const AMAZON_DEPARTMENT_SWEEP_ORDER = [
  "mobiles",
  "mobile_accessories",
  "laptops",
  "computer_accessories",
  "tablets",
  "tvs",
  "audio",
  "gaming",
  "cameras",
  "networking",
  "smart_home",

  "appliances",
  "refrigerators",
  "washers",
  "ac",

  "kitchen",
  "cookware",
  "home",
  "furniture",
  "storage",
  "bedding",
  "bath",
  "lighting",
  "garden",

  "tools",
  "hardware",
  "electrical",
  "plumbing",

  "beauty",
  "skincare",
  "haircare",
  "personal_care",
  "oral_care",
  "deodorants",
  "shaving",
  "perfumes",
  "health",

  "men_fashion",
  "women_fashion",
  "kids_fashion",
  "shoes",
  "bags",
  "watches",
  "jewelry",
  "luggage",

  "sports",
  "fitness",
  "cycling",
  "outdoor",

  "toys",
  "baby",

  "office",
  "stationery",
  "school_supplies",
  "arts_crafts",
  "printers",

  "books",
  "musical_instruments",

  "automotive",
  "car_care",

  "pets",
  "pet_food",
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

  const exceptionalSource =
    (
      surface.name.includes("80filter")
      || surface.name.includes("85filter")
      || surface.name.includes("90filter")
      || surface.name.includes("95filter")
      || surface.name === "80off"
      || surface.name === "85off"
      || surface.name === "90off"
      || surface.name === "95off"
    );

  /*
   * A single exceptional page may contain many valuable
   * candidates. Allow more of them into verification.
   */
  const sourceLimit =
    exceptionalSource
      ? Math.min(
          20,
          Math.max(
            settings.amazon_discovery_limit,
            16,
          )
        )
      : settings.amazon_discovery_limit;

  let probeId = '';
  if (deals.length && !['goldbox','limited_time','clearance'].includes(surface.name)) {
    const eligible = deals.filter(x => x.current_price > 0);
    if (eligible.length) {
      const c = await repo.counterAdd(`coupon_probe:${surface.name}`, 1);
      probeId = eligible[(c - 1) % eligible.length].external_id;
    }
  }

  const ranked = deals.slice().sort((a,b) => discountPercent(b)-discountPercent(a));
  for (const base of ranked.slice(0, Math.max(sourceLimit, 1) * 2)) {
    if (!(base.current_price > 0)) continue;
    const deal: DealCandidate = { ...base, metadata: { ...(base.metadata || {}) } };
    const isProbe = Boolean(probeId && deal.external_id === probeId);
    if (isProbe) Object.assign(deal.metadata!, { coupon_probe: true, coupon_probe_surface: surface.name });
    const meta = deal.metadata || {};
    const goldbox = surface.name === 'goldbox' || Boolean(meta.goldbox);
    const promo = Boolean(meta.promo_hint || meta.coupon_hint || meta.flash_hint);
    const visiblePct =
      discountPercent(deal);

    const visible =
      visiblePct >=
      settings.normal_min_discount;

    /*
     * Exceptional-filter pages occasionally contain sponsored
     * or unrelated products. Do not waste Ultra verification
     * unless the card itself still carries strong discount
     * evidence or an explicit promo signal.
     */
    if (
      exceptionalSource
      &&
      visiblePct <
        settings.ultra_min_discount
      &&
      !promo
    ) {
      continue;
    }

    if (!(isProbe || goldbox || promo || visible)) continue;
    const prelim = preliminaryDecision(settings, deal);
    if (isProbe) {
      prelim.score = Math.max(prelim.score, 87);
      if (!prelim.reasons.includes('amazon_coupon_probe')) prelim.reasons.push('amazon_coupon_probe');
    }
    const result = await repo.upsertCandidate(deal, prelim);
    if (result.new_or_reopened) queued++;
    if (queued >= sourceLimit) break;
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
    /*
     * Direct API only here.
     * Rendered Noon discovery is handled by GitHub
     * Playwright and does not consume CF Browser budget.
     */
    void env;

    const result =
      await fetchNoonSurface(surface); latency = result.latency;
    const deals = parseNoon(result.text, surface); fetched = deals.length;
    queued = await admitNoon(repo, settings, deals);
  } catch (e) { error = `${e instanceof Error ? e.name : 'Error'}:${e instanceof Error ? e.message : String(e)}`; }
  await repo.sourceResult('noon', surface.name, surface.category, fetched, queued, latency, error);
  return { store: 'noon', source: surface.name, fetched, queued, error: Boolean(error) };
}


/*
 * AMAZON_HUNTER_V3_ADAPTIVE
 *
 * Source selection now learns from:
 * - verified / candidate conversion
 * - sent / scan productivity
 * - candidate yield
 * - error rate
 * - recent false Ultra leads
 *
 * Every source keeps an exploration floor so the system
 * never becomes blind to a department that suddenly improves.
 */

type AmazonHealthSnapshot = {
  source:string;
  scans:number;
  fetched:number;
  candidates:number;
  verified:number;
  sent:number;
  errors:number;
  consecutive_errors:number;
  false_ultra:number;
};

function amazonAdaptiveWeight(
  surface:Surface,
  health:
    AmazonHealthSnapshot | undefined,
  ultraMode=false,
):number {

  let weight = 1;

  /*
   * Proven first-party Amazon deal surfaces
   * keep a strong baseline.
   */
  if (surface.name === "goldbox") {
    weight += 3;
  }

  if (surface.name === "limited_time") {
    weight += 2;
  }

  if (surface.name === "clearance") {
    weight += 1;
  }

  /*
   * Ultra discovery still favors searches aimed
   * at the largest discounts.
   */
  if (ultraMode) {
    if (
      surface.name.includes("90")
    ) {
      weight += 2;
    } else if (
      surface.name.includes("75")
      || surface.name.includes("70")
    ) {
      weight += 1;
    }
  }

  /*
   * New / under-sampled sources receive exploration,
   * not punishment.
   */
  if (
    !health
    || health.scans < 3
  ) {
    return Math.max(
      1,
      Math.min(7, weight + 1)
    );
  }

  const candidates =
    Math.max(
      0,
      health.candidates
    );

  const verified =
    Math.max(
      0,
      health.verified
    );

  const scans =
    Math.max(
      1,
      health.scans
    );

  const verifyRate =
    candidates > 0
      ? verified / candidates
      : 0;

  const sentPerScan =
    Math.max(
      0,
      health.sent
    ) / scans;

  const candidatesPerScan =
    candidates / scans;

  const errorRate =
    Math.max(
      0,
      health.errors
    ) / scans;

  /*
   * Verified conversion is the strongest signal.
   */
  if (
    candidates >= 5
    && verifyRate >= 0.65
  ) {
    weight += 3;

  } else if (
    candidates >= 5
    && verifyRate >= 0.40
  ) {
    weight += 2;

  } else if (
    candidates >= 5
    && verifyRate >= 0.25
  ) {
    weight += 1;

  } else if (
    candidates >= 8
    && verifyRate < 0.12
  ) {
    weight -= 2;
  }

  /*
   * Sources that regularly generate sendable deals
   * deserve more search budget.
   */
  if (sentPerScan >= 0.70) {
    weight += 2;
  } else if (sentPerScan >= 0.30) {
    weight += 1;
  }

  /*
   * Productive pages deserve deeper coverage.
   */
  if (candidatesPerScan >= 1.20) {
    weight += 1;
  }

  /*
   * Protection / network errors cool a source down.
   */
  if (
    errorRate >= 0.40
    || health.consecutive_errors >= 3
  ) {
    weight -= 1;
  }

  /*
   * Search sources repeatedly producing fake Ultra
   * references are heavily cooled.
   */
  if (health.false_ultra >= 3) {
    weight -= 2;
  } else if (health.false_ultra >= 1) {
    weight -= 1;
  }

  return Math.max(
    1,
    Math.min(
      7,
      Math.round(weight)
    )
  );
}


function pickAdaptiveAmazonSurface(
  surfaces:Surface[],
  healthRows:
    AmazonHealthSnapshot[],
  cursor:number,
  ultraMode=false,
):Surface | undefined {

  if (!surfaces.length) {
    return undefined;
  }

  const healthMap =
    new Map(
      healthRows.map(
        row => [
          row.source,
          row,
        ]
      )
    );

  const weighted:
    Surface[] = [];

  for (const surface of surfaces) {

    const weight =
      amazonAdaptiveWeight(
        surface,
        healthMap.get(
          surface.name
        ),
        ultraMode,
      );

    for (
      let i=0;
      i<weight;
      i++
    ) {
      weighted.push(surface);
    }
  }

  if (!weighted.length) {
    return surfaces[
      Math.max(0, cursor - 1)
      % surfaces.length
    ];
  }

  return weighted[
    Math.max(0, cursor - 1)
    % weighted.length
  ];
}


function amazonPagedSurface(
  surface:Surface,
  page:number,
):Surface {

  const url =
    new URL(surface.url);

  url.searchParams.set(
    "page",
    String(
      Math.max(2, page)
    ),
  );

  return {
    ...surface,
    url:url.toString(),
  };
}


async function discoveryStep(
  env: V14Env,
  repo: D1Repository,
  settings: Settings,
): Promise<Record<string, unknown>[]> {

  /*
   * AMAZON_DISCOVERY_TIME_CURSOR_V1
   *
   * Discovery must never depend on hot D1 counters.
   * Rotation is derived from wall-clock minute instead.
   */
  const cycle =
    Math.floor(
      Date.now() / 60000
    );

  /*
   * This is observability only.
   * No read-modify-write counter is required anymore.
   */
  await repo.counterSet(
    "cycle_count",
    cycle,
  );

  /*
   * Adaptive history is useful but not allowed to block
   * discovery. If the historical query is slow, continue
   * immediately with neutral weights.
   */
  let amazonHealth:
    AmazonHealthSnapshot[] = [];

  try {

    amazonHealth =
      await Promise.race([
        repo.amazonSourceHealth(),

        new Promise<
          AmazonHealthSnapshot[]
        >(
          resolve =>
            setTimeout(
              () => resolve([]),
              1200,
            )
        ),
      ]);

  } catch (e) {

    console.warn(
      JSON.stringify({
        event:
          "amazon_health_fallback",
        error:
          e instanceof Error
            ? `${e.name}:${e.message}`
            : String(e),
      })
    );

    amazonHealth = [];
  }

  const aCur =
    cycle * 7 + 1;

  const ultraHunterNames =
    new Set<string>([
      ...AMAZON_ULTRA_HUNTER_ORDER,
      ...AMAZON_EXCEPTIONAL_HUNTER_ORDER,
    ]);

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
    pickAdaptiveAmazonSurface(
      amazonRegular,
      amazonHealth,
      aCur,
      false,
    );

  /*
   * Separate Ultra hunter runs every cycle.
   * Its schedule is weighted toward 90% first.
   */
  const ultraCursor =
    cycle * 11 + 3;

  const ultraNames =
    [
      ...new Set(
        AMAZON_ULTRA_HUNTER_ORDER
      )
    ];

  const ultraPool =
    ultraNames
      .map(
        name =>
          AMAZON_SURFACES.find(
            x => x.name === name
          )
      )
      .filter(
        (
          value
        ): value is Surface =>
          Boolean(value)
      );

  const ultraSurface =
    pickAdaptiveAmazonSurface(
      ultraPool,
      amazonHealth,
      ultraCursor,
      true,
    );

  /*
   * Exceptional >=80% hunter has its own cursor.
   * It runs independently from the ordinary 65% Ultra hunt.
   */
  const exceptionalCursor =
    cycle * 13 + 5;

  const exceptionalPool =
    AMAZON_EXCEPTIONAL_HUNTER_ORDER
      .map(
        name =>
          AMAZON_SURFACES.find(
            x => x.name === name
          )
      )
      .filter(
        (
          value
        ): value is Surface =>
          Boolean(value)
      );

  const exceptionalSurface =
    pickAdaptiveAmazonSurface(
      exceptionalPool,
      amazonHealth,
      exceptionalCursor,
      true,
    );

  const tasks:
    Promise<Record<string, unknown>>[] = [];

  /*
   * Priority 1: >=80% exceptional hunt every cycle.
   */
  if (exceptionalSurface) {
    tasks.push(
      scanAmazonSurface(
        repo,
        settings,
        exceptionalSurface,
      ),
    );
  }

  /*
   * Priority 2: 65-79% broad Ultra hunt.
   *
   * It remains active, but the exceptional radar gets
   * the larger share of specialist search resources.
   */
  if (
    cycle % 2 === 0
    &&
    ultraSurface
    &&
    ultraSurface.name !==
      exceptionalSurface?.name
  ) {
    tasks.push(
      scanAmazonSurface(
        repo,
        settings,
        ultraSurface,
      ),
    );
  }

  /*
   * EXCEPTIONAL DEEP SEARCH
   *
   * Search pages only; Goldbox itself is not paginated here.
   *
   * Page 2:
   *   every 2 cycles when the source is at least viable.
   *
   * Page 3:
   *   every 6 cycles only for a source the learning engine
   *   considers productive.
   *
   * Still sequentially verified later by Playwright.
   */
  if (
    exceptionalSurface
    &&
    exceptionalSurface.url.includes("/s?")
  ) {
    const exceptionalHealth =
      amazonHealth.find(
        row =>
          row.source ===
          exceptionalSurface.name
      );

    const exceptionalWeight =
      amazonAdaptiveWeight(
        exceptionalSurface,
        exceptionalHealth,
        true,
      );

    if (
      cycle % 2 === 0
      &&
      exceptionalWeight >= 2
    ) {
      tasks.push(
        scanAmazonSurface(
          repo,
          settings,
          amazonPagedSurface(
            exceptionalSurface,
            2,
          ),
        ),
      );
    }

    if (
      cycle % 6 === 0
      &&
      exceptionalWeight >= 4
    ) {
      tasks.push(
        scanAmazonSurface(
          repo,
          settings,
          amazonPagedSurface(
            exceptionalSurface,
            3,
          ),
        ),
      );
    }
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
   * AMAZON FULL-DEPARTMENT SWEEP
   *
   * One extra category scan every 2 cycles.
   * This gives smaller departments guaranteed coverage.
   */
  if (cycle % 2 === 0) {
    const departmentCursor =
      cycle * 17 + 7;

    const departmentName =
      AMAZON_DEPARTMENT_SWEEP_ORDER[
        (departmentCursor - 1)
        % AMAZON_DEPARTMENT_SWEEP_ORDER.length
      ];

    const departmentSurface =
      AMAZON_SURFACES.find(
        x => x.name === departmentName
      );

    if (
      departmentSurface &&
      departmentSurface.name !== aSurface?.name &&
      departmentSurface.name !== ultraSurface?.name
    ) {
      tasks.push(
        scanAmazonSurface(
          repo,
          settings,
          departmentSurface,
        ),
      );
    }
  }


  /*
   * AMAZON SUPERMARKET / GROCERY SWEEP
   *
   * Food, drinks and household essentials get their
   * own guaranteed rotation every 3 cycles.
   */
  if (cycle % 3 === 0) {
    const supermarketCursor =
      cycle * 19 + 11;

    const supermarketName =
      AMAZON_SUPERMARKET_SWEEP_ORDER[
        (supermarketCursor - 1)
        % AMAZON_SUPERMARKET_SWEEP_ORDER.length
      ];

    const supermarketSurface =
      AMAZON_SURFACES.find(
        x => x.name === supermarketName
      );

    if (
      supermarketSurface &&
      supermarketSurface.name !== aSurface?.name &&
      supermarketSurface.name !== ultraSurface?.name
    ) {
      tasks.push(
        scanAmazonSurface(
          repo,
          settings,
          supermarketSurface,
        ),
      );
    }
  }


  /*
   * AMAZON HUNTER V3 SMART DEPTH
   *
   * Every 4 cycles, a productive adaptive source gets
   * page 2 as well. This expands coverage without
   * aggressive concurrency or blind multi-page crawling.
   */
  if (
    cycle % 4 === 0
    && aSurface
  ) {

    const health =
      amazonHealth.find(
        row =>
          row.source ===
          aSurface.name
      );

    const weight =
      amazonAdaptiveWeight(
        aSurface,
        health,
        false,
      );

    if (weight >= 3) {
      tasks.push(
        scanAmazonSurface(
          repo,
          settings,
          amazonPagedSurface(
            aSurface,
            2,
          ),
        ),
      );
    }
  }



  /*
   * NOON PUBLIC CATALOG DISCOVERY
   *
   * Only public category pages are scanned.
   * Internal API/search endpoints are intentionally
   * excluded because Noon currently blocks them.
   */
  /*
   * Noon rendered discovery is already handled by the
   * dedicated GitHub/V13 transport.
   *
   * Cloudflare discovery is now reserved for Amazon so
   * Noon can never delay or block the Amazon radar.
   */
  const noonPublicSurfaces:
    Surface[] = [];

  if (
    noonPublicSurfaces.length > 0
  ) {
    const noonCursor =
      cycle * 23 + 13;

    const noonSurface =
      noonPublicSurfaces[
        (noonCursor - 1)
        % noonPublicSurfaces.length
      ];

    if (noonSurface) {
      tasks.push(
        scanNoonSurface(
          env,
          repo,
          settings,
          noonSurface,
        ),
      );
    }
  }

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
  /*
   * Fair verification:
   * Amazon Normal and Noon Normal alternate priority.
   * Neither queue can permanently starve the other.
   */
  const verifyCursor =
    await repo.counterAdd(
      "verify_store_cursor",
      1,
    );

  const order:
    Array<['amazon' | 'noon','normal']> =
      verifyCursor % 2 === 0
        ? [
            ['noon','normal'],
            ['amazon','normal'],
          ]
        : [
            ['amazon','normal'],
            ['noon','normal'],
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
   * HYBRID DELIVERY:
   *
   * AMAZON:
   *   Playwright only, so every Amazon review gets
   *   the real Amazon-page screenshot.
   *
   * NOON:
   *   Cloudflare sends verified Normal deals directly
   *   to the isolated Noon review destination.
   */
  const out: Record<string, unknown>[] = [];

  const row =
    await repo.claimNoonForDelivery(
      workerId("deliver-noon"),
      settings.lease_seconds,
    );

  if (!row) return out;

  try {
    await sendReview(
      env,
      row,
      repo,
      settings,
    );

    await repo.markSent(
      row.deal_key
    );

    out.push({
      lane:"normal",
      store:"noon",
      deal:row.deal_key.slice(0,10),
      sent:true,
    });

  } catch (e) {
    const reason =
      `${e instanceof Error ? e.name : 'Error'}:${
        e instanceof Error
          ? e.message
          : String(e)
      }`;

    await repo.deliveryRetry(
      row.deal_key,
      reason,
      settings.retry_base_seconds,
      settings.max_attempts,
    );

    out.push({
      lane:"normal",
      store:"noon",
      deal:row.deal_key.slice(0,10),
      sent:false,
      reason,
    });
  }

  return out;
}


/*
 * V14_INDEPENDENT_DISCOVERY_V2
 *
 * Discovery is intentionally independent from:
 * - stale lease cleanup
 * - verification
 * - Telegram delivery
 * - Queue health
 *
 * Amazon hunting must continue even if any downstream
 * component is slow or temporarily broken.
 */
export async function runDiscoveryOnly(
  env: V14Env,
  settings: Settings,
): Promise<Record<string, unknown>> {

  const repo =
    new D1Repository(
      env.egypt_deals_v14_db
    );

  const started =
    Math.floor(
      Date.now() / 1000
    );

  await repo.counterSet(
    "discovery_started_ts",
    started,
  );

  const discovery =
    await discoveryStep(
      env,
      repo,
      settings,
    );

  const completed =
    Math.floor(
      Date.now() / 1000
    );

  await repo.counterSet(
    "discovery_heartbeat_ts",
    completed,
  );

  const result = {
    event:
      "v14_independent_discovery",
    discovery,
    started,
    completed,
  };

  console.log(
    JSON.stringify(result)
  );

  return result;
}


/*
 * Downstream processing is allowed to fail or retry
 * without ever stopping Amazon discovery.
 */
export async function runProcessingCycle(
  env: V14Env,
  settings: Settings,
): Promise<Record<string, unknown>> {

  const repo =
    new D1Repository(
      env.egypt_deals_v14_db
    );

  let stale = 0;

  try {
    stale =
      await repo.releaseStaleLeases();

  } catch (e) {

    /*
     * Lease cleanup is useful housekeeping,
     * but must never make processing completely dead.
     */
    console.error(
      JSON.stringify({
        event:
          "stale_lease_cleanup_failed",
        error:
          e instanceof Error
            ? `${e.name}:${e.message}`
            : String(e),
      })
    );
  }

  const verified:
    Record<string, unknown>[] = [];

  for (
    let i = 0;
    i < 3;
    i++
  ) {

    const item =
      await verifyOne(
        env,
        repo,
        settings,
      );

    if (!item) {
      break;
    }

    verified.push(item);
  }

  const delivered =
    await deliveryStep(
      env,
      repo,
      settings,
    );

  await repo.counterSet(
    "processing_heartbeat_ts",
    Math.floor(
      Date.now() / 1000
    ),
  );

  const result = {
    event:
      "v14_processing_cycle",
    stale_released:
      stale,
    verified,
    delivered,
  };

  console.log(
    JSON.stringify(result)
  );

  return result;
}


export async function runCycle(env: V14Env, settings: Settings): Promise<Record<string, unknown>> {
  const repo = new D1Repository(env.egypt_deals_v14_db);

  /*
   * V14_CYCLE_HEARTBEAT_V1
   *
   * Lets the Cron watchdog know whether the Queue
   * consumer is actually completing discovery cycles.
   */
  await repo.counterSet(
    "cycle_started_ts",
    Math.floor(Date.now() / 1000),
  );

  const stale = await repo.releaseStaleLeases();
  const discovery = await discoveryStep(env, repo, settings);
  const verified: Record<string, unknown>[] = [];
  for (let i=0;i<3;i++) { const x = await verifyOne(env, repo, settings); if (!x) break; verified.push(x); }
  const delivered = await deliveryStep(env, repo, settings);
  const stats = await repo.stats();
  const result = { event:'v14_cycle', stale_released: stale, discovery, verified, delivered, stats };

  await repo.counterSet(
    "cycle_heartbeat_ts",
    Math.floor(Date.now() / 1000),
  );

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
