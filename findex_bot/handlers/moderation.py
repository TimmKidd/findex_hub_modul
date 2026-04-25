# findex_bot/handlers/moderation.py
from __future__ import annotations

import logging
import os
from typing import Optional

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import findex_bot.runtime as runtime
from findex_bot.db.db import get_sessionmaker
from findex_bot.db.repo import AdRepo
from findex_bot.utils.ui_utils import safe_answer, rejection_reasons_kb, rejected_user_text, field_title
from findex_bot.utils.obs import log_event

logger = logging.getLogger(__name__)
router = Router()


def _parse_id(cbdata: str) -> int:
    return int((cbdata or "").split(":")[1])


def _get_moderation_chat_id() -> int:
    val = getattr(runtime, "MODERATION_CHAT_ID", None)
    if val is None:
        val = os.getenv("MODERATION_CHAT_ID")
    if val is None:
        raise RuntimeError("MODERATION_CHAT_ID is not configured (runtime.MODERATION_CHAT_ID / env MODERATION_CHAT_ID)")
    return int(val)


def _reason_text(role: str, field_key: str) -> str:
    role = (role or "").strip().lower()

    if role == "seeker":
        mapping = {
            "title": "Должность некорректная",
            "schedule": "График некорректный",
            "salary": "Зарплата некорректная",
            "location": "Локация некорректная",
            "contacts": "Контакты некорректные",
            "about": "О себе некорректно",
            "media": "Фото некорректное",
        }
        return mapping.get(field_key, "Заполнено некорректно")

    mapping = {
        "title": "Должность некорректная",
        "salary": "Зарплата некорректная",
        "location": "Локация некорректная",
        "contacts": "Контакты некорректные",
        "description": "Описание некорректное",
        "media": "Медиа некорректное",
    }
    return mapping.get(field_key, "Заполнено некорректно")


def _moderator_label(cb: CallbackQuery) -> str:
    u = cb.from_user
    if getattr(u, "username", None):
        return f"@{u.username}"
    full = " ".join([x for x in [getattr(u, "first_name", None), getattr(u, "last_name", None)] if x]) or ""
    return full or str(getattr(u, "id", "—"))


def _build_rejected_line(cb: CallbackQuery, reason: str) -> str:
    return f"\n\n❌ Отклонено\nМодератор: {_moderator_label(cb)}\nПричина: {reason}"


def _strip_previous_rejected_line(text: str) -> str:
    if not text:
        return text
    marker_legacy = "\n\n✖ Отклонено: причина —"
    if marker_legacy in text:
        text = text.split(marker_legacy)[0]
    marker_new = "\n\n❌ Отклонено"
    if marker_new in text:
        text = text.split(marker_new)[0]
    return text


async def _edit_mod_message_keep_header(cb: CallbackQuery, reason: str) -> None:
    """
    Ключевой фикс:
    НЕ пересобираем объявление заново (иначе теряются тех-строки).
    Берём текущий текст/капшен, чистим старый хвост и дописываем новый.
    """
    if not cb.message:
        return

    try:
        if cb.message.caption is not None:
            base = _strip_previous_rejected_line(cb.message.caption)
            await cb.message.edit_caption(caption=base + _build_rejected_line(cb, reason), reply_markup=None)
        else:
            base = _strip_previous_rejected_line(cb.message.text or "")
            await cb.message.edit_text(base + _build_rejected_line(cb, reason), reply_markup=None)
    except Exception:
        pass


def _fix_callback(role: str, field_key: str, ad_id: int) -> Optional[str]:
    role = (role or "").strip().lower()

    if role == "seeker":
        mapping = {
            "title": f"seek_edit_title:{ad_id}",
            "schedule": f"seek_edit_schedule:{ad_id}",
            "salary": f"seek_edit_salary:{ad_id}",
            "location": f"seek_edit_location:{ad_id}",
            "contacts": f"seek_edit_contacts:{ad_id}",
            "about": f"seek_edit_about:{ad_id}",
            "media": f"seek_edit_media:{ad_id}",
        }
        return mapping.get(field_key)

    mapping = {
        "title": f"emp_edit_title:{ad_id}",
        "salary": f"emp_edit_salary:{ad_id}",
        "location": f"emp_edit_location:{ad_id}",
        "contacts": f"emp_edit_contacts:{ad_id}",
        "description": f"emp_edit_description:{ad_id}",
        "media": f"emp_edit_media:{ad_id}",
    }
    return mapping.get(field_key)


def _user_fix_keyboard_for_field(field_key: str, fix_callback_data: str) -> InlineKeyboardMarkup:
    """
    Строго как на твоём скрине:
      ✏️ Исправить: Локация
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"✏️ Исправить: {field_title(field_key)}", callback_data=fix_callback_data)]
        ]
    )


# -----------------------------
# MOD: reject -> show reasons
# -----------------------------
@router.callback_query(F.data.startswith("mod_reject:"))
async def mod_reject(cb: CallbackQuery):
    # важно: тут НЕ показываем alert “Отклонено”, только открываем выбор причин
    await safe_answer(cb)

    ad_id = _parse_id(cb.data)
    async with get_sessionmaker()() as session:
        ad = await AdRepo(session).get(ad_id)
        if not ad:
            log_event(
                logger,
                "moderation_reject_open",
                moderator_user_id=cb.from_user.id,
                callback_data=cb.data,
                ad_id=ad_id,
                result="not_found",
            )
            return await safe_answer(cb, "❌ Не найдено", alert=True)

        role = (ad.payload or {}).get("role") or getattr(ad, "role", None) or "employer"

    log_event(
        logger,
        "moderation_reject_open",
        moderator_user_id=cb.from_user.id,
        callback_data=cb.data,
        ad_id=ad_id,
        role=role,
        result="ok",
    )

    if cb.message:
        try:
            await cb.message.edit_reply_markup(reply_markup=rejection_reasons_kb(ad_id, str(role)))
        except Exception:
            # если вдруг edit_reply_markup не дался — хотя бы ответим понятным текстом
            return await safe_answer(cb, "⚠️ Не смог открыть причины (edit_reply_markup).", alert=True)


# -----------------------------
# MOD: select reason
# rejr:<ad_id>:<field_key>
# -----------------------------
@router.callback_query(F.data.startswith("mod_rejr:"))
async def mod_reject_reason(cb: CallbackQuery):
    await safe_answer(cb)

    parts = (cb.data or "").split(":")
    if len(parts) < 3:
        log_event(
            logger,
            "moderation_reject_reason",
            moderator_user_id=cb.from_user.id,
            callback_data=cb.data,
            result="fail",
        )
        return

    ad_id = int(parts[1])
    field_key = parts[2]

    async with get_sessionmaker()() as session:
        repo = AdRepo(session)
        ad = await repo.get(ad_id)
        if not ad:
            log_event(
                logger,
                "moderation_reject_reason",
                moderator_user_id=cb.from_user.id,
                callback_data=cb.data,
                ad_id=ad_id,
                field_key=field_key,
                result="not_found",
            )
            return await safe_answer(cb, "❌ Не найдено", alert=True)

        payload = ad.payload or {}
        role = (payload.get("role") or getattr(ad, "role", None) or "employer").strip().lower()

        reason = _reason_text(role, field_key)

        log_event(
            logger,
            "moderation_reject_reason",
            moderator_user_id=cb.from_user.id,
            callback_data=cb.data,
            ad_id=ad_id,
            field_key=field_key,
            role=role,
            result="ok",
        )

        # 1) сохраняем причину
        await repo.patch_payload(ad_id, rejection_field=field_key, rejection_reason=reason)

        # 2) статус
        try:
            await repo.set_status(ad_id, "rejected")
        except Exception:
            await repo.set_status(ad_id, "draft")

        # 3) вписываем причину в сообщение модерации (НЕ теряя тех-инфо)
        await _edit_mod_message_keep_header(cb, reason)

        # 4) сообщение пользователю + кнопка точечного исправления (как на скрине)
        author_id = payload.get("author_id") or getattr(ad, "author_id", None)
        if not author_id:
            log_event(
                logger,
                "moderation_reject_notify",
                moderator_user_id=cb.from_user.id,
                ad_id=ad_id,
                field_key=field_key,
                result="fail",
            )
            return await safe_answer(cb, "Отклонено", alert=True)

        fix_cb = _fix_callback(role, field_key, ad_id)
        if not fix_cb:
            return await safe_answer(cb, "Отклонено", alert=True)

        try:
            msg = await cb.bot.send_message(
                int(author_id),
                rejected_user_text(reason),
                reply_markup=_user_fix_keyboard_for_field(field_key, fix_cb),
            )

            await repo.patch_payload(
                ad_id,
                reject_notice_chat_id=int(msg.chat.id),
                reject_notice_message_id=int(msg.message_id),
                rejected_field=str(field_key),
                rejected_reason=str(reason),
            )

            log_event(
                logger,
                "moderation_reject_notify",
                moderator_user_id=cb.from_user.id,
                author_id=author_id,
                ad_id=ad_id,
                field_key=field_key,
                result="ok",
            )
        except Exception:
            log_event(
                logger,
                "moderation_reject_notify",
                moderator_user_id=cb.from_user.id,
                author_id=author_id,
                ad_id=ad_id,
                field_key=field_key,
                result="fail",
            )
            pass

    return await safe_answer(cb, "Отклонено", alert=True)
