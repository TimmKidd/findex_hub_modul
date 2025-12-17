# === forms.py ===
from __future__ import annotations

import uuid
import logging
from typing import Optional, Tuple

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LinkPreviewOptions,
)

from findex_bot.states.vacancies import EmployerForm, SeekerForm
from findex_bot.utils.ui_utils import (
    moderation_keyboard,
    rejection_keyboard,
    send_ad_preview,
    get_full_edit_keyboard,
    NOOP_CALLBACK,
)

logger = logging.getLogger(__name__)

router = Router()

# ------------------------------------------------------
# SAFE ANSWER / SAFE EDIT
# ------------------------------------------------------


async def _safe_answer(callback: CallbackQuery, text: str | None = None, show_alert: bool = False):
    try:
        if text is None:
            await callback.answer()
        else:
            await callback.answer(text, show_alert=show_alert)
    except Exception:
        pass


async def _safe_edit(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: ParseMode | None = None,
    disable_preview: bool = False,
    allow_fallback: bool = True,  # allow_fallback=False → не создаём новое сообщение (важно для мод-чата)
):
    msg = callback.message
    try:
        # Текстовое сообщение
        if getattr(msg, "text", None):
            return await msg.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                link_preview_options=LinkPreviewOptions(is_disabled=True) if disable_preview else None,
            )

        # Фото/видео сообщение (caption)
        if getattr(msg, "caption", None) is not None:
            return await msg.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
    except Exception:
        if not allow_fallback:
            return None

    if allow_fallback:
        try:
            return await callback.bot.send_message(
                chat_id=msg.chat.id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                link_preview_options=LinkPreviewOptions(is_disabled=True) if disable_preview else None,
            )
        except Exception:
            return None


def _get_msg_text_or_caption(callback: CallbackQuery) -> str:
    msg = callback.message
    return (getattr(msg, "text", None) or getattr(msg, "caption", None) or "").strip()


def _append_once(base: str, add: str) -> str:
    add_clean = (add or "").strip()
    if not add_clean:
        return base
    if add_clean in (base or ""):
        return base
    return f"{base.rstrip()}\n\n{add_clean}" if (base or "").strip() else add_clean


# ------------------------------------------------------
# CORE ACCESS
# ------------------------------------------------------


def _core():
    # ВАЖНО: импорт внутри функции — так мы избегаем циклических импортов
    from findex_bot import bot
    return bot


def _get_pending_storage():
    c = _core()
    c.ADS_PENDING = getattr(c, "ADS_PENDING", {}) or {}
    return c.ADS_PENDING


def _get_rejected_storage():
    c = _core()
    c.ADS_REJECTED = getattr(c, "ADS_REJECTED", {}) or {}
    return c.ADS_REJECTED


def _get_published_storage():
    """
    В bot.py у тебя это называется PUBLISHED_POSTS.
    Делаем совместимо: если где-то раньше было ADS_PUBLISHED — тоже поддержим.
    """
    c = _core()
    if hasattr(c, "PUBLISHED_POSTS"):
        c.PUBLISHED_POSTS = getattr(c, "PUBLISHED_POSTS", {}) or {}
        return c.PUBLISHED_POSTS
    c.ADS_PUBLISHED = getattr(c, "ADS_PUBLISHED", {}) or {}
    return c.ADS_PUBLISHED


def _get_mod_chat_id() -> Optional[int]:
    try:
        return int(_core().config.moderation_chat_id)
    except Exception:
        return None


def _get_main_channel_id() -> Optional[int]:
    try:
        return int(_core().config.main_channel_id)
    except Exception:
        return None


def _get_channel_username() -> str:
    try:
        return (_core().config.channel_username or "").lstrip("@")
    except Exception:
        return ""


# ------------------------------------------------------
# LIMITS (3 бесплатных в день) — БЕЗ циклического импорта
# ------------------------------------------------------


def _limits_record_published(user_id: int) -> int | str | None:
    """
    Увеличивает счётчик ТОЛЬКО после успешной публикации.
    Возвращает сколько осталось (0..3) или "∞".
    """
    try:
        c = _core()
        fn = getattr(c, "record_published", None)
        if callable(fn):
            return fn(int(user_id))
    except Exception:
        logger.exception("LIMITS: record_published failed user_id=%s", user_id)
    return None


def _limits_get_remaining(user_id: int) -> int | str | None:
    """Сколько осталось сегодня (не увеличивает)."""
    try:
        c = _core()
        fn = getattr(c, "get_remaining_today", None)
        if callable(fn):
            return fn(int(user_id))
    except Exception:
        logger.exception("LIMITS: get_remaining_today failed user_id=%s", user_id)
    return None


# ------------------------------------------------------
# PARSERS
# ------------------------------------------------------


def _parse_ad_id(data: str) -> Optional[str]:
    """
    Поддержка:
    mod_approve:<ad_id>
    mod_reject:<ad_id>
    open_post:<ad_id>
    а также варианты с | и _
    """
    if not data:
        return None
    for sep in (":", "|", "_"):
        if sep in data:
            p = data.split(sep, 1)
            if len(p) == 2 and p[1].strip():
                return p[1].strip()
    return None


def _parse_mod_reason(data: str) -> Tuple[Optional[str], Optional[str]]:
    """
    mod_reason:<ad_id>:<field>
    """
    if not data or not data.startswith("mod_reason:"):
        return None, None
    parts = data.split(":")
    if len(parts) >= 3:
        return (parts[1].strip() or None, parts[2].strip() or None)
    return None, None


# ------------------------------------------------------
# UI: LOCKED KEYBOARD (после отправки на модерацию)
# ------------------------------------------------------


def _locked_keyboard() -> InlineKeyboardMarkup:
    # Одна кнопка-заглушка, остальные кнопки исчезают → редактирование невозможно
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏳ Объявление отправлено на модерацию", callback_data=NOOP_CALLBACK)]
        ]
    )


# ------------------------------------------------------
# NOOP (кнопка заблокирована)
# ------------------------------------------------------


@router.callback_query(F.data == NOOP_CALLBACK)
async def noop_callback(callback: CallbackQuery):
    await _safe_answer(callback, "⏳ Уже отправлено на модерацию", show_alert=True)


# ------------------------------------------------------
# SEND TO MODERATION (ANTI-SPAM + сохраняем полный предпросмотр)
# ------------------------------------------------------


@router.callback_query(F.data.in_(["seek_send_mod", "emp_send_mod"]))
async def send_to_moderation(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)

    data = await state.get_data()
    if data.get("on_moderation"):
        await _safe_answer(callback, "⏳ Уже отправлено на модерацию", show_alert=True)
        return

    mod_chat_id = _get_mod_chat_id()
    if not mod_chat_id:
        return

    ad_id = uuid.uuid4().hex[:12]

    payload = dict(data)
    payload["author_id"] = callback.from_user.id

    # сохраняем, какое сообщение у пользователя является предпросмотром (чтобы потом обновить ЕГО)
    payload["user_chat_id"] = callback.from_user.id
    payload["user_message_id"] = callback.message.message_id
    payload["user_has_caption"] = (getattr(callback.message, "caption", None) is not None)

    role = payload.get("role", "Работодатель")
    payload["role"] = role

    _get_pending_storage()[ad_id] = payload

    # 1) в мод-чат — полноценная карточка
    await send_ad_preview(
        chat_id=mod_chat_id,
        ad_data=payload,
        bot=callback.bot,
        reply_markup=moderation_keyboard(ad_id),
    )

    # 2) блокируем повторную отправку
    await state.update_data(on_moderation=True)

    # 3) У пользователя: ЛОЧИМ ВСЕ КНОПКИ ОДНОЙ ЗАГЛУШКОЙ (по задаче)
    original_text = _get_msg_text_or_caption(callback)
    if not original_text:
        try:
            from findex_bot.utils.vacancy_utils import get_ad_text
            original_text = get_ad_text(payload, include_author=False)
        except Exception:
            original_text = "⏳ Объявление отправлено на модерацию"

    await _safe_edit(
        callback,
        original_text,
        reply_markup=_locked_keyboard(),
        parse_mode=ParseMode.HTML,
        disable_preview=True,
        allow_fallback=True,  # пользователю можно fallback
    )


# ------------------------------------------------------
# MODERATION: APPROVE
# ------------------------------------------------------


@router.callback_query(F.data.startswith("mod_approve"))
async def mod_approve_callback(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)

    ad_id = _parse_ad_id(callback.data or "")
    if not ad_id:
        return

    pending = _get_pending_storage()
    ad = pending.get(ad_id)
    if not ad:
        return

    main_channel = _get_main_channel_id()
    if not main_channel:
        return

    # текст объявления
    try:
        from findex_bot.utils.vacancy_utils import get_ad_text
        text = get_ad_text(ad, include_author=False)
    except Exception:
        text = ""

    # публикуем (с медиа, если оно есть)
    media_id = ad.get("media_id")
    media_type = ad.get("media_type")

    if media_id and media_type == "photo":
        sent = await callback.bot.send_photo(
            chat_id=main_channel,
            photo=media_id,
            caption=text,
            parse_mode=ParseMode.HTML,
        )
    elif media_id and media_type == "video":
        sent = await callback.bot.send_video(
            chat_id=main_channel,
            video=media_id,
            caption=text,
            parse_mode=ParseMode.HTML,
        )
    else:
        sent = await callback.bot.send_message(
            chat_id=main_channel,
            text=text,
            parse_mode=ParseMode.HTML,
        )

    username = _get_channel_username()
    url = f"https://t.me/{username}/{sent.message_id}" if username else ""

    _get_published_storage()[ad_id] = {
        "chat_id": main_channel,
        "message_id": sent.message_id,
        "url": url,
    }

    # ✅ фиксируем лимит ПОСЛЕ успешной публикации
    author_id = ad.get("author_id") or ad.get("user_chat_id")
    remaining_after = None
    if author_id:
        remaining_after = _limits_record_published(int(author_id))

    # --------------------------------------------------
    # 1) ОБНОВЛЯЕМ ПРЕДПРОСМОТР У ПОЛЬЗОВАТЕЛЯ (В ЭТОМ ЖЕ СООБЩЕНИИ)
    #    reply_markup=None (после публикации кнопки не нужны)
    # --------------------------------------------------
    try:
        user_chat_id = ad.get("user_chat_id") or ad.get("author_id")
        user_message_id = ad.get("user_message_id")
        user_has_caption = bool(ad.get("user_has_caption"))

        parts = []
        parts.append("✅ <b>Опубликовано</b>")

        if url:
            parts.append(f"🔗 Ссылка: {url}")

        if remaining_after is None and user_chat_id:
            remaining_after = _limits_get_remaining(int(user_chat_id))

        if remaining_after is not None:
            if remaining_after == "∞":
                parts.append("📩 Бесплатные публикации сегодня: ∞")
            else:
                parts.append(f"📩 Бесплатные публикации сегодня: {int(remaining_after)}/3")

        parts.append("ℹ️ Чтобы создать новое объявление — нажми /start")

        status_user = "\n\n" + "\n\n".join(parts)
        final_text = (text or "").strip() + status_user

        if user_chat_id and user_message_id:
            if user_has_caption:
                await callback.bot.edit_message_caption(
                    chat_id=int(user_chat_id),
                    message_id=int(user_message_id),
                    caption=final_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=None,
                )
            else:
                await callback.bot.edit_message_text(
                    chat_id=int(user_chat_id),
                    message_id=int(user_message_id),
                    text=final_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=None,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
    except Exception:
        logger.exception(
            "APPROVE: failed to update user preview ad_id=%s user_chat_id=%s user_message_id=%s user_has_caption=%s",
            ad_id,
            ad.get("user_chat_id"),
            ad.get("user_message_id"),
            ad.get("user_has_caption"),
        )

    # --------------------------------------------------
    # 2) В МОД-ЧАТЕ ОБНОВЛЯЕМ СООБЩЕНИЕ СТАТУСОМ (служебно, как и было)
    # --------------------------------------------------
    moderator_u = callback.from_user.username
    moderator_text = f"@{moderator_u}" if moderator_u else f"id{callback.from_user.id}"

    status_mod = (
        "✅ Опубликовано!\n"
        f"Модератор: {moderator_text}\n"
        f"Ссылка: {url}"
    )

    new_text = _append_once(_get_msg_text_or_caption(callback), status_mod)

    await _safe_edit(
        callback,
        new_text,
        reply_markup=None,
        parse_mode=ParseMode.HTML,
        disable_preview=True,
        allow_fallback=False,  # мод-чат — никаких новых сообщений
    )

    pending.pop(ad_id, None)


# ------------------------------------------------------
# MODERATION: REJECT (меняем только клавиатуру причин)
# ------------------------------------------------------


@router.callback_query(F.data.startswith("mod_reject"))
async def mod_reject_callback(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)

    ad_id = _parse_ad_id(callback.data or "")
    if not ad_id:
        return

    await state.clear()
    await state.update_data(mod_reject_ad_id=ad_id)

    try:
        await callback.message.edit_reply_markup(reply_markup=rejection_keyboard(ad_id))
    except Exception:
        original = _get_msg_text_or_caption(callback)
        await _safe_edit(
            callback,
            original,
            reply_markup=rejection_keyboard(ad_id),
            parse_mode=ParseMode.HTML,
            disable_preview=True,
            allow_fallback=False,  # мод-чат
        )


# ------------------------------------------------------
# MODERATION: REASON → отклоняем и возвращаем автору на правку
# ------------------------------------------------------


def _reason_text(field: str) -> str:
    m = {
        "position": "Должность некорректная",
        "schedule": "График некорректный",
        "salary": "Зарплата некорректная",
        "location": "Локация некорректная",
        "contacts": "Контакты некорректные",
        "description": "Описание неправильное",
        "custom": "Другая причина",
    }
    return m.get(field, "Другая причина")


def _make_fix_keyboard(ad_id: str, field: str) -> InlineKeyboardMarkup:
    titles = {
        "position": "Должность",
        "schedule": "График",
        "salary": "Зарплата",
        "location": "Локация",
        "contacts": "Контакты",
        "description": "Описание",
        "custom": "Другое",
    }
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✏️ Исправить: {titles.get(field, 'Поле')}",
                    callback_data=f"fix_rej:{ad_id}:{field}",
                )
            ]
        ]
    )


@router.callback_query(F.data.startswith("mod_reason:"))
async def mod_reason_callback(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)

    ad_id, field = _parse_mod_reason(callback.data or "")
    if not ad_id:
        st = await state.get_data()
        ad_id = st.get("mod_reject_ad_id")

    if not ad_id:
        return

    field = (field or "custom").lower().strip()
    reason = _reason_text(field)

    pending = _get_pending_storage()
    ad = pending.get(ad_id)
    if not ad:
        await state.clear()
        return

    author_id = ad.get("author_id")

    _get_rejected_storage()[ad_id] = ad
    pending.pop(ad_id, None)

    if author_id:
        try:
            await callback.bot.send_message(
                chat_id=int(author_id),
                text=(
                    "❌ Объявление отклонено модератором.\n\n"
                    f"Причина: <b>{reason}</b>\n\n"
                    "Нажми кнопку ниже, чтобы сразу исправить."
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=_make_fix_keyboard(ad_id, field),
            )
        except Exception:
            pass

    status = f"✖ Отклонено: причина — {reason}"
    base = _get_msg_text_or_caption(callback)
    new_text = _append_once(base, status)

    await _safe_edit(
        callback,
        new_text,
        reply_markup=None,
        parse_mode=ParseMode.HTML,
        disable_preview=True,
        allow_fallback=False,
    )

    await state.clear()


# ------------------------------------------------------
# AUTHOR: FIX AFTER REJECTION → снимаем блокировку + force_preview
# ------------------------------------------------------


@router.callback_query(F.data.startswith("fix_rej:"))
async def fix_rejected_ad(callback: CallbackQuery, state: FSMContext):
    await _safe_answer(callback)

    parts = (callback.data or "").split(":")
    if len(parts) < 3:
        return

    ad_id = parts[1].strip()
    field = parts[2].strip().lower()

    rejected = _get_rejected_storage()
    ad_data = rejected.get(ad_id)
    if not ad_data:
        await _safe_answer(callback, "Объявление не найдено", show_alert=True)
        return

    role = ad_data.get("role", "Работодатель")

    # ✅ Грузим данные, снимаем блокировку и включаем принудительный предпросмотр
    await state.clear()
    await state.update_data(**ad_data)
    await state.update_data(on_moderation=False, is_inline_edit=True, force_preview=True)

    if role == "Соискатель":
        mapping = {
            "position": SeekerForm.position,
            "schedule": SeekerForm.schedule,
            "salary": SeekerForm.salary,
            "location": SeekerForm.location,
            "contacts": SeekerForm.contacts,
            "description": SeekerForm.description,
        }
    else:
        mapping = {
            "position": EmployerForm.position,
            "salary": EmployerForm.salary,
            "location": EmployerForm.location,
            "contacts": EmployerForm.contacts,
            "description": EmployerForm.description,
        }

    target_state = mapping.get(field)
    if not target_state:
        await _safe_answer(callback, "Поле не поддерживается", show_alert=True)
        return

    await state.set_state(target_state)

    prompts = {
        "position": "Введи исправленную 👤 должность:",
        "schedule": "Введи исправленный 🕒 график:",
        "salary": "Введи исправленную 💲 зарплату:",
        "location": "Введи исправленную 📍 локацию:",
        "contacts": "Введи исправленные ☎️ контакты:",
        "description": "Введи исправленное 📝 описание:",
        "custom": "Введи исправления:",
    }

    try:
        await callback.message.answer(prompts.get(field, "Введи исправленное значение:"))
    except Exception:
        try:
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text=prompts.get(field, "Введи исправленное значение:"),
            )
        except Exception:
            pass
