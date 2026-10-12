// V15 private owner-review webhook. NO public-channel publishing capability.
const ASIN = /^[A-Z0-9]{10}$/;
const ACTIONS = new Set(['publish', 'edit', 'wait', 'ignore', 'approve', 'revise']);
const LIMIT = 65536;
const json = (v, status=200) => new Response(JSON.stringify(v), {status, headers:{'content-type':'application/json; charset=utf-8'}});
const digits = v => typeof v === 'string' && /^\d+$/.test(v);
const chatId = v => typeof v === 'string' && /^-?\d+$/.test(v);
function configured(env) {
  return Boolean(env.DB && env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_WEBHOOK_SECRET &&
    digits(env.OWNER_USER_ID) && chatId(env.REVIEW_CHAT_ID) && digits(env.BOT_USER_ID));
}
async function telegram(env, method, payload) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(payload)
  });
  const data = await r.json();
  if (!r.ok || !data.ok) throw Error('TELEGRAM_API_ERROR');
  return data.result;
}
const answer = (env, id, text) => telegram(env, 'answerCallbackQuery', {callback_query_id:id, text, show_alert:false});
const send = (env, text, extra={}) => telegram(env, 'sendMessage', {chat_id:env.REVIEW_CHAT_ID, text, ...extra});
const product = asin => `https://www.amazon.eg/dp/${asin}`;
function kb(asin) {
  if (!ASIN.test(asin)) throw Error('INVALID_ASIN');
  return {inline_keyboard:[
    [{text:'🛒 فتح المنتج', url:product(asin)}],
    [{text:'🚀 طلب نشر (تجريبي)',callback_data:`v15:publish:${asin}`},{text:'✏️ تعديل / رسالة مخصصة',callback_data:`v15:edit:${asin}`}],
    [{text:'🔍 انتظار التحقق',callback_data:`v15:wait:${asin}`},{text:'❌ تجاهل',callback_data:`v15:ignore:${asin}`}]
  ]};
}
const isOwner = (env, from, chat) => String(from?.id)===env.OWNER_USER_ID && String(chat?.id)===env.REVIEW_CHAT_ID;
const isBot = (env, from) => from?.is_bot===true && String(from?.id)===env.BOT_USER_ID;
function callbackValid(env, cb, action, asin) {
  const msg = cb.message;
  return isOwner(env, cb.from, msg?.chat) && isBot(env, msg?.from) &&
    Number.isSafeInteger(msg?.message_id) && String(msg?.text||'').includes(asin) &&
    msg?.reply_markup?.inline_keyboard?.some(row => row.some(button => button.callback_data===`v15:${action}:${asin}`));
}
async function status(env, asin) {
  return env.DB.prepare('SELECT status FROM v15_review_drafts WHERE asin=?').bind(asin).first();
}
async function transition(env, asin, next, allowed) {
  // A conditional UPDATE is atomic; stale buttons cannot overwrite terminal states.
  const placeholders = allowed.map(()=>'?').join(',');
  const update = await env.DB.prepare(`UPDATE v15_review_drafts SET status=?, updated_at=CURRENT_TIMESTAMP WHERE asin=? AND status IN (${placeholders})`)
    .bind(next, asin, ...allowed).run();
  if (update.meta?.changes) return true;
  if (await status(env,asin)) return false;
  // Only first-time review messages can create a draft; terminal state is never reset.
  const insert = await env.DB.prepare('INSERT OR IGNORE INTO v15_review_drafts(asin,status) VALUES(?,?)').bind(asin,next).run();
  return Boolean(insert.meta?.changes);
}
async function handleCallback(env, cb) {
  if (!isOwner(env,cb.from,cb.message?.chat)) return json({ok:true});
  const parts=String(cb.data||'').split(':');
  if (parts.length!==3 || parts[0]!=='v15' || !ACTIONS.has(parts[1]) || !ASIN.test(parts[2])) {
    await answer(env,cb.id,'طلب غير صالح'); return json({ok:true});
  }
  const [,action,asin]=parts;
  if (!callbackValid(env,cb,action,asin)) {await answer(env,cb.id,'زر غير موثوق'); return json({ok:true});}
  if (action==='approve' || action==='revise') {
    const draft=await env.DB.prepare('SELECT status,preview_message_id FROM v15_review_drafts WHERE asin=?').bind(asin).first();
    if (draft?.status!=='preview' || draft.preview_message_id!==cb.message.message_id) {
      await answer(env,cb.id,'المعاينة قديمة');return json({ok:true});
    }
  }
  // Conditional state transitions reject stale buttons.
  if (action==='edit' || action==='revise') {
    const allowed = action==='revise' ? ['preview'] : ['waiting','new'];
    const changed = await transition(env,asin,'editing_pending',allowed);
    if (!changed) {await answer(env,cb.id,'حالة العرض لا تسمح بالتعديل');return json({ok:true});}
    // If Telegram fails, keep editing_pending and do not accept arbitrary reply text.
    let prompt;
    try {
      prompt = await send(env,`✏️ تعديل العرض ${asin}\nاكتب الرسالة المخصصة بالرد على هذه الرسالة (Reply). حد أقصى 3000 حرف.`,{reply_markup:{force_reply:true,selective:true}});
    } catch (e) {
      await env.DB.prepare("UPDATE v15_review_drafts SET status='waiting' WHERE asin=? AND status='editing_pending'").bind(asin).run();
      throw e;
    }
    await env.DB.prepare("UPDATE v15_review_drafts SET status='editing',edit_prompt_message_id=?,updated_at=CURRENT_TIMESTAMP WHERE asin=? AND status='editing_pending'")
      .bind(prompt.message_id,asin).run();
    await answer(env,cb.id,'أرسل النص ردًا على رسالة التعديل');
  } else {
    const next = action==='ignore'?'ignored':action==='wait'?'waiting':'publish_requested';
    const allowed = action==='approve'?['preview']:action==='publish'?['waiting','new']:['waiting','new','editing','preview'];
    const changed = await transition(env,asin,next,allowed);
    await answer(env,cb.id,changed?(next==='publish_requested'?'تم تسجيل طلب تجريبي فقط':next==='ignored'?'تم التجاهل':'بانتظار التحقق'):'الزر قديم أو تم تنفيذ الإجراء');
    // No public destination, no public Telegram send method, no channel IDs.
  }
  return json({ok:true});
}
async function handleMessage(env,msg) {
  if (!isOwner(env,msg.from,msg.chat) || !isBot(env,msg.reply_to_message?.from)) return json({ok:true});
  const match=String(msg.reply_to_message?.text||'').match(/^✏️ تعديل العرض ([A-Z0-9]{10})\n/);
  if (!match || !Number.isSafeInteger(msg.message_id)) return json({ok:true});
  const asin=match[1];
  const draft=await env.DB.prepare('SELECT status,edit_prompt_message_id FROM v15_review_drafts WHERE asin=?').bind(asin).first();
  if (draft?.status!=='editing' || !Number.isSafeInteger(draft.edit_prompt_message_id) ||
      draft.edit_prompt_message_id!==msg.reply_to_message?.message_id) return json({ok:true});
  const message=msg.text;
  if (typeof message!=='string' || !message.trim() || message.length>3000 || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(message)) {
    await send(env,'الرسالة غير صالحة؛ اكتب نصًا من 1 إلى 3000 حرف.');return json({ok:true});
  }
  // Conditional transition means duplicate deliveries and competing replies cannot both win.
  const result=await env.DB.prepare("UPDATE v15_review_drafts SET message=?,status='preview_pending',updated_at=CURRENT_TIMESTAMP WHERE asin=? AND status='editing' AND edit_prompt_message_id=?")
    .bind(message.trim(),asin,msg.reply_to_message.message_id).run();
  if (!result.meta?.changes) return json({ok:true});
  await env.DB.prepare('INSERT OR IGNORE INTO v15_review_messages(chat_id,message_id,asin) VALUES(?,?,?)')
    .bind(String(msg.chat.id),msg.message_id,asin).run();
  // Telegram send can succeed while acknowledgement fails; duplicates are bounded by state.
  let preview;
  try {preview=await send(env,`🔎 معاينة خاصة — ${asin}\n\n${message.trim()}\n\n📦 ${product(asin)}\n⚠️ السعر والخصم غير مؤكدين؛ راجع صفحة أمازون.\n🔒 لا يوجد نشر عام.`,{
    reply_markup:{inline_keyboard:[
      [{text:'✅ اعتماد وطلب نشر تجريبي',callback_data:`v15:approve:${asin}`}],
      [{text:'🔄 تعديل مرة أخرى',callback_data:`v15:revise:${asin}`}],
      [{text:'🛒 فتح المنتج',url:product(asin)}]
    ]}
  });} catch(e) {
    await env.DB.prepare("UPDATE v15_review_drafts SET status='editing' WHERE asin=? AND status='preview_pending'").bind(asin).run();
    throw e;
  }
  await env.DB.prepare("UPDATE v15_review_drafts SET status='preview',preview_message_id=?,updated_at=CURRENT_TIMESTAMP WHERE asin=? AND status='preview_pending'")
    .bind(preview.message_id,asin).run();
  return json({ok:true});
}
async function handleOwnerCommand(env, msg) {
  if (!isOwner(env, msg.from, msg.chat)) return null;

  const command = String(msg.text || '').trim().split(/\s+/)[0]
    .split('@')[0].toLowerCase();

  if (command === '/start') {
    await send(env,
      '🤖 أهلاً بيك في Egypt Deal Hunter V15!\n\n' +
      '🔎 البوت جاهز لمراجعة عروض أمازون مصر.\n\n' +
      '📊 /status — حالة النظام\n' +
      '🛒 /deals — العروض المنتظرة للمراجعة\n\n' +
      '🔒 النشر العام معطّل.');
    return json({ok:true});
  }

  if (command === '/status') {
    await send(env,
      '✅ بوت V15 متصل ويستقبل الأوامر.\n' +
      '🔐 المراجعة خاصة بالمالك.\n' +
      '🔒 النشر العام معطّل.\n' +
      'ℹ️ هذا لا يؤكد تشغيل اكتشاف العروض تلقائيًا.');
    return json({ok:true});
  }

  if (command === '/deals') {
    const result = await env.DB.prepare(
      "SELECT asin,status FROM v15_review_drafts " +
      "WHERE status NOT IN ('ignored','publish_requested') " +
      "ORDER BY updated_at DESC LIMIT 10"
    ).all();

    const rows = result.results || [];

    const text = rows.length
      ? '🛒 عروض المراجعة:\n\n' +
        rows.map(r => `${r.asin} — ${r.status}`).join('\n')
      : '📭 لا توجد عروض مسجلة للمراجعة حاليًا.';

    await send(env, text);
    return json({ok:true});
  }

  return null;
}

async function limitedJson(request) {
  const reader=request.body?.getReader();
  if (!reader) throw Error('INVALID_JSON');
  const chunks=[];let size=0;
  try {
    for (;;) {
      const {done,value}=await reader.read();
      if (done) break;
      size+=value.byteLength;
      if (size>LIMIT) {await reader.cancel().catch(()=>{});throw Error('TOO_LARGE');}
      chunks.push(value);
    }
  } finally {reader.releaseLock();}
  const bytes=new Uint8Array(size);let offset=0;
  for (const chunk of chunks) {bytes.set(chunk,offset);offset+=chunk.byteLength;}
  const update=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
  if (!update || typeof update!=='object' || Array.isArray(update)) throw Error('INVALID_JSON');
  return update;
}
export default {async fetch(request,env) {
  if (request.method!=='POST') return new Response('Not found',{status:404});
  if (!configured(env)) return json({error:'NOT_CONFIGURED'},503);
  if (request.headers.get('X-Telegram-Bot-Api-Secret-Token')!==env.TELEGRAM_WEBHOOK_SECRET) return json({error:'UNAUTHORIZED'},403);
  if (Number(request.headers.get('content-length')||0)>LIMIT) return json({error:'TOO_LARGE'},413);
  let update;
  try {update=await limitedJson(request);} catch(e) {return json({error:e.message==='TOO_LARGE'?'TOO_LARGE':'INVALID_JSON'},e.message==='TOO_LARGE'?413:400);}
  try {
    if (update.callback_query) return await handleCallback(env,update.callback_query);
    if (update.message) {
      const commandResponse = await handleOwnerCommand(env, update.message);
      if (commandResponse) return commandResponse;
      return await handleMessage(env, update.message);
    }
    return json({ok:true});
  } catch(e) {console.error('V15_WEBHOOK_FAILED',String(e?.message||e));return json({error:'RETRY'},500);}
}};
export {kb};
