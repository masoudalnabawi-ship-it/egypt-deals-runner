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
      return json({ok:true, stats:await repo.stats(), browser_ms_today:await repo.counterGet(`browser_ms:${new Date().toISOString().slice(0,10)}`)});
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
