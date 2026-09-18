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

# Initialize Amazon intelligence + price history database.
import db as amazon_db
amazon_db.init_db()
print("✅ AMAZON PRICE INTELLIGENCE DB READY", flush=True)

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
    # Faster consumer/deal coverage.
    # Four rotations normally cover coupons/grocery/food or
    # the next four persisted priority surfaces.
    for n in range(4):
        await safe(
            f"priority_surface_{n+1}",
            radar.direct_surface_once("priority"),
            70
        )

    # ALL AMAZON DEPARTMENTS — fast round-robin coverage
    # Each call advances to another department while preserving its page.
    for n in range(6):
        await safe(
            f"general_surface_{n+1}",
            radar.direct_surface_once("general"),
            45
        )

    await safe("deep_discovery", radar.deep_discovery(), 25)

    # Process the first discovery groups BEFORE V5.
    # Grocery is inside this first batch, so newly discovered
    # consumer products can be verified in the SAME run.
    await drain_queue(8)

    await safe("hot_watch", radar.hot_watch_once(), 80)
    await safe("ultra_hot", radar.ultra_hot_once(), 90)

    # Keep historical/watchlist verification, but give fresh departments
    # more runtime so new deals are discovered faster.
    await safe("full_v5", radar.full_v5_watchlist_once(), 70)

    await safe("competitor_trigger", radar.competitor_trigger_once(), 30)

    # Keep four queue slots for late competitor/trigger work.
    await drain_queue(4)
    print("AMAZON_ONCE_COMPLETE", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
