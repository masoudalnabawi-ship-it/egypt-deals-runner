#!/usr/bin/env python3

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess
import signal
import sys
import time
import os

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

PYTHON = sys.executable
STOP = False

COMPETITOR_INTERVAL = int(os.getenv("COMPETITOR_INTERVAL", "20"))
AMAZON_INTERVAL = int(os.getenv("AMAZON_INTERVAL", "45"))
STORES_INTERVAL = int(os.getenv("STORES_INTERVAL", "120"))


def log(msg):
    print(
        time.strftime("%Y-%m-%d %H:%M:%S"),
        "|",
        msg,
        flush=True,
    )


def stop_worker(*_):
    global STOP
    STOP = True
    log("🛑 REALTIME WORKER STOP REQUESTED")


signal.signal(signal.SIGTERM, stop_worker)
signal.signal(signal.SIGINT, stop_worker)


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


def competitor_cycle():
    run_script(
        "COMPETITOR BENCHMARK",
        "scripts/channel_benchmark.py",
        60,
    )

    run_script(
        "COMPETITOR FLASH MEMORY",
        "scripts/channel_flash_memory.py",
        60,
    )


def amazon_cycle():
    run_script(
        "AMAZON REALTIME SCAN",
        "scripts/run_amazon_once.py",
        180,
    )


def stores_cycle():
    run_script(
        "NOON + BTECH + 2B SCAN",
        "scripts/run_v11_status.py",
        180,
    )


def start_listener():
    run_script(
        "AMAZON REVIEW CONFIG",
        "scripts/prepare_amazon_review_config.py",
        60,
    )

    log("🤖 STARTING PERMANENT TELEGRAM LISTENER")

    return subprocess.Popen(
        [
            PYTHON,
            "amazon_dynamic_runtime_v8/"
            "amazon_deals_bot_ready/bot.py",
        ],
        cwd=ROOT,
    )


# Restore persisted watchlists, price history and review state
# before starting the permanent worker.
try:
    subprocess.run(
        ["bash", "scripts/state.sh", "hydrate"],
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    log("📦 RUNTIME STATE HYDRATED")
except Exception as exc:
    log(f"⚠️ STATE HYDRATE ERROR {exc!r}")

listener = start_listener()

jobs = {}
next_run = {
    "competitor": 0.0,
    "amazon": 0.0,
    "stores": 0.0,
}

intervals = {
    "competitor": COMPETITOR_INTERVAL,
    "amazon": AMAZON_INTERVAL,
    "stores": STORES_INTERVAL,
}

STATE_SYNC_INTERVAL = int(
    os.getenv("STATE_SYNC_INTERVAL", "60")
)
next_state_sync = 0.0

functions = {
    "competitor": competitor_cycle,
    "amazon": amazon_cycle,
    "stores": stores_cycle,
}

log(
    "🚀 REALTIME WORKER ON"
    f" | competitor={COMPETITOR_INTERVAL}s"
    f" | amazon={AMAZON_INTERVAL}s"
    f" | noon+btech={STORES_INTERVAL}s"
)

with ThreadPoolExecutor(max_workers=3) as pool:

    while not STOP:

        if listener.poll() is not None:
            log("⚠️ TELEGRAM LISTENER STOPPED — RESTARTING")
            time.sleep(3)
            listener = start_listener()

        now = time.monotonic()

        # Persist watchlists, price history and Telegram state.
        if now >= next_state_sync:
            try:
                subprocess.run(
                    ["bash", "scripts/state.sh", "collect"],
                    cwd=ROOT,
                    timeout=30,
                    check=False,
                )
                log("💾 RUNTIME STATE SYNCED")
            except Exception as exc:
                log(f"⚠️ STATE SYNC ERROR {exc!r}")

            next_state_sync = now + STATE_SYNC_INTERVAL

        for name in ("competitor", "amazon", "stores"):

            future = jobs.get(name)

            if future is not None and not future.done():
                continue

            if now < next_run[name]:
                continue

            jobs[name] = pool.submit(functions[name])

            next_run[name] = (
                now + intervals[name]
            )

        time.sleep(1)


# Final state snapshot before shutdown.
try:
    subprocess.run(
        ["bash", "scripts/state.sh", "collect"],
        cwd=ROOT,
        timeout=30,
        check=False,
    )
    log("💾 FINAL RUNTIME STATE SYNCED")
except Exception as exc:
    log(f"⚠️ FINAL STATE SYNC ERROR {exc!r}")

log("🧹 STOPPING TELEGRAM LISTENER")

try:
    listener.terminate()
    listener.wait(timeout=10)
except Exception:
    try:
        listener.kill()
    except Exception:
        pass

log("✅ REALTIME WORKER STOPPED")
