from __future__ import annotations

import logging

from .models import Lane
from .workers.pipeline import V14Pipeline


log = logging.getLogger("v14.shadow")


class ShadowV14Pipeline(V14Pipeline):

    async def delivery_loop(self, lane: Lane):
        log.warning(
            "V14 SHADOW | delivery disabled | lane=%s",
            lane.value,
        )
        await self.stop_event.wait()

    async def callback_loop(self):
        log.warning(
            "V14 SHADOW | Telegram callbacks disabled"
        )
        await self.stop_event.wait()
