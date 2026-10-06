from __future__ import annotations

import asyncio
import os
from dataclasses import replace

from ..config import Settings
from ..models import Lane
from .telegram import TelegramDelivery


class RoutedTelegramDelivery:
    """Telegram router for the strict Noon/Amazon split.

    Noon: always normal review path
        secondary @EgyptDealsFinderBot

    Noon:
        always secondary review bot, regardless of lane

    Amazon:
        primary bot, unchanged
    """

    def __init__(
        self,
        settings: Settings,
        primary: TelegramDelivery | None = None,
    ):
        self.settings = settings
        self.primary = primary or TelegramDelivery(settings)

        token = os.getenv(
            "NOON_REVIEW_BOT_TOKEN", ""
        ).strip()

        chat_id = os.getenv(
            "NOON_REVIEW_BOT_CHAT_ID", ""
        ).strip()

        self.noon_review_bot_chat_id = chat_id

        # Never silently fall back to the wrong bot.
        if not token:
            raise RuntimeError(
                "NOON_REVIEW_BOT_TOKEN missing"
            )

        if not chat_id:
            raise RuntimeError(
                "NOON_REVIEW_BOT_CHAT_ID missing"
            )

        if token == settings.telegram_token:
            raise RuntimeError(
                "Noon review bot must use a separate token"
            )

        secondary_settings = replace(
            settings,
            telegram_token=token,
            normal_chat_id=chat_id,
            noon_normal_chat_id=chat_id,
        )

        self.secondary = TelegramDelivery(
            secondary_settings
        )

        self._primary_offset = None
        self._secondary_offset = None
        self._callback_sources = {}

    def _delivery_for_row(
        self,
        row: dict,
    ) -> TelegramDelivery:

        if row.get("store") == "noon":
            return self.secondary

        return self.primary

    async def send(self, row: dict) -> dict:
        delivery = self._delivery_for_row(row)
        return await delivery.send(row)

    async def send_public(
        self,
        row: dict,
        urgent: bool = False,
    ) -> dict:
        # Manual publication remains on the established
        # primary/public Telegram path.
        return await self.primary.send_public(
            row,
            urgent=urgent,
        )

    async def aclose(self) -> None:
        await self.secondary.aclose()
        await self.primary.aclose()

    async def delete_webhook(self) -> None:
        await asyncio.gather(
            self.primary.delete_webhook(),
            self.secondary.delete_webhook(),
        )

    async def get_updates(
        self,
        offset: int | None,
        timeout: int = 20,
    ) -> list[dict]:

        # Each bot has a different Telegram update_id sequence.
        # Keep a separate offset for each bot.
        results = await asyncio.gather(
            self.primary.get_updates(
                self._primary_offset,
                timeout=timeout,
            ),
            self.secondary.get_updates(
                self._secondary_offset,
                timeout=timeout,
            ),
            return_exceptions=True,
        )

        combined = []

        sources = (
            self.primary,
            self.secondary,
        )

        for index, result in enumerate(results):
            if isinstance(result, BaseException):
                continue

            delivery = sources[index]

            for update in result or []:
                try:
                    next_offset = (
                        int(update["update_id"]) + 1
                    )

                    if index == 0:
                        self._primary_offset = (
                            next_offset
                        )
                    else:
                        self._secondary_offset = (
                            next_offset
                        )

                except Exception:
                    pass

                callback = (
                    update.get("callback_query")
                    or {}
                )

                callback_id = str(
                    callback.get("id") or ""
                )

                if callback_id:
                    self._callback_sources[
                        callback_id
                    ] = delivery

                combined.append(update)

        return combined

    async def answer_callback(
        self,
        callback_id: str,
        text: str,
        alert: bool = False,
    ) -> None:

        delivery = self._callback_sources.pop(
            callback_id,
            self.primary,
        )

        await delivery.answer_callback(
            callback_id,
            text,
            alert,
        )

    async def clear_buttons(
        self,
        chat_id,
        message_id: int,
    ) -> None:

        if str(chat_id) == str(
            self.noon_review_bot_chat_id
        ):
            await self.secondary.clear_buttons(
                chat_id,
                message_id,
            )
            return

        await self.primary.clear_buttons(
            chat_id,
            message_id,
        )
