#!/usr/bin/env python3

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V11 = ROOT / "telegram_deals_bot_v7_dev"

sys.path.insert(0, str(V11))
os.chdir(V11)

from db import init_db
from engine import moderation_loop

async def main():
    init_db()

    print(
        "🤖 UNIFIED TELEGRAM MODERATION ONLINE",
        flush=True,
    )

    await moderation_loop()

if __name__ == "__main__":
    asyncio.run(main())
