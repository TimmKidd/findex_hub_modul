from __future__ import annotations

from aiogram.fsm.context import FSMContext

from findex_bot.db.db import get_sessionmaker
from findex_bot.db.repo import AdRepo
from findex_bot.utils.ui_utils import cleanup_tracked_messages


async def cleanup_after_preview(
    bot,
    state: FSMContext,
    preview_msg_id: int | None,
    previous_preview_msg_id: int | None = None,
) -> None:
    keep_ids = set()

    try:
        if preview_msg_id:
            keep_ids.add(int(preview_msg_id))
    except Exception:
        pass

    try:
        if previous_preview_msg_id:
            keep_ids.add(int(previous_preview_msg_id))
    except Exception:
        pass

    await cleanup_tracked_messages(bot, state, keep_ids=keep_ids)


async def persist_preview_ref(
    *,
    state: FSMContext,
    ad_id: int,
    chat_id: int,
    message_id: int,
    is_media: bool,
    k_preview_msg_id: str,
    k_preview_is_media: str,
) -> None:
    await state.update_data(**{
        k_preview_msg_id: int(message_id),
        k_preview_is_media: bool(is_media),
    })

    async with get_sessionmaker()() as session:
        ad = await AdRepo(session).get(ad_id)
        if not ad:
            return
        payload = dict(ad.payload or {})
        payload["preview_message_id"] = int(message_id)
        payload["preview_is_media"] = bool(is_media)
        payload["preview_chat_id"] = int(chat_id)
        ad.payload = payload
        await session.commit()
