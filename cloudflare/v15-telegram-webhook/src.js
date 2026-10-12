// V15-only private Telegram review webhook. NEVER posts to public channels.
const ASIN = /^[A-Z0-9]{10}$/;
const actions = new Set(['publish', 'edit', 'wait', 'ignore', 'approve', 'revise']);
const json = (value, status=200) => new Response(JSON.stringify(value), {status, headers:{'content-type':'application/json; charset=utf-8'}});
function config(env) {
  return Boolean(env.DB && env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_WEBHOOK_SECRET && env.OWNER_USER_ID && /^\d+$/.test(env.OWNER_USER_ID) && env.REVIEW_CHAT_ID && /^-?\d+$/.test(env.REVIEW_CHAT_ID));
}
async function telegram(env, method, data) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(data)});
  const body = await r.json();
  if (!r.ok || !body.ok) throw new Error('TELEGRAM_API_ERROR');
  return body.result;
}
const answer = (env,id,text) => telegram(env,'answerCallbackQuery',{callback_query_id:id,text,show_alert:false});
const send = (env,text,extra={}) => telegram(env,'sendMessage',{chat_id:env.REVIEW_CHAT_ID,text,...extra});
function kb(asin) {return {inline_keyboard:[[{text:'🛒 فتح المنتج',url:`https://www.amazon.eg/dp/${asin}`}],[{text:'🚀 طلب نشر (تجريبي)',callback_data:`v15:publish:${asin}`},{text:'✏️ تعديل / رسالة مخصصة',callback_data:`v15:edit:${asin}`}],[{text:'🔍 انتظار التحقق',callback_data:`v15:wait:${asin}`},{text:'❌ تجاهل',callback_data:`v15:ignore:${asin}`}]]};}
async function handleCallback(env, cb) {
  if (String(cb.from?.id)!==env.OWNER_USER_ID || String(cb.message?.chat?.id)!==env.REVIEW_CHAT_ID) return json({ok:true});
  const parts=String(cb.data||'').split(':');
  if (parts.length!==3 || parts[0]!=='v15' || !actions.has(parts[1]) || !ASIN.test(parts[2])) {await answer(env,cb.id,'طلب غير صالح');return json({ok:true});}
  const [,action,asin]=parts;
  // A callback must originate from a bot message with this ASIN, preventing arbitrary forged selections.
  if (!String(cb.message?.text||'').includes(asin)) {await answer(env,cb.id,'رسالة العرض غير متاحة');return json({ok:true});}
  const eventId=String(cb.id);
  const claim=await env.DB.prepare('INSERT OR IGNORE INTO v15_review_events(event_id,asin,action) VALUES(?,?,?)').bind(eventId,asin,action).run();
  if (!claim.meta?.changes) {await answer(env,cb.id,'تم استلام الطلب سابقًا');return json({ok:true});}
  if (action==='edit' || action==='revise') {
    await env.DB.prepare("INSERT INTO v15_review_drafts(asin,status,updated_at) VALUES(?,'editing',CURRENT_TIMESTAMP) ON CONFLICT(asin) DO UPDATE SET status='editing',updated_at=CURRENT_TIMESTAMP").bind(asin).run();
    await answer(env,cb.id,'أرسل نص الرسالة ردًا على هذه الرسالة');
    await send(env,`✏️ تعديل العرض ${asin}\nاكتب الرسالة المخصصة بالرد على هذه الرسالة (Reply). حد أقصى 3000 حرف.`,{reply_markup:{force_reply:true,selective:true}});
  } else if (action==='approve' || action==='publish') {
    await env.DB.prepare("INSERT INTO v15_review_drafts(asin,status,updated_at) VALUES(?,'publish_requested',CURRENT_TIMESTAMP) ON CONFLICT(asin) DO UPDATE SET status='publish_requested',updated_at=CURRENT_TIMESTAMP").bind(asin).run();
    await answer(env,cb.id,'تم تسجيل طلب النشر التجريبي');
    await send(env,`🔒 تم تسجيل طلب نشر ${asin} فقط. النشر العام معطّل.`);
  } else {
    const state=action==='ignore'?'ignored':'waiting';
    await env.DB.prepare('INSERT INTO v15_review_drafts(asin,status,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(asin) DO UPDATE SET status=excluded.status,updated_at=CURRENT_TIMESTAMP').bind(asin,state).run();
    await answer(env,cb.id,state==='ignored'?'تم التجاهل':'بانتظار التحقق');
  }
  return json({ok:true});
}
async function handleMessage(env, msg) {
  if (String(msg.from?.id)!==env.OWNER_USER_ID || String(msg.chat?.id)!==env.REVIEW_CHAT_ID) return json({ok:true});
  const prompt=String(msg.reply_to_message?.text||'');
  const match=prompt.match(/^✏️ تعديل العرض ([A-Z0-9]{10})/);
  if (!match) return json({ok:true});
  const asin=match[1];
  const draft=await env.DB.prepare('SELECT status FROM v15_review_drafts WHERE asin=?').bind(asin).first();
  if (draft?.status!=='editing') return json({ok:true});
  const message=msg.text;
  if (typeof message!=='string' || !message.trim() || message.length>3000 || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(message)) {
    await send(env,'الرسالة غير صالحة؛ اكتب نصًا من 1 إلى 3000 حرف.');return json({ok:true});
  }
  await env.DB.prepare("UPDATE v15_review_drafts SET message=?,status='preview',updated_at=CURRENT_TIMESTAMP WHERE asin=? AND status='editing'").bind(message.trim(),asin).run();
  await send(env,`🔎 معاينة خاصة — ${asin}\n\n${message.trim()}\n\n📦 https://www.amazon.eg/dp/${asin}\n⚠️ السعر والخصم غير مؤكدين؛ راجع صفحة أمازون.\n🔒 لا يوجد نشر عام.`,{reply_markup:{inline_keyboard:[[{text:'✅ اعتماد وطلب نشر تجريبي',callback_data:`v15:approve:${asin}`}],[{text:'🔄 تعديل مرة أخرى',callback_data:`v15:revise:${asin}`}],[{text:'🛒 فتح المنتج',url:`https://www.amazon.eg/dp/${asin}`}]]}});
  return json({ok:true});
}
export default {async fetch(request,env) {
  if (request.method!=='POST') return new Response('Not found',{status:404});
  if (!config(env)) return json({error:'NOT_CONFIGURED'},503);
  if (request.headers.get('X-Telegram-Bot-Api-Secret-Token')!==env.TELEGRAM_WEBHOOK_SECRET) return json({error:'UNAUTHORIZED'},403);
  if (Number(request.headers.get('content-length')||0)>65536) return json({error:'TOO_LARGE'},413);
  let update;try {update=await request.json();} catch {return json({error:'INVALID_JSON'},400);}
  try {if (update.callback_query) return await handleCallback(env,update.callback_query);if (update.message) return await handleMessage(env,update.message);return json({ok:true});}
  catch (e) {console.error('V15_WEBHOOK_FAILED',String(e?.message||e));return json({error:'RETRY'},500);}
}};
export {kb};
