import type { JobMessage, V14Env } from './types';
import { getSettings } from './config';
import { D1Repository } from './db';
import { handleTelegramUpdate, runCycle } from './engine';
import { setWebhook } from './telegram';

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
