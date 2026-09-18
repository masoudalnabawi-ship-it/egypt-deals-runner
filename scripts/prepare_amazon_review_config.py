import json
import os
from pathlib import Path

dst = (
    Path(__file__).resolve().parents[1]
    / "amazon_dynamic_runtime_v8"
    / "amazon_deals_bot_ready"
    / "config.json"
)

cfg = {
    "token": os.environ["TELEGRAM_BOT_TOKEN"],
    "review_group_id": int(os.environ["AMAZON_REVIEW_GROUP_ID"]),
    "normal_review_chat_id": int(
        os.environ["AMAZON_NORMAL_REVIEW_CHAT_ID"]
    ),
    "channel_id": int(os.environ["AMAZON_CHANNEL_ID"]),
    "inbox": "inbox.jsonl",
}

dst.write_text(
    json.dumps(cfg, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print("✅ AMAZON PRIVATE REVIEW CONFIG READY")
