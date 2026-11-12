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
export default {async fetch(request,env){
  const u=new URL(request.url),path=u.pathname;
  if(path==='/health')return json({ok:true,service:'talabat-isolated-review',main_v14_untouched:true});
  if(!env.BOT_TOKEN || !env.CHANNEL_ID || !env.DB)return json({ok:false,error:'missing_secret_or_binding'},503);
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
