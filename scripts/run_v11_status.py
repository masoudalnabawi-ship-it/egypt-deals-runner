#!/usr/bin/env python3

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / ".runtime_state" / "store_scan_status.json"

STORES = ("noon", "btech", "2b")

LABELS = {
    "noon": "Noon",
    "btech": "B.TECH",
    "2b": "2B",
}

status = {
    "noon": "🔄 جاري الفحص",
    "btech": "🔄 جاري الفحص",
    "2b": "🔄 جاري الفحص",
}


def load_state():
    try:
        return json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        return {}


def save_state(data):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def telegram_call(method, payload):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    if not token:
        return {}

    url = (
        f"https://api.telegram.org/bot{token}/{method}"
    )

    data = urllib.parse.urlencode(payload).encode()

    try:
        with urllib.request.urlopen(
            url,
            data=data,
            timeout=15,
        ) as r:
            return json.loads(
                r.read().decode("utf-8")
            )
    except Exception:
        return {}


def status_text():
    now = datetime.now(
        ZoneInfo("Africa/Cairo")
    ).strftime("%H:%M:%S")

    return (
        "🛰 Egypt Deals — Live Status\n\n"
        "Amazon   ✅ Realtime\n"
        f"Noon     {status['noon']}\n"
        f"B.TECH   {status['btech']}\n"
        f"2B       {status['2b']}\n\n"
        f"🕒 آخر تحديث: {now}"
    )


def publish_status():
    chat_id = (
        os.getenv("ADMIN_CHAT_ID", "").strip()
        or
        os.getenv(
            "TELEGRAM_MEDIA_STAGE_CHAT_ID",
            ""
        ).strip()
    )

    if not chat_id:
        return

    state = load_state()
    message_id = state.get("message_id")
    text = status_text()

    if message_id:
        result = telegram_call(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
            },
        )

        if result.get("ok"):
            state["status"] = status
            save_state(state)
            return

        desc = str(
            result.get("description", "")
        ).lower()

        if "message is not modified" in desc:
            return

    result = telegram_call(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
        },
    )

    if result.get("ok"):
        mid = (
            result.get("result", {})
            .get("message_id")
        )

        save_state(
            {
                "message_id": mid,
                "status": status,
            }
        )


publish_status()

cmd = [
    sys.executable,
    "scripts/run_v11_once.py",
]

p = subprocess.Popen(
    cmd,
    cwd=ROOT,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1,
)

for line in p.stdout:
    print(line, end="", flush=True)

    low = line.lower()

    for store in STORES:
        marker = f"| {store} |"

        if marker not in low:
            continue

        old = status[store]

        if "v11 store ready" in low:
            m = re.search(
                r"fetched=(\d+)",
                low,
            )

            count = (
                m.group(1)
                if m
                else "0"
            )

            status[store] = (
                f"✅ يعمل — {count} منتج"
            )

        elif "v11 store timeout" in low:
            status[store] = "⚠️ Timeout"

        elif "v11 store error" in low:
            status[store] = "❌ Error"

        elif "v11 store cooldown" in low:
            status[store] = "🟡 Cooldown"

        if status[store] != old:
            publish_status()

rc = p.wait()

for store in STORES:
    if status[store] == "🔄 جاري الفحص":
        status[store] = "⚪ لم يظهر في الدورة"

publish_status()

raise SystemExit(rc)
