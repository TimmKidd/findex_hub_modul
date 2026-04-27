from __future__ import annotations

import contextlib
from aiogram.fsm.context import FSMContext


async def delete_form_preview_message(
    bot,
    state: FSMContext,
    chat_id: int,
    *,
    fallback_message_id: int | None = None,
) -> None:
    ids: set[int] = set()

    with contextlib.suppress(Exception):
        data = await state.get_data()
        prev_id = data.get("form_preview_message_id")
        if prev_id:
            ids.add(int(prev_id))

    if fallback_message_id:
        ids.add(int(fallback_message_id))

    for msg_id in ids:
        with contextlib.suppress(Exception):
            await bot.delete_message(chat_id=int(chat_id), message_id=int(msg_id))

    with contextlib.suppress(Exception):
        await state.update_data(form_preview_message_id=None)
