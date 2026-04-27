from __future__ import annotations

from aiogram.types import CallbackQuery


async def edit_metro_card(cb: CallbackQuery, text: str, reply_markup=None) -> None:
    if not cb.message:
        return
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup)
    except Exception as e:
        if "message is not modified" in str(e).lower():
            return
        raise


async def metro_close(
    *,
    cb: CallbackQuery,
    safe_answer_fn,
    prompt_location_text: str,
    metro_location_keyboard_fn,
) -> None:
    await safe_answer_fn(cb)
    try:
        await edit_metro_card(cb, prompt_location_text, reply_markup=metro_location_keyboard_fn())
    except Exception:
        pass


async def metro_pick(
    *,
    cb: CallbackQuery,
    safe_answer_fn,
    metro_lines_keyboard_fn,
) -> None:
    await safe_answer_fn(cb)
    parts = (cb.data or "").split(":")
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    try:
        await edit_metro_card(cb, "Выбери линию метро Москвы:", reply_markup=metro_lines_keyboard_fn(page))
    except Exception:
        pass


async def metro_line_pick(
    *,
    cb: CallbackQuery,
    safe_answer_fn,
    metro_stations_keyboard_fn,
) -> None:
    await safe_answer_fn(cb)
    parts = (cb.data or "").split(":")
    if len(parts) < 3:
        return
    line_uid = parts[1]
    page = int(parts[2]) if parts[2].isdigit() else 0
    try:
        await edit_metro_card(
            cb,
            "Выбери станцию метро:",
            reply_markup=metro_stations_keyboard_fn(line_uid, page),
        )
    except Exception:
        pass
