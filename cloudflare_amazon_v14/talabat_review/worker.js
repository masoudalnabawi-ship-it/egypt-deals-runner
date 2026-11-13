const REVIEW_CHAT = '-1004375874566';

function json(data, status=200) { return Response.json(data, {status, headers:{'Cache-Control':'no-store'}}); }
function html(body, status=200) { return new Response(body,{status,headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'",'X-Content-Type-Options':'nosniff'}}); }
function esc(s) {return String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function safeEqual(a,b) { a=String(a||''); b=String(b||''); if (!a || a.length!==b.length) return false; let n=0; for(let i=0;i<a.length;i++) n|=a.charCodeAt(i)^b.charCodeAt(i); return n===0; }
function isTalabatUrl(s, product=false) { try {const u=new URL(s); return u.protocol==='https:' && u.hostname==='www.talabat.com' && u.pathname.startsWith('/egypt/') && (!product || u.pathname.includes('/product/'));} catch {return false;} }
async function hexHmac(secret,msg) { const k=await crypto.subtle.importKey('raw',new TextEncoder().encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);const s=await crypto.subtle.sign('HMAC',k,new TextEncoder().encode(msg)); return Array.from(new Uint8Array(s),x=>x.toString(16).padStart(2,'0')).join(''); }
function auth(req,env){return safeEqual(req.headers.get('Authorization'),`Bearer ${env.BOT_TOKEN}`);}
async function telegram(env,method,payload){const r=await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const x=await r.json().catch(()=>({}));if(!r.ok||!x.ok)throw new Error('telegram_'+method+':'+String(x.description||r.status));return x.result;}
function documentPage(label,title,body,submit){return html(`<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(label)}</title><style>body{font-family:system-ui;max-width:470px;margin:9vh auto;padding:22px;line-height:1.8;background:#f7f8fa;color:#1b2936}article{padding:22px;background:white;border-radius:18px;box-shadow:0 2px 16px #0001}h2{margin-top:0}button{border:0;padding:13px 20px;background:#11795d;color:#fff;border-radius:11px;font-weight:700;width:100%;font-size:17px}small{color:#596573} .reject{background:#b33434}</style><article><h2>${esc(label)}</h2><p>${esc(title)}</p><p><small>${esc(body)}</small></p>${submit||''}</article></html>`);}
// GLOBAL_BRANCH_OBSERVATIONS_V2: multiple service areas share one product review.
function money(x){return Number(x).toFixed(2);}
// Keep future and existing private-review cards concise.
function verifiedCaption(rec, locs){
  const last=locs[0]||{};
  // Keep the original photographed branch/price; other prices live behind the button.
  const price=Number(rec.price);
  const discount=Number(rec.discount);
  const area=String(rec.area||last.area||'').slice(0,55);
  const more=locs.length>1?` (+${locs.length-1} فرع)`:'';
  return (`🛒 طلبات مارت | للمراجعة فقط\n📦 ${String(rec.title).slice(0,120)}\n💰 ${money(price)} ج | 🔥 خصم ${discount.toFixed(1)}%\n📍 ${area}${more}\n⚠️ السعر والتوفر والتوصيل حسب منطقتك`).slice(0,550);
}
async function recentLocations(env,key){
  const r=await env.DB.prepare('SELECT branch_id,area,price,discount,checked_at FROM talabat_product_locations WHERE offer_key=? AND checked_at>? ORDER BY checked_at DESC,area LIMIT 80')
    .bind(key,Math.floor(Date.now()/1000)-43200).all();
  return r.results || [];
}
async function signedReviewUrl(env,origin,id,action){
  const expiry=Math.floor(Date.now()/1000)+86400*3;
  const signature=await hexHmac(env.BOT_TOKEN,`${id}|${action}|${expiry}`);
  return `${origin}/review?id=${encodeURIComponent(id)}&action=${action}&exp=${expiry}&sig=${signature}`;
}
export default {async fetch(request,env){
  const u=new URL(request.url),path=u.pathname;
  if(path==='/health')return json({ok:true,service:'talabat-isolated-review',main_v14_untouched:true});
  if(!env.BOT_TOKEN || !env.CHANNEL_ID || !env.DB)return json({ok:false,error:'missing_secret_or_binding'},503);
  if(path==='/status' && request.method==='GET')
    return documentPage('النشر العام متوقف','مراجعة عروض طلبات مارت','لا يتم نشر العروض في القناة قبل إصلاح رابط المنتج والتحقق من صلاحيات مسؤول المراجعة.',null);
  if(path==='/branches' && request.method==='GET') {
    const key=String(u.searchParams.get('key')||'');
    if(!/^[a-f0-9]{32}$/.test(key))return documentPage('رابط غير صالح','','لا توجد بيانات.',null);
    const locations=await recentLocations(env,key);
    const rec=await env.DB.prepare('SELECT title FROM talabat_reviews WHERE id=? LIMIT 1').bind(key).first();
    const title=rec?.title||'الفروع المؤكدة للمنتج';
    const lines=locations.map(x=>`${x.area} — ${money(x.price)} جنيه — خصم ${money(x.discount)}% — آخر فحص ${new Date(Number(x.checked_at)*1000).toLocaleString('ar-EG',{timeZone:'Africa/Cairo'})}`).join(' | ');
    return documentPage('الفروع والأسعار المؤكدة',title,lines||'لا توجد فروع تم التحقق منها خلال آخر 12 ساعة. السعر والتوصيل النهائي غير مضمونين.',null);
  }
  if(path==='/observe' && request.method==='POST') {
    if(!auth(request,env))return json({ok:false,error:'unauthorized'},401);
    const o=await request.json().catch(()=>null);
    if(!o)return json({ok:false,error:'invalid_body'},400);
    const key=String(o.key||''),branch=String(o.branch_id||'');
    const now=Math.floor(Date.now()/1000);
    if(!/^[a-f0-9]{32}$/.test(key)||!/^[0-9]{3,10}$/.test(branch)||
       !o.title||!o.sku||!o.area||!isTalabatUrl(o.source_url)||
       !(Number(o.price)>0)||!(Number(o.stock)>0)||!(Number(o.discount)>=40)||
       Math.abs(now-Number(o.checked_at))>900)
      return json({ok:false,error:'invalid_or_stale_observation'},400);
    const prev=await env.DB.prepare('SELECT price,discount,area FROM talabat_product_locations WHERE offer_key=? AND branch_id=?').bind(key,branch).first();
    await env.DB.prepare('INSERT INTO talabat_product_locations(offer_key,branch_id,area,sku,title,price,discount,checked_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(offer_key,branch_id) DO UPDATE SET area=excluded.area,sku=excluded.sku,title=excluded.title,price=excluded.price,discount=excluded.discount,checked_at=excluded.checked_at')
      .bind(key,branch,String(o.area).slice(0,110),String(o.sku).slice(0,90),String(o.title).slice(0,400),Number(o.price),Number(o.discount),now).run();
    const locations=await recentLocations(env,key);
    const rec=await env.DB.prepare('SELECT id,title,status,review_message_id,product_url,price,discount,area FROM talabat_reviews WHERE review_message_id IS NOT NULL AND (id=? OR lower(title)=lower(?)) ORDER BY created_at ASC LIMIT 1')
      .bind(key,String(o.title)).first();
    const changed=!prev||Number(prev.price)!==Number(o.price)||Number(prev.discount)!==Number(o.discount)||prev.area!==String(o.area);
    if(rec && rec.status==='pending') {
      // Refresh older long cards too, even when the price has not changed.
      // Telegram returns 400 for a no-op edit; ignore that specific condition.
      const editPrivate=async(method,payload)=>{
        try { await telegram(env,method,payload); }
        catch(error) {if(!String(error).includes('message is not modified'))throw error;}
      };
      try {
        await editPrivate('editMessageCaption',{chat_id:REVIEW_CHAT,
          message_id:rec.review_message_id,caption:verifiedCaption(rec,locations)});
        const rejectUrl=await signedReviewUrl(env,u.origin,rec.id,'reject');
        const buttons=[];
        if(isTalabatUrl(rec.product_url,true))
          buttons.push([{text:'🛒 فتح المنتج',url:rec.product_url}]);
        buttons.push([{text:'📍 الفروع والأسعار',url:u.origin+'/branches?key='+key},
          {text:'❌ رفض العرض',url:rejectUrl}]);
        await editPrivate('editMessageReplyMarkup',{chat_id:REVIEW_CHAT,
          message_id:rec.review_message_id,reply_markup:{inline_keyboard:buttons}});
      } catch(error) { console.error('BRANCH_CAPTION_UPDATE_FAILED',key,String(error)); }
    }
    return json({ok:true,seen:!!rec,review_status:rec?.status||null,
      branches:locations.map(x=>({area:x.area,branch_id:x.branch_id,price:x.price,discount:x.discount,checked_at:x.checked_at})),
      updated:changed});
  }
  // PRICE_HISTORY_API_V1: bot-authenticated snapshots of OBSERVED prices only.
  // Hourly upsert prevents the five-minute scanner from creating duplicate rows.
  if(path==='/price-history/ingest' && request.method==='POST') {
    if(!auth(request,env))return json({ok:false,error:'unauthorized'},401);
    const data=await request.json().catch(()=>null);
    if(!data||!Array.isArray(data.rows)||data.rows.length<1||data.rows.length>70)
      return json({ok:false,error:'invalid_batch'},400);
    const now=Math.floor(Date.now()/1000);
    const stmts=[];
    for(const row of data.rows){
      const branch=String(row?.branch_id||''),sku=String(row?.sku||'');
      const price=Number(row?.price),reported=Number(row?.displayed_original_price);
      const stamp=Number(row?.observed_at);
      if(!/^[0-9]{3,10}$/.test(branch)||!/^[A-Za-z0-9_-]{1,90}$/.test(sku)||
         !Number.isFinite(price)||price<=0||price>1000000||
         !Number.isSafeInteger(stamp)||stamp>now+300||stamp<now-14400)
        return json({ok:false,error:'invalid_observation'},422);
      const bucket=Math.floor(stamp/3600)*3600;
      const original=Number.isFinite(reported)&&reported>0&&reported<1000000?reported:null;
      stmts.push(env.DB.prepare(`INSERT INTO talabat_price_history
        (branch_id,sku,hour_bucket,price,displayed_original_price,observed_at,title)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(branch_id,sku,hour_bucket) DO UPDATE SET
        price=excluded.price,displayed_original_price=excluded.displayed_original_price,
        observed_at=excluded.observed_at,title=excluded.title`)
        .bind(branch,sku,bucket,price,original,stamp,String(row.title||'').slice(0,200)));
    }
    await env.DB.batch(stmts);
    return json({ok:true,accepted:stmts.length});
  }
  if(path==='/price-history/evidence' && request.method==='POST') {
    if(!auth(request,env))return json({ok:false,error:'unauthorized'},401);
    const data=await request.json().catch(()=>null);
    const branch=String(data?.branch_id||''),sku=String(data?.sku||'');
    const current=Number(data?.price),advertised=Number(data?.advertised_discount);
    if(!/^[0-9]{3,10}$/.test(branch)||!/^[A-Za-z0-9_-]{1,90}$/.test(sku)||
       !Number.isFinite(current)||current<=0||current>1000000)
      return json({ok:false,error:'invalid_evidence_request'},400);
    const now=Math.floor(Date.now()/1000);
    // Exclude the current 24h; today's sale price cannot prove a prior baseline.
    const q=await env.DB.prepare(`SELECT price,observed_at FROM talabat_price_history
      WHERE branch_id=? AND sku=? AND observed_at>=? AND observed_at<?
      ORDER BY observed_at DESC LIMIT 1000`)
      .bind(branch,sku,now-31*86400,now-86400).all();
    const rows=(q.results||[]).filter(x=>Number(x.price)>0);
    const days=new Set(rows.map(x=>Math.floor(Number(x.observed_at)/86400)));
    const span=rows.length?Math.max(...rows.map(x=>Number(x.observed_at)))-Math.min(...rows.map(x=>Number(x.observed_at))):0;
    const med=(values)=>{
      const a=values.sort((x,y)=>x-y),n=a.length;
      return n ? (a[Math.floor((n-1)/2)]+a[Math.floor(n/2)])/2 : null;
    };
    const baseline=med(rows.map(x=>Number(x.price)));
    const coverage=days.size;
    let status='insufficient_history';
    let observedSavings=null;
    if(baseline!==null){
      observedSavings=Math.round((1-current/baseline)*1000)/10;
      if(coverage>=3 && span>=6*86400){
        if(observedSavings>=20) status='historically_supported';
        else if(observedSavings<10 && Number.isFinite(advertised)&&advertised>=40)
          status='advertised_discount_not_supported';
        else status='mixed_price_history';
      }
    }
    return json({ok:true,status,baseline:baseline===null?null:Math.round(baseline*100)/100,
      observed_savings_percent:observedSavings,history_days:coverage,
      earliest_observation:rows.length?Math.min(...rows.map(x=>Number(x.observed_at))):null,
      note:'Only observed prices for this SKU and branch; no third-party market comparison.'});
  }
  // Authenticated repair of already-sent PRIVATE review cards. No publishing.
  if(path==='/repair-review-buttons' && request.method==='POST') {
    if(!auth(request,env))return json({ok:false,error:'unauthorized'},401);
    const offset=Math.max(0,Math.min(240,Number(u.searchParams.get('offset')||0)||0));
    const q=await env.DB.prepare(`SELECT id,title,price,discount,area,product_url,review_message_id
      FROM talabat_reviews WHERE status='pending' AND review_message_id IS NOT NULL
      ORDER BY created_at DESC LIMIT 12 OFFSET ?`).bind(Math.floor(offset)).all();
    let updated=0,failed=0,skipped=0;
    for(const rec of (q.results||[])) {
      if(!isTalabatUrl(rec.product_url,true)){skipped++;continue;}
      // Conservative pacing to avoid Telegram flood limits.
      await new Promise(resolve=>setTimeout(resolve,1100));
      const rejectUrl=await signedReviewUrl(env,u.origin,rec.id,'reject');
      const markup={inline_keyboard:[
        [{text:'🛒 فتح المنتج',url:rec.product_url}],
        [{text:'📍 الفروع والأسعار',url:u.origin+'/branches?key='+rec.id},
         {text:'❌ رفض العرض',url:rejectUrl}]
      ]};
      try {
        const locs=await recentLocations(env,rec.id);
        try { await telegram(env,'editMessageCaption',{chat_id:REVIEW_CHAT,
          message_id:rec.review_message_id,caption:verifiedCaption(rec,locs)}); }
        catch(err) { if(!String(err).includes('message is not modified'))
          console.error('CAPTION_REPAIR_FAILED',rec.id,String(err)); }
        await telegram(env,'editMessageReplyMarkup',{chat_id:REVIEW_CHAT,
          message_id:rec.review_message_id,reply_markup:markup});
        updated++;
      } catch(err) {
        if(String(err).includes('message is not modified'))updated++;
        else {failed++;console.error('BUTTON_REPAIR_FAILED',rec.id,String(err));}
      }
    }
    return json({ok:true,updated,failed,skipped,limit:12,offset});
  }
  if(path==='/seen' && request.method==='POST') {
    if(!auth(request,env))return json({ok:false,error:'unauthorized'},401);
    const o=await request.json().catch(()=>null);
    const id=String(o?.id||'');
    if(!/^[a-z0-9_-]{12,90}$/i.test(id))return json({ok:false,error:'invalid_id'},400);
    const rec=await env.DB.prepare('SELECT status FROM talabat_reviews WHERE id=?').bind(id).first();
    return json({ok:true,seen:!!rec,status:rec?.status||null});
  }
  if(path==='/reserve' && request.method==='POST') {
    if(!auth(request,env))return json({ok:false,error:'unauthorized'},401);
    const o=await request.json().catch(()=>null);if(!o)return json({ok:false,error:'bad_json'},400);
    const {id,title,area,sku,price,discount,product_url,source_url,proof_at}=o;
    if(!/^[a-z0-9_-]{12,90}$/i.test(String(id)) || !title || !sku || !(Number(price)>0) || !(Number(discount)>=40) || !isTalabatUrl(source_url) || !isTalabatUrl(product_url,true))return json({ok:false,error:'invalid_offer'},400);
    if(Math.abs(Date.now()/1000-Number(proof_at))>900)return json({ok:false,error:'stale_proof'},422);
    const q=await env.DB.prepare(`INSERT OR IGNORE INTO talabat_reviews(id,status,title,area,sku,price,discount,product_url,source_url,proof_at,created_at) VALUES(?,'reserved',?,?,?,?,?,?,?,?,?)`)
      .bind(id,String(title).slice(0,400),String(area).slice(0,80),String(sku).slice(0,90),Number(price),Number(discount),String(product_url),String(source_url),Number(proof_at),Math.floor(Date.now()/1000)).run();
    return json({ok:true,reserved:!!q.meta.changes,id});
  }
  if(path==='/attach' && request.method==='POST') {
    if(!auth(request,env))return json({ok:false,error:'unauthorized'},401);
    const o=await request.json().catch(()=>null);if(!o||!/^\d+$/.test(String(o.message_id))||!/^[a-z0-9_-]{12,90}$/i.test(String(o.id)))return json({ok:false,error:'bad_input'},400);
    const q=await env.DB.prepare(`UPDATE talabat_reviews SET status='pending',review_message_id=? WHERE id=? AND status='reserved'`)
      .bind(Number(o.message_id),String(o.id)).run();
    if(!q.meta.changes)return json({ok:false,error:'not_reserved_or_duplicate'},409);
    const expiry=Math.floor(Date.now()/1000)+86400*3;
    const sign=async action=>{const msg=`${o.id}|${action}|${expiry}`;const signature=await hexHmac(env.BOT_TOKEN,msg);return `${u.origin}/review?id=${encodeURIComponent(o.id)}&action=${action}&exp=${expiry}&sig=${signature}`;};
    return json({ok:true,publish_url:await sign('publish'),reject_url:await sign('reject')});
  }
  if(path==='/review' && (request.method==='GET'||request.method==='POST')) {
    const data=request.method==='GET'?u.searchParams:await request.formData();
    const id=String(data.get('id')||''), action=String(data.get('action')||''),exp=Number(data.get('exp')||0),sig=String(data.get('sig')||'');
    if(!/^[a-z0-9_-]{12,90}$/i.test(id)||!['publish','reject'].includes(action)||exp<Math.floor(Date.now()/1000)||exp>Date.now()/1000+86400*4||!safeEqual(sig,await hexHmac(env.BOT_TOKEN,`${id}|${action}|${exp}`)))return documentPage('رابط غير صالح','انتهت صلاحية الزر أو الرابط غير صحيح','لا يتم نشر أي شيء.',null);
    const rec=await env.DB.prepare('SELECT * FROM talabat_reviews WHERE id=?').bind(id).first();
    if(!rec)return documentPage('العرض غير موجود','لم نعثر على هذا العرض','لا يوجد إجراء.',null);
    if(rec.status!=='pending')return documentPage('تمت معالجة العرض',rec.title,`الحالة الحالية: ${rec.status}`,null);
    if(action==='publish')return documentPage('النشر العام متوقف',rec.title,'لا يمكن نشر العرض قبل توثيق رابط المنتج وتأمين هوية المسؤول.',null);
    if(request.method==='GET') {
      const fields=[['id',id],['action',action],['exp',String(exp)],['sig',sig]].map(([k,v])=>`<input type="hidden" name="${k}" value="${esc(v)}">`).join('');
      const form=`<form method="post" action="/review">${fields}<button class="${action==='reject'?'reject':''}" type="submit">${action==='publish'?'تأكيد النشر لقناة أمازون':'تأكيد رفض العرض'}</button></form>`;
      return documentPage(action==='publish'?'موافقة نشر طلبات مارت':'رفض عرض طلبات مارت',rec.title,`${rec.area} • ${rec.price} جنيه • خصم ${rec.discount}% • التوصيل والسعر النهائي غير مؤكدين`,form);
    }
    if(action==='publish')
      return documentPage('النشر متوقف مؤقتا',
        rec.title,
        'رابط المنتج غير صالح داخل التطبيق. لن يتم النشر حتى إصلاح الرابط وتأمين الموافقة.',
        null);
    const next=action==='reject'?'rejected':'publishing';
    const q=await env.DB.prepare('UPDATE talabat_reviews SET status=? WHERE id=? AND status=\'pending\'').bind(next,id).run();
    if(!q.meta.changes)return documentPage('تمت المعالجة',rec.title,'سبق التعامل مع العرض.',null);
    if(action==='reject') {
      try{await telegram(env,'editMessageReplyMarkup',{chat_id:REVIEW_CHAT,message_id:rec.review_message_id,reply_markup:{inline_keyboard:[]}});}catch{}
      return documentPage('تم رفض العرض',rec.title,'لن يُنشر في القناة.',null);
    }
    const caption=`🛒 طلبات مارت | ${rec.area}\n📦 ${rec.title}\n💰 ${rec.price} جنيه | 🔥 ${rec.discount}%\n📸 صورة حقيقية من الموقع وقت الفحص\n⚠️ راجع التوفر والسعر النهائي عند الدفع\n🛒 رابط المنتج على الموقع:\n${rec.product_url}`.slice(0,1010);
    try {
      await telegram(env,'copyMessage',{chat_id:env.CHANNEL_ID,from_chat_id:REVIEW_CHAT,message_id:rec.review_message_id,caption,reply_markup:{inline_keyboard:[[{text:'🛒 فتح صفحة المنتج',url:rec.product_url}]]}});
      await env.DB.prepare('UPDATE talabat_reviews SET status=\'published\',published_at=? WHERE id=? AND status=\'publishing\'').bind(Math.floor(Date.now()/1000),id).run();
      try{await telegram(env,'editMessageReplyMarkup',{chat_id:REVIEW_CHAT,message_id:rec.review_message_id,reply_markup:{inline_keyboard:[]}});}catch{}
      return documentPage('تم نشر العرض',rec.title,'تم النشر على قناة أمازون الحالية.',null);
    }catch(e){
      console.error('TALABAT_PUBLICATION_UNCERTAIN',id,String(e));
      return documentPage('نتيجة النشر غير مؤكدة',rec.title,'افحص قناة أمازون أولًا. لن نعيد المحاولة تلقائيًا لمنع التكرار.',null);
    }
  }
  return json({ok:false,error:'not_found'},404);
}};
