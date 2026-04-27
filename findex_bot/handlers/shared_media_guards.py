from __future__ import annotations

from aiogram.types import Message


def buttons_only_notice_text(text: str) -> str:
    return str(text)


async def send_guard_hint(
    *,
    message: Message,
    text: str,
    track_cleanup_message_fn,
):
    hint = await message.answer(text)
    await track_cleanup_message_fn(hint)
    return hint
