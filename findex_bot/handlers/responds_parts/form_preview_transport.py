from __future__ import annotations

import logging

from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import LinkPreviewOptions

logger = logging.getLogger(__name__)


async def upsert_form_preview_message(
    *,
    bot,
    state: FSMContext,
    chat_id: int,
    text: str,
    reply_markup,
    track_form_bot_message_fn,
) -> None:
    data = await state.get_data()
    prev_id = data.get("form_preview_message_id")

    if prev_id:
        try:
            await bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=int(prev_id),
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            return
        except Exception as e:
            if "message is not modified" in str(e).lower():
                return
            logger.warning("edit form preview failed -> send new: %r", e)

    m = await bot.send_message(
        chat_id=int(chat_id),
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    await state.update_data(form_preview_message_id=int(m.message_id))
    await track_form_bot_message_fn(state, m)
