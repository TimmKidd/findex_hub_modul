# findex_bot/utils/ui_utils.py
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message


# ✅ единый noop для заглушек
NOOP_CALLBACK = "noop"

# ✅ лимит
DAILY_FREE_LIMIT = 3

# ✅ безлимитные юзеры (username без @, в lower)
UNLIMITED_USERNAMES = {"findexhub_manager", "timmkidd"}


def is_unlimited_user(username: str | None) -> bool:
    if not username:
        return False
    return username.strip().lstrip("@").lower() in UNLIMITED_USERNAMES


def utc_day_key(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d")


def utc_seconds_to_reset(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    # следующий 00:00 UTC
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
    """
    ✅ Изменения сохранены (как у тебя на скрине)
    """
    try:
        if isinstance(message_or_cb, Message):
            await message_or_cb.answer("✅ Изменения сохранены")
        else:
            if message_or_cb.message:
                await message_or_cb.message.answer("✅ Изменения сохранены")
            else:
                await message_or_cb.bot.send_message(message_or_cb.from_user.id, "✅ Изменения сохранены")
    except Exception:
        pass


def sent_to_moderation_stub_kb() -> InlineKeyboardMarkup:
    """
    ✅ Заглушка как на скрине: одна кнопка под предпросмотром, не отдельным сообщением.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏳ Объявление отправлено на модерацию", callback_data=NOOP_CALLBACK)]
        ]
    )


# -----------------------------
# Поля: человеко-читаемые названия
# -----------------------------
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


# -----------------------------
# Медиа: выбор и подтверждение
# -----------------------------
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
            [InlineKeyboardButton(text="➕ Добавить фото", callback_data="seek_media_add")],
            [InlineKeyboardButton(text="⏭ Без фото", callback_data="seek_media_skip")],
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


# -----------------------------
# Предпросмотр
# -----------------------------
def employer_preview_keyboard(ad_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 Должность", callback_data=f"emp_edit_title:{ad_id}"),
                InlineKeyboardButton(text="💲 Зарплата", callback_data=f"emp_edit_salary:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="📍 Локация", callback_data=f"emp_edit_location:{ad_id}"),
                InlineKeyboardButton(text="📞 Контакты", callback_data=f"emp_edit_contacts:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="📝 Описание", callback_data=f"emp_edit_description:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="🎞 Медиа", callback_data=f"emp_edit_media:{ad_id}"),
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
                InlineKeyboardButton(text="👤 Должность", callback_data=f"seek_edit_title:{ad_id}"),
                InlineKeyboardButton(text="🕒 График", callback_data=f"seek_edit_schedule:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="💲 Зарплата", callback_data=f"seek_edit_salary:{ad_id}"),
                InlineKeyboardButton(text="📍 Локация", callback_data=f"seek_edit_location:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="📞 Контакты", callback_data=f"seek_edit_contacts:{ad_id}"),
                InlineKeyboardButton(text="📝 О себе", callback_data=f"seek_edit_about:{ad_id}"),
            ],
            [
                InlineKeyboardButton(text="🖼 Фото", callback_data=f"seek_edit_media:{ad_id}"),
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
                [InlineKeyboardButton(text="📝 О себе заполнено некорректно", callback_data=f"rejr:{ad_id}:about")],
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
