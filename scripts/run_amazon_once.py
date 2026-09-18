import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
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

STATE_DIR = Path(__file__).resolve().parents[1] / ".runtime_state"
COMPETITOR_PENDING_FILE = (
    STATE_DIR / "channel_amazon_pending.json"
)


async def process_competitor_pending(limit=4):
    """
    Competitor channels are discovery only.

    We NEVER trust their claimed discount.
    Each ASIN is opened directly on Amazon,
    then V5 performs the normal exact verification.
    """
    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    try:
        pending = json.loads(
            COMPETITOR_PENDING_FILE.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        pending = []

    if not isinstance(pending, list):
        pending = []

    if not pending:
        print(
            "🎯 COMPETITOR AMAZON PENDING = 0",
            flush=True
        )
        return 0

    remaining = []
    attempted = 0
    verified = 0
    watch_changed = False

    async with httpx.AsyncClient() as client:

        for item in pending:

            if not isinstance(item, dict):
                continue

            if attempted >= limit:
                remaining.append(item)
                continue

            asin = str(
                item.get("asin") or ""
            ).strip().upper()

            if (
                len(asin) != 10
                or not asin.isalnum()
            ):
                continue

            attempted += 1

            direct_url = radar.asin_url(asin)

            try:
                current = await radar.live_price(
                    client,
                    direct_url
                )
            except Exception as exc:
                current = 0

                print(
                    "⚠️ COMPETITOR DIRECT ERROR",
                    asin,
                    repr(exc),
                    flush=True
                )

            current = radar.to_float(current)

            if current <= 0:
                item["attempts"] = (
                    int(
                        item.get(
                            "attempts",
                            0
                        ) or 0
                    )
                    + 1
                )

                item["last_attempt_at"] = int(
                    time.time()
                )

                remaining.append(item)

                print(
                    "⏳ COMPETITOR AMAZON RETRY",
                    asin,
                    "| attempt=",
                    item["attempts"],
                    flush=True
                )

                continue

            meta = (
                radar.AMAZON_PRODUCT_META_CACHE.get(
                    asin,
                    {}
                )
            )

            exact = {
                "asin": asin,
                "url": direct_url,
                "title": (
                    meta.get("title_ar")
                    or meta.get("title")
                    or asin
                ),
                "title_ar": (
                    meta.get("title_ar")
                    or ""
                ),
                "current_price": current,
                "old_price": (
                    meta.get("old_price")
                ),
                "image_url": (
                    meta.get("image_url")
                    or ""
                ),
            }

            radar.add_product(
                exact,
                "competitor_channel_direct"
            )

            rec = radar.watch.get(asin)

            if not isinstance(rec, dict):
                item["attempts"] = (
                    int(
                        item.get(
                            "attempts",
                            0
                        ) or 0
                    )
                    + 1
                )

                remaining.append(item)
                continue

            # Highest temporary lane.
            # V5 still decides whether it is a real deal.
            rec[
                "global_deep_v95_priority"
            ] = max(
                int(
                    rec.get(
                        "global_deep_v95_priority",
                        0
                    ) or 0
                ),
                400,
            )

            rec[
                "priority_boost_until"
            ] = max(
                int(
                    rec.get(
                        "priority_boost_until",
                        0
                    ) or 0
                ),
                int(time.time()) + 3600,
            )

            rec["manual_watch"] = True
            rec[
                "competitor_fast_candidate"
            ] = True

            rec[
                "competitor_channel"
            ] = item.get("channel")

            # Keep competitor price only as context.
            # NEVER use it as Amazon reference.
            rec[
                "competitor_price_hint"
            ] = radar.to_float(
                item.get(
                    "channel_price_hint"
                )
            )

            verified += 1
            watch_changed = True

            # Do NOT remove from pending yet.
            # V5 + real Amazon review card must finish first.
            item["attempts"] = (
                int(
                    item.get(
                        "attempts",
                        0
                    ) or 0
                )
                + 1
            )

            item[
                "amazon_direct_verified_at"
            ] = int(time.time())

            remaining.append(item)

            print(
                "🎯 COMPETITOR AMAZON EXACT",
                asin,
                "| AMAZON PRICE =",
                round(current, 2),
                "| AMAZON OLD =",
                meta.get("old_price"),
                "| V5 PRIORITY = 400",
                flush=True
            )

    if watch_changed:
        async with radar.lock:
            radar.save_files()

    COMPETITOR_PENDING_FILE.write_text(
        json.dumps(
            remaining[-100:],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "🎯 COMPETITOR FAST VERIFY"
        " | ATTEMPTED =",
        attempted,
        "| VERIFIED =",
        verified,
        "| REMAINING =",
        len(remaining),
        flush=True
    )

    return verified


def prune_competitor_pending_after_review():
    """
    Remove competitor ASIN only after the Amazon review
    system has actually created/retained a review card.

    If review failed (CAPTCHA/503/etc), keep it for retry.
    """
    try:
        pending = json.loads(
            COMPETITOR_PENDING_FILE.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        pending = []

    if not isinstance(pending, list):
        pending = []

    if not pending:
        return 0

    db_path = REVIEW_DIR / "amazon_bot.db"

    if not db_path.exists():
        print(
            "⏳ COMPETITOR PENDING KEPT"
            " | REVIEW DB NOT FOUND",
            flush=True
        )
        return 0

    kept = []
    removed = 0

    try:
        db = sqlite3.connect(str(db_path))

        for item in pending:

            if not isinstance(item, dict):
                continue

            asin = str(
                item.get("asin") or ""
            ).strip().upper()

            if (
                len(asin) != 10
                or not asin.isalnum()
            ):
                continue

            did = hashlib.sha1(
                ("asin:" + asin).encode()
            ).hexdigest()[:24]

            row = db.execute(
                """
                SELECT status, review_message_id
                FROM deals
                WHERE deal_id=?
                """,
                (did,),
            ).fetchone()

            if row and row[1]:
                removed += 1

                print(
                    "✅ COMPETITOR REVIEW CONFIRMED",
                    asin,
                    "| status=",
                    row[0],
                    "| message_id=",
                    row[1],
                    flush=True
                )

                continue

            attempts = int(
                item.get(
                    "attempts",
                    0
                ) or 0
            )

            # Give transient Amazon/CAPTCHA failures
            # several future runs before retiring.
            if attempts >= 4:
                removed += 1

                print(
                    "🧹 COMPETITOR PENDING RETIRED",
                    asin,
                    "| attempts=",
                    attempts,
                    "| no review card",
                    flush=True
                )

                continue

            kept.append(item)

        db.close()

    except Exception as exc:
        print(
            "⚠️ COMPETITOR PENDING PRUNE ERROR",
            repr(exc),
            flush=True
        )

        return 0

    COMPETITOR_PENDING_FILE.write_text(
        json.dumps(
            kept[-100:],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "🎯 COMPETITOR PENDING FINAL"
        " | CONFIRMED/RETIRED =",
        removed,
        "| KEPT =",
        len(kept),
        flush=True
    )

    return removed


async def safe(name, coro, timeout=90):
    try:
        await asyncio.wait_for(coro, timeout=timeout)
        print(f"AMAZON_ONCE {name}=OK", flush=True)
    except asyncio.TimeoutError:
        print(f"AMAZON_ONCE {name}=TIMEOUT", flush=True)
    except Exception as exc:
        print(f"AMAZON_ONCE {name}=ERROR {exc!r}", flush=True)

def surface_backoff_active():
    try:
        return (
            time.monotonic()
            < float(
                getattr(
                    radar,
                    "AMAZON_SURFACE_BACKOFF_UNTIL",
                    0
                ) or 0
            )
        )
    except Exception:
        return False


async def drain_queue(limit=8):
    async with httpx.AsyncClient() as client:
        for i in range(limit):

            # Do NOT pop discovery work while Search is paused.
            if radar.amazon_search_backoff_active():
                print(
                    "⏳ AMAZON_ONCE QUEUE PAUSED"
                    " | SEARCH BACKOFF ACTIVE"
                    " | QUEUE =",
                    len(radar.UNIFIED_AMAZON_QUEUE),
                    flush=True
                )
                break

            job = radar.pop_amazon_candidate()

            if not job:
                break

            try:
                ok = await asyncio.wait_for(
                    radar.process_queue_item(
                        client,
                        job
                    ),
                    timeout=55
                )

                # If this request itself triggered a block/503,
                # put it back so the late drain can retry it.
                if ok is False:
                    job["attempts"] = int(
                        job.get("attempts", 0) or 0
                    ) + 1

                    job["ready_at"] = (
                        time.time() + 15
                    )

                    radar.UNIFIED_AMAZON_QUEUE.append(
                        job
                    )

                    radar.UNIFIED_AMAZON_QUEUE.sort(
                        key=lambda x: (
                            -x.get("priority", 0),
                            x.get("ready_at", 0),
                        )
                    )

                    print(
                        "↩️ AMAZON_ONCE QUEUE REQUEUED",
                        job.get("source"),
                        "| QUEUE =",
                        len(radar.UNIFIED_AMAZON_QUEUE),
                        flush=True
                    )
                    break

            except Exception as exc:
                print(
                    f"AMAZON_ONCE queue[{i}]={exc!r}",
                    flush=True
                )

async def main():

    # COMPETITOR FAST VERIFY FIRST.
    # Do this before Search/direct surfaces can trigger
    # Amazon backoff and delay a newly spotted deal.
    competitor_verified = await process_competitor_pending(
        4
    )

    if competitor_verified > 0:
        await safe(
            "competitor_pending_v5",
            radar.full_v5_watchlist_once(),
            70
        )

    # Delete competitor pending only when the full
    # Amazon review card actually exists.
    prune_competitor_pending_after_review()

    # Progressive discovery + priority checks. Every invocation advances persisted state.
    # WIDE AMAZON COVERAGE V3
    # Priority surfaces first, then more discovery/watchlist rotations so a
    # large 8k+ watchlist is not sampled only a handful of products per run.
    # Faster consumer/deal coverage.
    # Four rotations normally cover coupons/grocery/food or
    # the next four persisted priority surfaces.
    for n in range(4):

        if surface_backoff_active():
            print(
                "⏳ PRIORITY SURFACE ROTATION PAUSED"
                " | AMAZON SURFACE BACKOFF",
                flush=True
            )
            break

        await safe(
            f"priority_surface_{n+1}",
            radar.direct_surface_once("priority"),
            70
        )

        if surface_backoff_active():
            print(
                "⏳ PRIORITY SURFACE ROTATION STOPPED"
                " | BACKOFF TRIGGERED",
                flush=True
            )
            break

    # ALL AMAZON DEPARTMENTS — fast round-robin coverage
    # Each call advances to another department while preserving its page.
    for n in range(6):

        if surface_backoff_active():
            print(
                "⏳ GENERAL SURFACE ROTATION PAUSED"
                " | AMAZON SURFACE BACKOFF",
                flush=True
            )
            break

        await safe(
            f"general_surface_{n+1}",
            radar.direct_surface_once("general"),
            45
        )

        if surface_backoff_active():
            print(
                "⏳ GENERAL SURFACE ROTATION STOPPED"
                " | BACKOFF TRIGGERED",
                flush=True
            )
            break

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
