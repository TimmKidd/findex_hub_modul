from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Iterable

from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    Message,
)

NOOP_CALLBACK = "noop"
DAILY_FREE_LIMIT = 3
UNLIMITED_USERNAMES = {"findexhub_manager", "timmkidd"}

K_CLEANUP_IDS = "draft_cleanup_ids"
K_CLEANUP_CHAT_ID = "draft_cleanup_chat_id"

CONTACT_MODE_CONTACTS = "contacts"
CONTACT_MODE_BOT = "bot"
CONTACT_MODE_BOTH = "both"

CB_CONTACT_MODE_SET = "contact_mode_set"
CB_CONTACT_MODE_INFO = "contact_mode_info"

CB_REPUBLISH = "republish"
CB_PUBLISHED_TOGGLE = "pubpv_toggle"
CB_SHARE_AD = "share_ad"
CB_TEASER_SHARE_HELP = "teaser_share_help"


def published_preview_kb(ad_id: int, collapsed: bool = False) -> InlineKeyboardMarkup:
    toggle_text = "🔽 Развернуть" if collapsed else "🔼 Свернуть"
    toggle_action = "expand" if collapsed else "collapse"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=toggle_text,
                    callback_data=f"{CB_PUBLISHED_TOGGLE}:{int(ad_id)}:{toggle_action}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📢 Поделиться вакансией",
                    switch_inline_query=f"share_ad_{int(ad_id)}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔁 Повторить публикацию",
                    callback_data=f"{CB_REPUBLISH}:{int(ad_id)}",
                ),
            ],
        ]
    )


def teaser_share_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📣 Поделиться вакансией", callback_data=CB_TEASER_SHARE_HELP)]
        ]
    )


def contact_mode_keyboard(ad_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔓 Контакты в объявлении", callback_data=f"{CB_CONTACT_MODE_SET}:{ad_id}:{CONTACT_MODE_CONTACTS}")],
            [InlineKeyboardButton(text="🔐 Отклики через бота", callback_data=f"{CB_CONTACT_MODE_SET}:{ad_id}:{CONTACT_MODE_BOT}")],
            [InlineKeyboardButton(text="🔀 Оба варианта", callback_data=f"{CB_CONTACT_MODE_SET}:{ad_id}:{CONTACT_MODE_BOTH}")],
            [InlineKeyboardButton(text="ℹ️ В чём разница?", callback_data=f"{CB_CONTACT_MODE_INFO}:{ad_id}")],
        ]
    )


def contact_mode_info_text() -> str:
    return (
        "🔍 <b>Разница между режимами</b>\n\n"
        "🔓 <b>Контакты в объявлении</b>\n"
        "Люди пишут тебе напрямую в личку/звонят.\n"
        "Быстро, привычно, удобно (но это не точно)\n\n"
        "🔐 <b>Отклики через бота</b>\n"
        "Все отклики приходят сюда, с кнопками “ответить / пригласить / закрыть”.\n"
        "Быстро, конфиденциально, безопасно, в любой момент можешь продолжить общение напрямую.\n"
        "Есть статусы, напоминания и защита от спама.\n\n"
        "Ты всегда можешь изменить этот выбор позже."
    )


_UNLIMITED_IDS_CACHE_RAW: str | None = None
_UNLIMITED_IDS_CACHE_SET: set[int] = set()


def _get_unlimited_user_ids() -> set[int]:
    global _UNLIMITED_IDS_CACHE_RAW, _UNLIMITED_IDS_CACHE_SET

    raw = (os.getenv("UNLIMITED_USER_IDS") or "").strip()
    if raw == (_UNLIMITED_IDS_CACHE_RAW or ""):
        return _UNLIMITED_IDS_CACHE_SET

    out: set[int] = set()
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.add(int(part))
            except Exception:
                continue

    _UNLIMITED_IDS_CACHE_RAW = raw
    _UNLIMITED_IDS_CACHE_SET = out
    return out


def is_unlimited_user_id(user_id: int | None) -> bool:
    if not user_id:
        return False
    try:
        uid = int(user_id)
    except Exception:
        return False
    return uid in _get_unlimited_user_ids()


def is_unlimited_user(username: str | None) -> bool:
    if not username:
        return False
    return username.strip().lstrip("@").lower() in UNLIMITED_USERNAMES


def is_unlimited(user_id: int | None, username: str | None = None) -> bool:
    if is_unlimited_user_id(user_id):
        return True
    return is_unlimited_user(username)


def utc_day_key(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d")


def utc_seconds_to_reset(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    tomorrow_utc_midnight = (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
    sec = int((tomorrow_utc_midnight - now).total_seconds())
    return max(0, sec)


def format_hhmmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


async def safe_answer(cb: CallbackQuery, text: str | None = None, alert: bool = False):
    try:
        if text is None:
            await cb.answer()
        else:
            await cb.answer(text, show_alert=alert)
    except Exception:
        pass


async def send_saved_hint(message_or_cb: Message | CallbackQuery):
    try:
        if isinstance(message_or_cb, Message):
            return await message_or_cb.answer("✅ Изменения сохранены")
        else:
            if message_or_cb.message:
                return await message_or_cb.message.answer("✅ Изменения сохранены")
            return await message_or_cb.bot.send_message(message_or_cb.from_user.id, "✅ Изменения сохранены")
    except Exception:
        return None


def _extract_msg_id_and_chat_id(obj: Any) -> tuple[int | None, int | None]:
    if obj is None:
        return None, None

    if isinstance(obj, int):
        return int(obj), None

    msg_id = getattr(obj, "message_id", None)
    chat = getattr(obj, "chat", None)
    chat_id = getattr(chat, "id", None) if chat is not None else None

    try:
        msg_id = int(msg_id) if msg_id is not None else None
    except Exception:
        msg_id = None

    try:
        chat_id = int(chat_id) if chat_id is not None else None
    except Exception:
        chat_id = None

    return msg_id, chat_id


K_STEP_PROMPT_ID = "cleanup_step_prompt_id"
K_STEP_ERROR_ID = "cleanup_step_error_id"


async def reset_cleanup_bucket(state) -> None:
    try:
        await state.update_data(
            **{
                K_CLEANUP_IDS: [],
                K_CLEANUP_CHAT_ID: None,
                K_STEP_PROMPT_ID: None,
                K_STEP_ERROR_ID: None,
            }
        )
    except Exception:
        pass


async def track_cleanup_message(state, message_or_id: Any, chat_id: int | None = None) -> None:
    try:
        data = await state.get_data()
    except Exception:
        return

    ids = list(data.get(K_CLEANUP_IDS) or [])
    msg_id, obj_chat_id = _extract_msg_id_and_chat_id(message_or_id)

    if msg_id is None:
        return

    final_chat_id = chat_id or obj_chat_id or data.get(K_CLEANUP_CHAT_ID)

    if msg_id not in ids:
        ids.append(int(msg_id))

    try:
        await state.update_data(
            **{
                K_CLEANUP_IDS: ids,
                K_CLEANUP_CHAT_ID: int(final_chat_id) if final_chat_id is not None else data.get(K_CLEANUP_CHAT_ID),
            }
        )
    except Exception:
        pass


async def track_cleanup_messages(state, *messages_or_ids: Any, chat_id: int | None = None) -> None:
    for item in messages_or_ids:
        await track_cleanup_message(state, item, chat_id=chat_id)


async def cleanup_tracked_messages(
    bot,
    state,
    *,
    keep_ids: Iterable[int] | None = None,
    chat_id: int | None = None,
) -> None:
    try:
        data = await state.get_data()
    except Exception:
        return

    ids = [int(x) for x in (data.get(K_CLEANUP_IDS) or []) if x]
    if not ids:
        return

    final_chat_id = chat_id or data.get(K_CLEANUP_CHAT_ID)
    if not final_chat_id:
        return

    keep = {int(x) for x in (keep_ids or []) if x}
    new_bucket: list[int] = []

    for mid in ids:
        if mid in keep:
            new_bucket.append(mid)
            continue
        try:
            await bot.delete_message(chat_id=int(final_chat_id), message_id=int(mid))
        except Exception:
            pass

    try:
        await state.update_data(**{K_CLEANUP_IDS: new_bucket})
    except Exception:
        pass



async def clear_step_prompt(bot, state, *, chat_id: int | None = None) -> None:
    try:
        data = await state.get_data()
        mid = data.get(K_STEP_PROMPT_ID)
        cid = chat_id or data.get(K_CLEANUP_CHAT_ID)
        if mid and cid:
            with contextlib.suppress(Exception):
                await bot.delete_message(chat_id=int(cid), message_id=int(mid))
        await state.update_data(**{K_STEP_PROMPT_ID: None})
    except Exception:
        pass


async def clear_step_error(bot, state, *, chat_id: int | None = None) -> None:
    try:
        data = await state.get_data()
        mid = data.get(K_STEP_ERROR_ID)
        cid = chat_id or data.get(K_CLEANUP_CHAT_ID)
        if mid and cid:
            with contextlib.suppress(Exception):
                await bot.delete_message(chat_id=int(cid), message_id=int(mid))
        await state.update_data(**{K_STEP_ERROR_ID: None})
    except Exception:
        pass


async def replace_step_prompt(
    bot,
    state,
    *,
    chat_id: int,
    text: str,
    reply_markup=None,
    parse_mode=None,
):
    await clear_step_prompt(bot, state, chat_id=chat_id)

    msg = await bot.send_message(
        chat_id=int(chat_id),
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )

    try:
        await track_cleanup_message(state, msg, chat_id=int(chat_id))
    except Exception:
        pass

    try:
        await state.update_data(
            **{
                K_STEP_PROMPT_ID: int(msg.message_id),
                K_CLEANUP_CHAT_ID: int(chat_id),
            }
        )
    except Exception:
        pass

    return msg


async def replace_step_error(
    bot,
    state,
    *,
    chat_id: int,
    text: str,
    reply_markup=None,
    parse_mode=None,
):
    await clear_step_error(bot, state, chat_id=chat_id)

    msg = await bot.send_message(
        chat_id=int(chat_id),
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )

    try:
        await track_cleanup_message(state, msg, chat_id=int(chat_id))
    except Exception:
        pass

    try:
        await state.update_data(
            **{
                K_STEP_ERROR_ID: int(msg.message_id),
                K_CLEANUP_CHAT_ID: int(chat_id),
            }
        )
    except Exception:
        pass

    return msg


async def delete_user_input_message(bot, message) -> None:
    try:
        await bot.delete_message(
            chat_id=int(message.chat.id),
            message_id=int(message.message_id),
        )
    except Exception:
        pass


def sent_to_moderation_stub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏳ Объявление отправлено на модерацию", callback_data=NOOP_CALLBACK)]
        ]
    )


MEDIA_CONFIRMED_CALLBACK = "media_confirmed"


def media_confirmed_stub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Подтверждено", callback_data=MEDIA_CONFIRMED_CALLBACK)]
        ]
    )


def field_title(field_key: str) -> str:
    key = (field_key or "").strip().lower()
    mapping = {
        "title": "Должность",
        "schedule": "График",
        "salary": "Зарплата",
        "location": "Локация",
        "contacts": "Контакты",
        "description": "Описание",
        "about": "О себе",
        "media": "Медиа",
        "photo": "Фото",
        "video": "Видео",
    }
    return mapping.get(key, "Поле")


def rejected_user_text(reason: str) -> str:
    return (
        "❌ Объявление отклонено модератором.\n\n"
        f"Причина: <b>{reason}</b>\n\n"
        "Нажми кнопку ниже, чтобы сразу исправить."
    )


def employer_media_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить медиа", callback_data="emp_media_add")],
            [InlineKeyboardButton(text="⏭ Без медиа", callback_data="emp_media_skip")],
        ]
    )


def seeker_media_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить медиа", callback_data="seek_media_add")],
            [InlineKeyboardButton(text="⏭ Без медиа", callback_data="seek_media_skip")],
        ]
    )


def media_confirm_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"{prefix}:ok"),
                InlineKeyboardButton(text="🔁 Заменить", callback_data=f"{prefix}:retry"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"{prefix}:delete"),
            ]
        ]
    )


def employer_preview_keyboard(ad_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 Исправить должность", callback_data=f"emp_edit_title:{ad_id}"),
                InlineKeyboardButton(text="💲 Исправить зарплату", callback_data=f"emp_edit_salary:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="📍 Исправить локацию", callback_data=f"emp_edit_location:{ad_id}"),
                InlineKeyboardButton(text="📞 Исправить контакты", callback_data=f"emp_edit_contacts:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="📝 Исправить описание", callback_data=f"emp_edit_description:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="🎞 Исправить медиа", callback_data=f"emp_edit_media:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="✅ Отправить на модерацию", callback_data=f"send_employer:{ad_id}"),
            ],
        ]
    )


def seeker_preview_keyboard(ad_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 Исправить должность", callback_data=f"seek_edit_title:{ad_id}"),
                InlineKeyboardButton(text="🕒 Исправить график", callback_data=f"seek_edit_schedule:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="💲 Исправить зарплату", callback_data=f"seek_edit_salary:{ad_id}"),
                InlineKeyboardButton(text="📍 Исправить локацию", callback_data=f"seek_edit_location:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="📞 Исправить контакты", callback_data=f"seek_edit_contacts:{ad_id}"),
                InlineKeyboardButton(text="📝 Исправить о себе", callback_data=f"seek_edit_about:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="🎞 Исправить медиа", callback_data=f"seek_edit_media:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="✅ Отправить на модерацию", callback_data=f"send_seeker:{ad_id}"),
            ],
        ]
    )


def get_full_edit_keyboard(role: str, ad_id: int) -> InlineKeyboardMarkup:
    r = (role or "").strip().lower()
    return seeker_preview_keyboard(ad_id) if r == "seeker" else employer_preview_keyboard(ad_id)


def moderation_keyboard(ad_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{ad_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{ad_id}"),
            ]
        ]
    )


def rejection_reasons_kb(ad_id: int, role: str) -> InlineKeyboardMarkup:
    role = (role or "").strip().lower()

    if role == "seeker":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="👤 Должность некорректная", callback_data=f"rejr:{ad_id}:title")],
                [InlineKeyboardButton(text="🕒 График некорректный", callback_data=f"rejr:{ad_id}:schedule")],
                [InlineKeyboardButton(text="💲 Зарплата некорректная", callback_data=f"rejr:{ad_id}:salary")],
                [InlineKeyboardButton(text="📍 Локация некорректная", callback_data=f"rejr:{ad_id}:location")],
                [InlineKeyboardButton(text="📞 Контакты некорректные", callback_data=f"rejr:{ad_id}:contacts")],
                [InlineKeyboardButton(text="📝 О себе некорректно", callback_data=f"rejr:{ad_id}:about")],
                [InlineKeyboardButton(text="🖼 Фото некорректное", callback_data=f"rejr:{ad_id}:media")],
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Должность некорректная", callback_data=f"rejr:{ad_id}:title")],
            [InlineKeyboardButton(text="💲 Зарплата некорректная", callback_data=f"rejr:{ad_id}:salary")],
            [InlineKeyboardButton(text="📍 Локация некорректная", callback_data=f"rejr:{ad_id}:location")],
            [InlineKeyboardButton(text="📞 Контакты некорректные", callback_data=f"rejr:{ad_id}:contacts")],
            [InlineKeyboardButton(text="📝 Описание некорректное", callback_data=f"rejr:{ad_id}:description")],
            [InlineKeyboardButton(text="🎞 Медиа некорректное", callback_data=f"rejr:{ad_id}:media")],
        ]
    )


def rejection_keyboard(ad_id: int, role: str) -> InlineKeyboardMarkup:
    return rejection_reasons_kb(ad_id, role)