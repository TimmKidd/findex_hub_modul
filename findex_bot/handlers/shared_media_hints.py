from __future__ import annotations

import asyncio
import contextlib

from aiogram.types import Message


async def send_media_choice_hint(
    message: Message,
    *,
    text: str,
    ttl_sec: float = 4,
) -> None:
    hint = None
    try:
        hint = await message.bot.send_message(
            chat_id=message.chat.id,
            text=text,
        )
        await asyncio.sleep(ttl_sec)
    except Exception:
        return
    finally:
        with contextlib.suppress(Exception):
            if hint:
                await hint.delete()
