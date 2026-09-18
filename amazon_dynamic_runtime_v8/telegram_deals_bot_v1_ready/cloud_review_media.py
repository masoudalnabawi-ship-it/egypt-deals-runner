from __future__ import annotations

import json
import os
from pathlib import Path

import httpx


async def stage_photo_for_cloudflare(photo_path: str) -> str:
    """Upload a local screenshot to Telegram briefly and return its reusable file_id.

    Cloudflare can pass this file_id directly to Telegram's sendPhoto API using
    the same bot token. The staging message is deleted immediately, so the user
    does not get duplicate media messages.
    """
    path = Path(str(photo_path or "").strip())
    if not path.is_file():
        return ""

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = (
        os.getenv("TELEGRAM_MEDIA_STAGE_CHAT_ID", "").strip()
        or os.getenv("ADMIN_CHAT_ID", "").strip()
        or os.getenv("REVIEW_CHAT_ID", "").strip()
    )
    if not token or not chat_id:
        return ""

    api = f"https://api.telegram.org/bot{token}"
    try:
        async with httpx.AsyncClient(timeout=55) as client:
            with path.open("rb") as f:
                resp = await client.post(
                    api + "/sendPhoto",
                    data={"chat_id": chat_id, "disable_notification": "true"},
                    files={"photo": (path.name, f, "image/jpeg")},
                )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                return ""
            msg = data.get("result") or {}
            photos = msg.get("photo") or []
            file_id = str((photos[-1] if photos else {}).get("file_id") or "")

            # Best effort: remove the staging message immediately. Telegram's
            # reusable file_id remains valid for the same bot.
            message_id = msg.get("message_id")
            if message_id is not None:
                try:
                    await client.post(
                        api + "/deleteMessage",
                        json={"chat_id": chat_id, "message_id": message_id},
                    )
                except Exception:
                    pass

            return file_id
    except Exception:
        return ""
