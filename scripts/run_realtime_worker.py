#!/usr/bin/env python3

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

PYTHON = sys.executable
STOP = False

COMPETITOR_INTERVAL = int(
    os.getenv("COMPETITOR_INTERVAL", "20")
)
STORES_INTERVAL = int(
    os.getenv("STORES_INTERVAL", "120")
)
STATE_SYNC_INTERVAL = int(
    os.getenv("STATE_SYNC_INTERVAL", "60")
)


def log(msg):
    print(
        time.strftime("%Y-%m-%d %H:%M:%S"),
        "|",
        msg,
        flush=True,
    )


def request_stop(*_):
    global STOP
    STOP = True
    log("🛑 UNIFIED RUNTIME STOP REQUESTED")


signal.signal(signal.SIGTERM, request_stop)
signal.signal(signal.SIGINT, request_stop)


def run_script(label, script, timeout):
    log(f"▶️ {label} START")

    try:
        result = subprocess.run(
            [PYTHON, script],
            cwd=ROOT,
            timeout=timeout,
        )

        log(
            f"{'✅' if result.returncode == 0 else '⚠️'} "
            f"{label} RC={result.returncode}"
        )

        return result.returncode

    except subprocess.TimeoutExpired:
        log(f"⏳ {label} TIMEOUT")
        return 124

    except Exception as exc:
        log(f"❌ {label} ERROR {exc!r}")
        return 1


def start_process(label, script):
    log(f"🚀 START {label}")

    return subprocess.Popen(
        [PYTHON, script],
        cwd=ROOT,
    )


def competitor_cycle():
    rc = run_script(
        "COMPETITOR DISCOVERY",
        "scripts/channel_benchmark.py",
        70,
    )

    if rc == 0:
        run_script(
            "COMPETITOR AMAZON ROUTER",
            "scripts/channel_flash_memory.py",
            70,
        )


def stores_cycle():
    run_script(
        "NOON + BTECH + 2B",
        "scripts/run_v11_status.py",
        180,
    )


# --------------------------------------------
# Restore ONE persisted runtime state
# --------------------------------------------
try:
    subprocess.run(
        ["bash", "scripts/state.sh", "hydrate"],
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    log("📦 STATE HYDRATED")
except Exception as exc:
    log(f"⚠️ STATE HYDRATE {exc!r}")


# Prepare Amazon review DB/config.
run_script(
    "AMAZON REVIEW CONFIG",
    "scripts/prepare_amazon_review_config.py",
    60,
)


# Amazon bot is QUEUE-ONLY.
# It sends Amazon review cards but NEVER calls getUpdates.
amazon_review = start_process(
    "AMAZON REVIEW QUEUE",
    "amazon_dynamic_runtime_v8/"
    "amazon_deals_bot_ready/bot.py",
)

amazon_radar = start_process(
    "AMAZON RADAR",
    "amazon_dynamic_runtime_v8/"
    "telegram_deals_bot_v1_ready/"
    "amazon_radar.py",
)

amazon_native_scout = start_process(
    "AMAZON NATIVE SCOUT",
    "scripts/amazon_native_scout.py",
)

# This is the ONLY Telegram getUpdates process.
moderation = start_process(
    "UNIFIED TELEGRAM MODERATION",
    "scripts/unified_moderation.py",
)


children = {
    "amazon_review": (
        amazon_review,
        "amazon_dynamic_runtime_v8/"
        "amazon_deals_bot_ready/bot.py",
    ),
    "amazon_radar": (
        amazon_radar,
        "amazon_dynamic_runtime_v8/"
        "telegram_deals_bot_v1_ready/"
        "amazon_radar.py",
    ),
    "amazon_native_scout": (
        amazon_native_scout,
        "scripts/amazon_native_scout.py",
    ),
    "moderation": (
        moderation,
        "scripts/unified_moderation.py",
    ),
}


jobs = {}
next_run = {
    "competitor": 0.0,
    "stores": 0.0,
}

intervals = {
    "competitor": COMPETITOR_INTERVAL,
    "stores": STORES_INTERVAL,
}

functions = {
    "competitor": competitor_cycle,
    "stores": stores_cycle,
}

next_state_sync = 0.0

log(
    "✅ UNIFIED DEALS RUNTIME ONLINE"
    f" | competitors={COMPETITOR_INTERVAL}s"
    f" | stores={STORES_INTERVAL}s"
    " | telegram_pollers=1"
)


with ThreadPoolExecutor(max_workers=2) as pool:

    while not STOP:

        # Restart permanent child only if it actually died.
        for name, (proc, script) in list(
            children.items()
        ):
            if proc.poll() is None:
                continue

            log(
                f"⚠️ {name.upper()} STOPPED"
                " — RESTARTING"
            )

            time.sleep(2)

            new_proc = start_process(
                name.upper(),
                script,
            )

            children[name] = (
                new_proc,
                script,
            )

        now = time.monotonic()

        if now >= next_state_sync:
            try:
                subprocess.run(
                    ["bash", "scripts/state.sh", "collect"],
                    cwd=ROOT,
                    timeout=30,
                    check=False,
                )
                log("💾 STATE SYNCED")
            except Exception as exc:
                log(
                    f"⚠️ STATE SYNC ERROR {exc!r}"
                )

            next_state_sync = (
                now + STATE_SYNC_INTERVAL
            )

        for name in (
            "competitor",
            "stores",
        ):
            future = jobs.get(name)

            if (
                future is not None
                and not future.done()
            ):
                continue

            if now < next_run[name]:
                continue

            jobs[name] = pool.submit(
                functions[name]
            )

            next_run[name] = (
                now + intervals[name]
            )

        time.sleep(1)


# --------------------------------------------
# Clean shutdown: NO orphan pollers/processes
# --------------------------------------------
log("🧹 STOPPING UNIFIED RUNTIME")

for name, (proc, _) in children.items():
    try:
        log(f"🧹 STOP {name}")
        proc.terminate()
    except Exception:
        pass

for name, (proc, _) in children.items():
    try:
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

try:
    subprocess.run(
        ["bash", "scripts/state.sh", "collect"],
        cwd=ROOT,
        timeout=30,
        check=False,
    )
except Exception:
    pass

log("✅ UNIFIED RUNTIME STOPPED")
