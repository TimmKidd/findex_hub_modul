from __future__ import annotations

from typing import Optional, Tuple

from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from findex_bot.db.db import get_sessionmaker
from findex_bot.db.repo import AdRepo
from findex_bot.utils.ui_utils import (
    safe_answer,
    employer_media_choice_kb,
    seeker_media_choice_kb,
    track_cleanup_message,
)
from findex_bot.utils.moscow_metro import metro_location_keyboard
from findex_bot.utils.vacancy_utils import resolve_ad_role


def _parse_preview_edit(cbdata: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    s = (cbdata or "").strip()
    if not s:
        return None, None, None

    if s.startswith("emp_edit_"):
        role = "employer"
        left = s[len("emp_edit_"):]
    elif s.startswith("seek_edit_"):
        role = "seeker"
        left = s[len("seek_edit_"):]
    else:
        return None, None, None

    if ":" not in left:
        return None, None, None

    field, ad_part = left.split(":", 1)
    field = (field or "").strip().lower()

    try:
        ad_id = int(ad_part.strip())
    except Exception:
        ad_id = None

    if field == "about":
        field = "about"
    if field == "media":
        field = "media"

    return role, field, ad_id


async def _start_edit_from_preview(cb: CallbackQuery, state: FSMContext):
    from findex_bot.handlers.forms import (
        logger,
        K_EDIT_MODE,
        K_PREVIEW_MSG_ID,
        K_PREVIEW_IS_MEDIA,
        _chat_type_str,
        _prompt_for,
        _field_title_local,
    )
    await safe_answer(cb)

    if _chat_type_str(cb) != "private":
        return

    role, field, ad_id = _parse_preview_edit(cb.data or "")
    if not role or not field or not ad_id:
        return

    try:
        async with get_sessionmaker()() as session:
            ad = await AdRepo(session).get(int(ad_id))
            if not ad:
                return await safe_answer(cb, "❌ Объявление не найдено", alert=True)
            author_id = int(getattr(ad, "author_user_id", 0) or 0)

            try:
                payload = ad.payload or {}
                rid = int(payload.get("reject_notice_message_id") or 0)
                rcid = int(payload.get("reject_notice_chat_id") or 0)
                if rid > 0 and rcid > 0:
                    await cb.bot.delete_message(chat_id=rcid, message_id=rid)
                    logger.warning(
                        "REJECT_NOTICE_DELETE_OK ad_id=%s field=%s role=%s rcid=%s rid=%s",
                        ad_id, field, role, rcid, rid,
                    )
            except Exception:
                logger.exception("REJECT_NOTICE_DELETE_FAIL ad_id=%s field=%s", ad_id, field)

            if author_id != int(cb.from_user.id):
                return await safe_answer(cb, "⛔️ Нет доступа", alert=True)
    except Exception:
        logger.exception("failed to validate preview edit access ad_id=%s field=%s", ad_id, field)
        return await safe_answer(cb, "❌ Не удалось открыть режим редактирования", alert=True)

    try:
        is_media = bool(getattr(cb.message, "caption", None) is not None) if cb.message else False
        await state.update_data(
            ad_id=int(ad_id),
            **{
                K_EDIT_MODE: True,
                K_PREVIEW_MSG_ID: int(cb.message.message_id) if cb.message else None,
                K_PREVIEW_IS_MEDIA: bool(is_media),
            },
        )
    except Exception:
        logger.exception("failed to update FSM data for preview edit ad_id=%s field=%s", ad_id, field)

    if field == "media":
        text, next_state = _prompt_for(role, field)
        try:
            await state.set_state(next_state)
        except Exception:
            logger.exception("failed to set FSM state for preview media edit ad_id=%s field=%s", ad_id, field)

        if not cb.message:
            return

        if role == "seeker":
            sent = await cb.message.answer(
                f"✏️ Исправить: {_field_title_local(field)}\n\n{text}",
                reply_markup=seeker_media_choice_kb(),
            )
        else:
            sent = await cb.message.answer(
                f"✏️ Исправить: {_field_title_local(field)}\n\n{text}",
                reply_markup=employer_media_choice_kb(),
            )
        await track_cleanup_message(state, sent)
        return

    text, next_state = _prompt_for(role, field)
    try:
        await state.set_state(next_state)
    except Exception:
        logger.exception("failed to set FSM state for preview edit ad_id=%s field=%s", ad_id, field)

    if cb.message:
        if field == "location":
            sent = await cb.message.answer(
                f"✏️ Исправить: {_field_title_local(field)}\n\n{text}",
                reply_markup=metro_location_keyboard(),
            )
        else:
            sent = await cb.message.answer(f"✏️ Исправить: {_field_title_local(field)}\n\n{text}")
        await track_cleanup_message(state, sent)
