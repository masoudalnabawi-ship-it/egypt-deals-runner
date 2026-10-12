import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
const src = new URL('../cloudflare/v15-telegram-webhook/src.js',import.meta.url);
const {default:worker,kb} = await import(pathToFileURL(src.pathname));
const env={DB:{},TELEGRAM_BOT_TOKEN:'FAKE',TELEGRAM_WEBHOOK_SECRET:'secret',OWNER_USER_ID:'123',REVIEW_CHAT_ID:'-123',BOT_USER_ID:'456'};
const request=(payload,secret='secret')=>new Request('https://example.test',{method:'POST',headers:{'X-Telegram-Bot-Api-Secret-Token':secret},body:typeof payload==='string'?payload:JSON.stringify(payload)});
test('rejects requests without secret',async()=>assert.equal((await worker.fetch(request({},'bad'),env)).status,403));
test('rejects invalid JSON',async()=>assert.equal((await worker.fetch(request('{'),env)).status,400));
test('rejects oversized payload without Content-Length',async()=>{
 const r=request({padding:'a'.repeat(70000)});r.headers.delete('content-length');
 assert.equal((await worker.fetch(r,env)).status,413);
});
test('rejects missing configuration',async()=>assert.equal((await worker.fetch(request({}),{})).status,503));
test('ignores non-owner callback without database access',async()=>{
 const r=await worker.fetch(request({callback_query:{from:{id:999},message:{chat:{id:-123}}}}),env);
 assert.equal(r.status,200);
});
test('buttons contain only private callback data and Amazon URL',()=>{
 const k=kb('B000000001');const buttons=k.inline_keyboard.flat();
 assert.equal(buttons.filter(b=>b.callback_data).length,4);
 assert.ok(buttons.every(b=>!b.url||b.url==='https://www.amazon.eg/dp/B000000001'));
 assert.throws(()=>kb('invalid'));
});
test('source contains no public channel send or Telegram forward',()=>{
 const s=readFileSync(src,'utf8');
 assert.doesNotMatch(s,/forwardMessage|copyMessage|PUBLIC_CHAT_ID|PUBLIC_CHANNEL_ID/);
});
