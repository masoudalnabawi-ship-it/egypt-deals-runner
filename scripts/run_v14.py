from __future__ import annotations

import asyncio
import logging
import signal
import sys

from deals_v14.config import Settings
from deals_v14.delivery.routed import RoutedTelegramDelivery
from deals_v14.workers.pipeline import V14Pipeline


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


async def main():
    settings = Settings.from_env()
    pipeline = V14Pipeline(settings)

    pipeline.delivery = RoutedTelegramDelivery(
        settings,
        primary=pipeline.delivery,
    )

    loop = asyncio.get_running_loop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, pipeline.stop)
        except NotImplementedError:
            pass

    await pipeline.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
