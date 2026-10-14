// V16 private review webhook. No public-channel publishing methods.
const ASIN=/^[A-Z0-9]{10}$/;
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json'}});
const validEnv=e=>Boolean(e.DB&&e.TELEGRAM_BOT_TOKEN&&e.TELEGRAM_WEBHOOK_SECRET&&e.REVIEW_CHAT_ID&&e.OWNER_USER_ID&&e.BOT_USER_ID&&e.REGISTRATION_SECRET);
const owner=(e,u,c)=>String(u?.id)===String(e.OWNER_USER_ID)&&String(c?.id)===String(e.REVIEW_CHAT_ID);
const ownBot=(e,m)=>m?.from?.is_bot===true&&String(m?.from?.id)===String(e.BOT_USER_ID);
const product=a=>`https://www.amazon.eg/dp/${a}`;
async function tg(e,method,payload){const r=await fetch(`https://api.telegram.org/bot${e.TELEGRAM_BOT_TOKEN}/${method}`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});const j=await r.json();if(!r.ok||!j.ok)throw Error('TELEGRAM_API_FAILED');return j.result;}
async function ack(e,cb,text){await tg(e,'answerCallbackQuery',{callback_query_id:cb.id,text:text.slice(0,180),show_alert:false});}
async function register(e,req){
 if(req.headers.get('Authorization')!==`Bearer ${e.REGISTRATION_SECRET}`)return json({error:'UNAUTHORIZED'},403);
 const data=await req.json();const asin=data?.asin,mid=data?.message_id;
 if(!ASIN.test(asin)||!Number.isSafeInteger(mid)||mid<1||String(data.chat_id)!==String(e.REVIEW_CHAT_ID))return json({error:'INVALID'},400);
 await e.DB.prepare("INSERT INTO v16_reviews(message_id,asin,chat_id,state) VALUES(?,?,?,'pending') ON CONFLICT(message_id) DO NOTHING").bind(mid,asin,String(data.chat_id)).run();
 const row=await e.DB.prepare('SELECT asin FROM v16_reviews WHERE message_id=?').bind(mid).first();
 return row?.asin===asin?json({ok:true}):json({error:'CONFLICT'},409);
}
// One SQL statement for atomic daily/monthly admission; no free-tier billing guarantees.
async function budget(e,req){
 if(req.headers.get('Authorization')!==`Bearer ${e.REGISTRATION_SECRET}`)return json({error:'UNAUTHORIZED'},403);
 const daily=Number(e.V16_DAILY_RUN_LIMIT||12),monthly=Number(e.V16_MONTHLY_RUN_LIMIT||240);
 if(!Number.isSafeInteger(daily)||daily<1||daily>288||!Number.isSafeInteger(monthly)||monthly<1||monthly>8928)return json({error:'BAD_LIMITS'},503);
 const now=new Date(),day=now.toISOString().slice(0,10),month=day.slice(0,7);
 const rows=await e.DB.prepare(`INSERT INTO v16_run_budget(id,day_key,month_key,daily_used,monthly_used) VALUES(1,?,?,1,1)
 ON CONFLICT(id) DO UPDATE SET day_key=excluded.day_key,month_key=excluded.month_key,
 daily_used=CASE WHEN day_key=excluded.day_key THEN daily_used+1 ELSE 1 END,
 monthly_used=CASE WHEN month_key=excluded.month_key THEN monthly_used+1 ELSE 1 END
 WHERE (CASE WHEN day_key=excluded.day_key THEN daily_used ELSE 0 END) < ?
 AND (CASE WHEN month_key=excluded.month_key THEN monthly_used ELSE 0 END) < ?
 RETURNING daily_used,monthly_used`).bind(day,month,daily,monthly).all();
 const row=rows.results?.[0];
 return json({allowed:!!row,daily_used:row?.daily_used??null,monthly_used:row?.monthly_used??null});
}
async function callback(e,cb){
 const m=cb?.message;
 if(!owner(e,cb?.from,m?.chat)||!ownBot(e,m))return json({ok:true});
 const p=/^v16:(publish|reject|edit|custom):([A-Z0-9]{10})$/.exec(cb.data||'');
 if(!p){await ack(e,cb,'زر غير صالح');return json({ok:true});}
 const [,action,asin]=p;
 const row=await e.DB.prepare('SELECT asin,state FROM v16_reviews WHERE message_id=? AND chat_id=?').bind(m.message_id,String(e.REVIEW_CHAT_ID)).first();
 const buttons=m.reply_markup?.inline_keyboard?.flat()||[];
 if(row?.asin!==asin||!buttons.some(b=>b.callback_data===cb.data)||!buttons.some(b=>b.url===product(asin))){await ack(e,cb,'رسالة غير موثوقة');return json({ok:true});}
 if(action==='publish'){await ack(e,cb,'🔒 النشر العام معطّل');return json({ok:true});}
 if(row.state==='rejected'){await ack(e,cb,'العرض مرفوض بالفعل');return json({ok:true});}
 if(action==='reject'){
  await e.DB.prepare("UPDATE v16_reviews SET state='rejected',prompt_id=NULL WHERE message_id=? AND state!='rejected'").bind(m.message_id).run();
  await ack(e,cb,'❌ تم رفض العرض');return json({ok:true});
 }
 const next=action==='edit'?'editing':'custom';
 // Only accept a reply to the exact prompt sent by this worker.
 const prompt=await tg(e,'sendMessage',{chat_id:e.REVIEW_CHAT_ID,text:`${action==='edit'?'✏️ تعديل':'📝 رسالة مخصصة'} للعرض ${asin}\nرد على هذه الرسالة بالنص الجديد (900 حرف بحد أقصى).`,reply_markup:{force_reply:true,selective:true}});
 await e.DB.prepare("UPDATE v16_reviews SET state=?,prompt_id=? WHERE message_id=? AND state!='rejected'").bind(next,prompt.message_id,m.message_id).run();
 await ack(e,cb,'رد على رسالة التعديل');return json({ok:true});
}
async function message(e,m){
 if(!owner(e,m?.from,m?.chat)||!ownBot(e,m?.reply_to_message))return json({ok:true});
 const promptId=m.reply_to_message?.message_id;
 if(!Number.isSafeInteger(promptId))return json({ok:true});
 const row=await e.DB.prepare("SELECT message_id,asin,state FROM v16_reviews WHERE prompt_id=? AND state IN ('editing','custom')").bind(promptId).first();
 if(!row)return json({ok:true});
 const value=m.text;
 if(typeof value!=='string'||!value.trim()||value.length>900||/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value)){
  await tg(e,'sendMessage',{chat_id:e.REVIEW_CHAT_ID,text:'⚠️ النص غير صالح (1–900 حرف).'});return json({ok:true});
 }
 // Update caption first; if Telegram fails, state remains awaiting edit.
 await tg(e,'editMessageCaption',{chat_id:e.REVIEW_CHAT_ID,message_id:row.message_id,caption:value.trim()+'\n\n🔒 للمراجعة الخاصة — لا نشر تلقائي.'});
 await e.DB.prepare("UPDATE v16_reviews SET state='pending',prompt_id=NULL,custom_text=? WHERE message_id=? AND prompt_id=? AND state IN ('editing','custom')").bind(value.trim(),row.message_id,promptId).run();
 return json({ok:true});
}
async function webhook(e,req){
 if(req.headers.get('X-Telegram-Bot-Api-Secret-Token')!==e.TELEGRAM_WEBHOOK_SECRET)return json({error:'UNAUTHORIZED'},403);
 if(Number(req.headers.get('content-length')||0)>65536)return json({error:'TOO_LARGE'},413);
 const body=await req.text();if(body.length>65536)return json({error:'TOO_LARGE'},413);
 let u;try{u=JSON.parse(body);}catch{return json({error:'INVALID_JSON'},400);}
 if(!Number.isSafeInteger(u?.update_id)||u.update_id<0)return json({error:'INVALID_UPDATE'},400);
 const claim=await e.DB.prepare('INSERT OR IGNORE INTO v16_updates(update_id) VALUES(?)').bind(u.update_id).run();
 if(!claim.meta?.changes)return json({ok:true,duplicate:true});
 try{return u.callback_query?await callback(e,u.callback_query):u.message?await message(e,u.message):json({ok:true});}
 catch(err){await e.DB.prepare('DELETE FROM v16_updates WHERE update_id=?').bind(u.update_id).run();throw err;}
}
export default {async fetch(req,e){
 if(req.method!=='POST')return new Response('Not found',{status:404});
 if(!validEnv(e))return json({error:'NOT_CONFIGURED'},503);
 const path=new URL(req.url).pathname;
 try{if(path==='/budget/claim')return await budget(e,req);if(path==='/register')return await register(e,req);if(path==='/telegram')return await webhook(e,req);return json({error:'NOT_FOUND'},404);}
 catch(err){console.error('V16_WEBHOOK_FAILED',String(err?.message||err));return json({error:'RETRY'},500);}
}};
