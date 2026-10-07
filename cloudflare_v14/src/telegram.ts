import type { DealRow, Settings, V14Env } from "./types";
import type { D1Repository } from "./db";
import { normalChatId, noonReviewChatId, ultraChatId } from "./config";
import { htmlEscape } from "./util";

function readMeta(row: DealRow): Record<string, unknown> {
  try { const x = JSON.parse(row.metadata_json || "{}"); return x && typeof x === "object" ? x : {}; } catch { return {}; }
}

function reviewToken(env: V14Env, row: DealRow): string {
  if (row.store === "noon") return String(env.NOON_REVIEW_BOT_TOKEN || env.TELEGRAM_BOT_TOKEN || "").trim();
  return String(env.TELEGRAM_BOT_TOKEN || "").trim();
}

function reviewChat(env: V14Env, row: DealRow): string {
  if (row.store === "noon") return noonReviewChatId(env);
  return row.lane === "ultra" ? ultraChatId(env) : normalChatId(env);
}

function publicChat(env: V14Env, row: DealRow): string {
  if (row.store === "noon") {
    // Noon can never fall back to an Amazon destination.
    return String(
      env.NOON_CHANNEL_ID ||
      noonReviewChatId(env) ||
      ""
    ).trim();
  }

  return String(
    env.AMAZON_CHANNEL_ID ||
    env.TELEGRAM_CHANNEL_ID ||
    ultraChatId(env) ||
    ""
  ).trim();
}

function caption(row: DealRow): string {
  const isAmazon = row.store === "amazon";
  const store = isAmazon ? "Amazon Egypt" : "Noon Egypt";
  const icon = row.lane === "ultra" ? "🚨" : "🔥";
  const laneAr = row.lane === "ultra" ? "ألترا" : "مراجعة";
  const title = htmlEscape(String(row.title || "منتج بدون اسم").slice(0, 190));
  const current = Number(row.current_price || 0);
  const old = Number(row.old_price || 0);
  const real = Number(row.real_discount || 0);
  const confidence = Number(row.confidence || 0);
  const score = Number(row.score || 0);
  const effective = Number(row.effective_price || current);
  const external = htmlEscape(String(row.external_id || ""));
  const category = htmlEscape(String(row.category || "")).slice(0, 70);
  const lines = [
    `${icon} <b>V14 ${laneAr} • ${store}</b>`, "", `🛒 <b>${title}</b>`, "",
    `💰 <b>السعر الآن:</b> ${current.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})} ج.م`,
  ];
  if (old > current) lines.push(`🏷 <b>السعر السابق:</b> <s>${old.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})}</s> ج.م`);
  if (effective > 0 && effective < current * 0.999) {
    const implied = current ? ((current - effective) / current) * 100 : 0;
    if (implied > 0 && implied <= 60) lines.push(`🎟 <b>بعد الكوبون/العرض:</b> ${effective.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})} ج.م`);
  }
  lines.push(`📉 <b>الخصم الحقيقي:</b> ${real.toFixed(1)}%`, `🧠 <b>التقييم:</b> ${score.toFixed(1)}/100`, `🛡 <b>الثقة:</b> ${(confidence * 100).toFixed(0)}%`);
  if (external) lines.push(`🆔 <b>${isAmazon ? "ASIN" : "SKU"}:</b> <code>${external}</code>`);
  if (category) lines.push(`📂 <b>القسم:</b> ${category}`);
  return lines.join("\n");
}

function keyboard(row: DealRow): Record<string, unknown> {
  const short = row.deal_key.slice(0, 16);
  return { inline_keyboard: [
    [{ text: "🚀 نشر عاجل", callback_data: `v14:u:${short}` }, { text: "✅ نشر عادي", callback_data: `v14:p:${short}` }],
    [{ text: "🔗 فتح المنتج", url: row.url }, { text: "❌ رفض", callback_data: `v14:r:${short}` }],
  ] };
}

async function telegramCall(token: string, method: string, body: Record<string, unknown>): Promise<any> {
  if (!token) throw new Error("telegram_token_missing");
  const r = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  let data: any = {}; try { data = await r.json(); } catch {}
  if (!r.ok || !data?.ok) throw new Error(`telegram_${method}_failed:${String(data?.description || r.status)}`);
  return data.result;
}

async function amazonScreenshot(
  env: V14Env,
  repo: D1Repository,
  settings: Settings,
  row: DealRow,
): Promise<ArrayBuffer | null> {

  if (
    row.store !== "amazon" ||
    row.lane !== "ultra" ||
    !env.BROWSER ||
    !settings.browser_daily_budget_ms
  ) {
    return null;
  }

  const day = new Date().toISOString().slice(0, 10);
  const counterKey = `browser_ms:${day}`;
  const used = await repo.counterGet(counterKey);

  /*
   * Browser budget policy:
   * - normal Amazon screenshots stop at 90%
   * - Ultra may use the reserve until 98%
   *
   * This gives the most important deals the real
   * Amazon-page screenshot first.
   */
  /*
   * Stop screenshots at 92% of the daily Browser budget.
   * The final 8% is reserved for Ultra verification itself.
   */
  const screenshotBudgetRatio = 0.92;

  if (
    used >=
    settings.browser_daily_budget_ms *
      screenshotBudgetRatio
  ) {
    return null;
  }

  try {
    const response: Response =
      await env.BROWSER.quickAction(
        "screenshot",
        {
          url: row.url,

          viewport: {
            width: 1280,
            height: 900,
          },

          gotoOptions: {
            waitUntil: "domcontentloaded",
            timeout: 20000,
          },

          waitForTimeout: 1000,

          setExtraHTTPHeaders: {
            "Accept-Language":
              "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
          },

          userAgent:
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
            "AppleWebKit/537.36 (KHTML, like Gecko) " +
            "Chrome/140.0 Safari/537.36",

          screenshotOptions: {
            fullPage: false,
          },
        },
      );

    const browserMs = Number(
      response.headers.get("X-Browser-Ms-Used") || 0
    );

    if (browserMs > 0) {
      await repo.counterAdd(counterKey, browserMs);
    }

    if (!response.ok) return null;

    const bytes = await response.arrayBuffer();

    // Reject obviously empty/invalid screenshots.
    if (bytes.byteLength < 5000) return null;

    return bytes;

  } catch {
    return null;
  }
}


async function sendPhotoBytes(
  token: string,
  chatId: string,
  bytes: ArrayBuffer,
  cap: string,
  keys: Record<string, unknown>,
): Promise<any> {

  if (!token) {
    throw new Error("telegram_token_missing");
  }

  const form = new FormData();

  form.append("chat_id", chatId);

  form.append(
    "photo",
    new Blob(
      [bytes],
      { type: "image/png" },
    ),
    "amazon-product-page.png",
  );

  form.append(
    "caption",
    cap.slice(0, 1024),
  );

  form.append(
    "parse_mode",
    "HTML",
  );

  form.append(
    "reply_markup",
    JSON.stringify(keys),
  );

  const r = await fetch(
    `https://api.telegram.org/bot${token}/sendPhoto`,
    {
      method: "POST",
      body: form,
    },
  );

  let data: any = {};

  try {
    data = await r.json();
  } catch {}

  if (!r.ok || !data?.ok) {
    throw new Error(
      `telegram_sendPhoto_failed:${
        String(data?.description || r.status)
      }`
    );
  }

  return data.result;
}


export async function sendReview(
  env: V14Env,
  row: DealRow,
  repo: D1Repository,
  settings: Settings,
): Promise<any> {

  /*
   * ABSOLUTE ROUTING POLICY
   *
   * NOON:
   *   normal only
   *
   * AMAZON ULTRA:
   *   Amazon only
   *   verified real discount >=65%
   *   confidence >= configured Ultra threshold
   */
  if (
    row.store === "noon" &&
    row.lane !== "normal"
  ) {
    throw new Error(
      "HARD_ROUTE_BLOCK:noon_ultra_forbidden"
    );
  }

  if (row.lane === "ultra") {
    if (row.store !== "amazon") {
      throw new Error(
        "HARD_ROUTE_BLOCK:ultra_non_amazon"
      );
    }

    if (
      Number(row.real_discount || 0)
        < settings.ultra_min_discount
    ) {
      throw new Error(
        "HARD_ROUTE_BLOCK:amazon_ultra_below_65"
      );
    }

    if (
      Number(row.confidence || 0)
        < settings.min_confidence_ultra
    ) {
      throw new Error(
        "HARD_ROUTE_BLOCK:amazon_ultra_confidence"
      );
    }
  }

  const token = reviewToken(env, row);
  let chatId = reviewChat(env, row);

  if (row.store === "noon" && !chatId) {
    const runtimeNoonChat =
      await repo.counterGet("noon_review_chat_id");

    if (runtimeNoonChat) {
      chatId = String(runtimeNoonChat);
    }
  }

  if (!token) {
    throw new Error(
      row.store === "noon"
        ? "NOON_REVIEW_TOKEN_missing"
        : "TELEGRAM_BOT_TOKEN_missing"
    );
  }

  if (!chatId) {
    throw new Error(
      `telegram_chat_missing:${row.store}:${row.lane}`
    );
  }

  const cap = caption(row);
  const keys = keyboard(row);

  /*
   * AMAZON REVIEW:
   * Prefer a REAL rendered product-page screenshot.
   */
  if (row.store === "amazon") {
    const shot =
      await amazonScreenshot(
        env,
        repo,
        settings,
        row,
      );

    if (shot) {
      try {
        return await sendPhotoBytes(
          token,
          chatId,
          shot,
          cap,
          keys,
        );
      } catch {}
    }
  }

  /*
   * Safe fallback:
   * product image if screenshot is temporarily unavailable.
   */
  const image =
    String(row.image_url || "").trim();

  if (image) {
    try {
      return await telegramCall(
        token,
        "sendPhoto",
        {
          chat_id: chatId,
          photo: image,
          caption: cap.slice(0, 1024),
          parse_mode: "HTML",
          reply_markup: keys,
        },
      );
    } catch {}
  }

  return telegramCall(
    token,
    "sendMessage",
    {
      chat_id: chatId,
      text:
        `${cap}\n\n🔗 ${htmlEscape(row.url)}`,
      parse_mode: "HTML",
      disable_web_page_preview: false,
      reply_markup: keys,
    },
  );
}

export async function sendPublic(
  env: V14Env,
  row: DealRow,
  urgent = false,
  repo?: D1Repository,
): Promise<any> {
  const token = String(env.TELEGRAM_BOT_TOKEN || "").trim();
  let chatId = publicChat(env, row);

  if (row.store === "noon" && !chatId && repo) {
    const runtimeNoonChat =
      await repo.counterGet("noon_review_chat_id");

    if (runtimeNoonChat) {
      chatId = String(runtimeNoonChat);
    }
  }
  if (!token) throw new Error("TELEGRAM_BOT_TOKEN_missing");
  if (!chatId) throw new Error(`telegram_public_chat_missing:${row.store}`);
  const prefix = urgent ? "🚀 <b>نشر عاجل</b>\n\n" : "✅ <b>عرض معتمد</b>\n\n";
  const cap = prefix + caption(row);
  const keys = { inline_keyboard: [[{ text: "🔗 فتح المنتج", url: row.url }]] };
  const image = String(row.image_url || "").trim();
  if (image) {
    try { return await telegramCall(token, "sendPhoto", { chat_id: chatId, photo: image, caption: cap.slice(0,1024), parse_mode: "HTML", reply_markup: keys }); } catch {}
  }
  return telegramCall(token, "sendMessage", { chat_id: chatId, text: `${cap}\n\n🔗 ${htmlEscape(row.url)}`, parse_mode: "HTML", disable_web_page_preview: false, reply_markup: keys });
}

export async function answerCallback(token: string, callbackId: string, text: string, alert = false): Promise<void> {
  await telegramCall(token, "answerCallbackQuery", { callback_query_id: callbackId, text: text.slice(0,190), show_alert: alert });
}

export async function clearButtons(token: string, chatId: string | number, messageId: number): Promise<void> {
  await telegramCall(token, "editMessageReplyMarkup", { chat_id: chatId, message_id: messageId, reply_markup: { inline_keyboard: [] } });
}

export async function setWebhook(token: string, url: string, secret: string): Promise<void> {
  await telegramCall(token, "setWebhook", { url, secret_token: secret, allowed_updates: ["callback_query"], drop_pending_updates: false });
}

export function tokenForWebhook(env: V14Env, route: "main" | "noon"): string {
  return route === "noon" ? String(env.NOON_REVIEW_BOT_TOKEN || env.TELEGRAM_BOT_TOKEN || "").trim() : String(env.TELEGRAM_BOT_TOKEN || "").trim();
}
