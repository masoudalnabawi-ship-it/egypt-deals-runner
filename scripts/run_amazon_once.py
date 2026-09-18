import asyncio
import json
import os
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "amazon_dynamic_runtime_v8" / "telegram_deals_bot_v1_ready"
REVIEW_DIR = Path(__file__).resolve().parents[1] / "amazon_dynamic_runtime_v8" / "amazon_deals_bot_ready"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

def _capture_in_subprocess(url, key="product"):
    code = r"""
import json, sys
from amazon_page_capture import capture_amazon_page
print(json.dumps(capture_amazon_page(sys.argv[1], sys.argv[2]), ensure_ascii=False))
"""
    try:
        cp = subprocess.run(
            [sys.executable, "-c", code, str(url), str(key)],
            cwd=str(REVIEW_DIR),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=50,
        )
        if cp.returncode != 0:
            return {"ok": False, "reason": cp.stderr[-300:]}
        lines = [x for x in cp.stdout.splitlines() if x.strip()]
        return json.loads(lines[-1]) if lines else {"ok": False}
    except Exception as exc:
        return {"ok": False, "reason": repr(exc)}

_bridge = types.ModuleType("amazon_page_capture")
_bridge.capture_amazon_page = _capture_in_subprocess
sys.modules["amazon_page_capture"] = _bridge

import httpx
import amazon_radar as radar

_orig_cloud_review = radar._send_amazon_independent_review

async def _cloud_review_with_diag(payload):
    r = await _orig_cloud_review(payload)
    try:
        data = r.json()
    except Exception:
        data = {}

    if isinstance(data, dict):
        keys = (
            "ok", "status", "action", "duplicate",
            "queued", "telegram", "sent",
            "error", "id", "deal_id"
        )
        safe = {k: data.get(k) for k in keys if k in data}
    else:
        safe = {}

    print(
        "AMAZON_CLOUD_RESULT",
        payload.get("asin") or payload.get("fingerprint"),
        safe or str(getattr(r, "text", ""))[:300],
        flush=True
    )

    # Telegram safety fallback:
    # Cloudflare currently accepts the deal but may not deliver the review card.
    # If its response does not explicitly confirm Telegram delivery, send the
    # already-staged screenshot directly with the same bot.
    telegram_confirmed = bool(
        data.get("telegram") or
        data.get("sent") or
        data.get("telegram_sent")
    ) if isinstance(data, dict) else False

    if not telegram_confirmed:
        try:
            token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
            chat_id = (
                os.getenv("TELEGRAM_MEDIA_STAGE_CHAT_ID", "").strip()
                or os.getenv("ADMIN_CHAT_ID", "").strip()
            )

            if token and chat_id:
                title = str(payload.get("title") or "عرض Amazon").strip()
                price = payload.get("price") or payload.get("current_price") or ""
                old = payload.get("old_price") or ""
                discount = payload.get("discount_percent") or payload.get("discount") or ""
                product_url = str(payload.get("url") or "").strip()

                text = "🔥 عرض Amazon للمراجعة\n\n"
                text += f"🛍️ {title[:500]}\n"
                if price:
                    text += f"💰 السعر: {price} ج.م\n"
                if old:
                    text += f"📉 السابق: {old} ج.م\n"
                if discount:
                    text += f"📊 الخصم: {discount}%\n"

                markup = {"inline_keyboard": []}
                if product_url:
                    markup["inline_keyboard"].append([
                        {"text": "🔗 فتح العرض", "url": product_url}
                    ])

                photo = str(
                    payload.get("telegram_photo_file_id")
                    or payload.get("image_url")
                    or ""
                ).strip()

                api = f"https://api.telegram.org/bot{token}"

                async with httpx.AsyncClient(timeout=35) as tg:
                    if photo:
                        rr = await tg.post(
                            api + "/sendPhoto",
                            json={
                                "chat_id": chat_id,
                                "photo": photo,
                                "caption": text[:1024],
                                "reply_markup": markup,
                            },
                        )
                    else:
                        rr = await tg.post(
                            api + "/sendMessage",
                            json={
                                "chat_id": chat_id,
                                "text": text[:4000],
                                "reply_markup": markup,
                                "disable_web_page_preview": False,
                            },
                        )

                    jj = rr.json()
                    print(
                        "📨 DIRECT TELEGRAM FALLBACK",
                        payload.get("asin") or payload.get("fingerprint"),
                        "|",
                        rr.status_code,
                        "| OK =", bool(jj.get("ok")),
                        flush=True,
                    )

        except Exception as tg_exc:
            print("❌ DIRECT TELEGRAM FALLBACK ERROR", repr(tg_exc), flush=True)

    return r

radar._send_amazon_independent_review = _cloud_review_with_diag

async def safe(name, coro, timeout=90):
    try:
        await asyncio.wait_for(coro, timeout=timeout)
        print(f"AMAZON_ONCE {name}=OK", flush=True)
    except asyncio.TimeoutError:
        print(f"AMAZON_ONCE {name}=TIMEOUT", flush=True)
    except Exception as exc:
        print(f"AMAZON_ONCE {name}=ERROR {exc!r}", flush=True)

async def drain_queue(limit=8):
    async with httpx.AsyncClient() as client:
        for i in range(limit):
            job = radar.pop_amazon_candidate()
            if not job:
                break
            try:
                await asyncio.wait_for(radar.process_queue_item(client, job), timeout=55)
            except Exception as exc:
                print(f"AMAZON_ONCE queue[{i}]={exc!r}", flush=True)

async def main():
    # Progressive discovery + priority checks. Every invocation advances persisted state.
    # WIDE AMAZON COVERAGE V3
    # Priority surfaces first, then more discovery/watchlist rotations so a
    # large 8k+ watchlist is not sampled only a handful of products per run.
    await safe("priority_surface", radar.direct_surface_once("priority"), 70)
    await safe("general_surface", radar.direct_surface_once("general"), 70)

    await safe("deep_discovery", radar.deep_discovery(), 25)
    await safe("hot_watch", radar.hot_watch_once(), 80)
    await safe("ultra_hot", radar.ultra_hot_once(), 90)

    for n in range(2):
        await safe(f"full_v5_{n+1}", radar.full_v5_watchlist_once(), 80)

    await safe("competitor_trigger", radar.competitor_trigger_once(), 30)
    await drain_queue(12)
    print("AMAZON_ONCE_COMPLETE", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
