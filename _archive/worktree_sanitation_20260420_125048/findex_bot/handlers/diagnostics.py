# findex_bot/handlers/diagnostics.py
from __future__ import annotations

import html
import logging
from typing import Tuple, List, Optional, Union

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

import findex_bot.runtime as runtime
from findex_bot.db.db import get_sessionmaker
from findex_bot.db.daily_limits import get_count as db_get_pub_count
from findex_bot.db.models import Ad
from findex_bot.utils.ui_utils import (
    DAILY_FREE_LIMIT,
    is_unlimited,  # ✅ единая истина: UNLIMITED_USER_IDS + fallback usernames
)

logger = logging.getLogger(__name__)
router = Router()

ALLOWED_STATUSES = {"member", "administrator", "creator"}

CB_MENU_DIAG = "menu_diag"
CB_MENU_BACK = "menu_diag_back"
CB_PENDING_OPEN = "diag_pending_open"


def _cfg():
    return getattr(runtime, "CONFIG", None)


def _target_chat() -> Optional[Union[str, int]]:
    """
    Берём настройки из runtime.CONFIG (их прокидывает bot.py при старте).
    Никаких load_dotenv/os.getenv здесь не делаем, чтобы не было расхождений.
    """
    cfg = _cfg()
    if not cfg:
        return None

    channel_username = (getattr(cfg, "channel_username", "") or "").lstrip("@").strip()
    channel_id = int(getattr(cfg, "main_channel_id", 0) or 0)

    if channel_username:
        return f"@{channel_username}"
    if channel_id:
        return channel_id
    return None


def _channel_url() -> Optional[str]:
    """
    Прямая ссылка возможна только если у канала есть public username.
    """
    cfg = _cfg()
    if not cfg:
        return None

    channel_username = (getattr(cfg, "channel_username", "") or "").lstrip("@").strip()
    if not channel_username:
        return None

    return f"https://t.me/{channel_username}"


def _plural_ads(n: int) -> str:
    n = abs(int(n))
    mod10 = n % 10
    mod100 = n % 100

    if mod10 == 1 and mod100 != 11:
        return "объявление"
    if 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
        return "объявления"
    return "объявлений"


def _diagnostics_kb(
    subscribe_url: str | None,
    pending_ads: list[Ad] | None = None,
    *,
    include_menu_back: bool = False,
) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []

    if subscribe_url:
        rows.append([InlineKeyboardButton(text="📣 Подписаться на канал", url=subscribe_url)])

    for ad in pending_ads or []:
        ad_id = int(getattr(ad, "id", 0) or 0)
        rows.append([
            InlineKeyboardButton(
                text=f"📄 Открыть объявление #{ad_id}",
                callback_data=f"{CB_PENDING_OPEN}:{ad_id}",
            )
        ])

    if include_menu_back:
        rows.append([InlineKeyboardButton(text="↩️ В меню", callback_data=CB_MENU_BACK)])

    if not rows:
        return None

    return InlineKeyboardMarkup(inline_keyboard=rows)


def pending_ad_nav_kb(*, include_menu_back: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="⬅️ В диагностику", callback_data=CB_MENU_DIAG)],
    ]
    if include_menu_back:
        rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=CB_MENU_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _check_subscription(bot, user_id: int) -> Tuple[bool, str]:
    """
    Возвращает (ok, human_text)
    """
    if int(user_id) in (getattr(runtime, "MODERATORS", set()) or set()):
        return True, "✅ Подписка: ок (модератор)"

    target = _target_chat()
    if not target:
        return False, "❌ Подписка: канал не настроен"

    try:
        member = await bot.get_chat_member(chat_id=target, user_id=int(user_id))
        status = getattr(member, "status", None)
        if status in ALLOWED_STATUSES:
            return True, "✅ Подписка: ок"

        subscribe_url = _channel_url()
        if subscribe_url:
            return False, f"❌ Подписка: нет (не подписан)\n👉 Подписаться: {subscribe_url}"
        return False, "❌ Подписка: нет (не подписан)"
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "member not found" in msg:
            logger.info(
                "diagnostics: user_id=%s target=%s not subscribed (member not found)",
                user_id,
                target,
            )
            subscribe_url = _channel_url()
            if subscribe_url:
                return False, f"❌ Подписка: нет (не подписан)\n👉 Подписаться: {subscribe_url}"
            return False, "❌ Подписка: нет (не подписан)"

        logger.warning(
            "diagnostics: get_chat_member bad request user_id=%s target=%s err=%r",
            user_id,
            target,
            e,
        )
        subscribe_url = _channel_url()
        if subscribe_url:
            return False, f"❌ Подписка: ошибка проверки (Telegram)\n👉 Подписаться: {subscribe_url}"
        return False, "❌ Подписка: ошибка проверки (Telegram)"
    except Exception:
        logger.exception(
            "diagnostics: get_chat_member unexpected error user_id=%s target=%s",
            user_id,
            target,
        )
        subscribe_url = _channel_url()
        if subscribe_url:
            return False, f"❌ Подписка: ошибка проверки (Telegram)\n👉 Подписаться: {subscribe_url}"
        return False, "❌ Подписка: ошибка проверки (Telegram)"


async def _limits_line(user_id: int, username: str | None) -> Optional[str]:
    """
    ✅ ПРАВИЛО ПРОЕКТА:
    - для безлимитных (UNLIMITED_USER_IDS в env + fallback usernames) лимиты НЕ ПОКАЗЫВАЕМ ВООБЩЕ.
    - для модераторов — тоже НЕ ПОКАЗЫВАЕМ (у них публикация не должна быть ограничена).
    - для обычных — берём truth-source из Postgres (daily_pub_limits), как в forms.py/menu.py.

    Возвращает строку или None (если строку показывать нельзя).
    """
    try:
        uid = int(user_id)

        if uid in (getattr(runtime, "MODERATORS", set()) or set()):
            return None

        if is_unlimited(uid, username):
            return None

        published = 0
        try:
            async with get_sessionmaker()() as session:
                published = await db_get_pub_count(session, uid)
                await session.commit()
        except Exception:
            published = 0

        limit = int(DAILY_FREE_LIMIT)
        remaining = max(0, limit - int(published))

        if remaining > 0:
            return f"✅ Лимиты: ок (осталось на сегодня UTC: {remaining}/{limit})"
        return f"❌ Лимиты: исчерпан (0/{limit})"
    except Exception:
        return "⚠️ Лимиты: не удалось проверить"


def _blocks_line(user_id: int) -> str:
    blocked = getattr(runtime, "BLOCKED_USERS", set()) or set()
    return "❌ Блокировки: есть" if int(user_id) in blocked else "✅ Блокировки: нет"


async def _get_pending_ads(user_id: int) -> list[Ad]:
    try:
        async with get_sessionmaker()() as session:
            stmt = (
                select(Ad)
                .where(
                    Ad.author_user_id == int(user_id),
                    Ad.status == "pending",
                )
                .order_by(Ad.updated_at.desc(), Ad.id.desc())
            )
            res = await session.execute(stmt)
            return list(res.scalars().all())
    except Exception:
        logger.exception("diagnostics: failed to load pending ads user_id=%s", user_id)
        return []


async def get_pending_ad_for_user(user_id: int, ad_id: int) -> Ad | None:
    try:
        async with get_sessionmaker()() as session:
            stmt = select(Ad).where(
                Ad.id == int(ad_id),
                Ad.author_user_id == int(user_id),
                Ad.status == "pending",
            )
            res = await session.execute(stmt)
            return res.scalar_one_or_none()
    except Exception:
        logger.exception(
            "diagnostics: failed to load pending ad user_id=%s ad_id=%s",
            user_id,
            ad_id,
        )
        return None


async def _moderation_state(user_id: int) -> tuple[str, list[Ad]]:
    try:
        pending_ads = await _get_pending_ads(int(user_id))
        count = len(pending_ads)

        if count <= 0:
            return "✅ Модерация: нет объявлений на проверке", []

        word = _plural_ads(count)
        if count == 1:
            return f"🟡 Модерация: {count} {word} ожидает проверки", pending_ads
        return f"🟡 Модерация: {count} {word} ожидают проверки", pending_ads
    except Exception:
        logger.exception("diagnostics: failed to build moderation state user_id=%s", user_id)
        return "⚠️ Модерация: не удалось проверить", []


def _final_line(lines: List[str]) -> str:
    if any(l.startswith("❌") for l in lines):
        return "❌ Есть проблемы — смотри строки выше."
    return "✅ Всё ок — публикация должна проходить."


def _payload_value(payload: dict, *keys: str) -> str:
    for key in keys:
        val = payload.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return ""


def render_pending_ad_text(ad: Ad) -> str:
    """
    Оставляем только как fallback/debug. Основной UX теперь должен открывать
    живой preview с медиа через menu.py.
    """
    payload = getattr(ad, "payload", None) or {}
    ad_id = int(getattr(ad, "id", 0) or 0)
    role = str(getattr(ad, "role", "") or "").strip().lower()

    title = _payload_value(payload, "title", "position", "job_title", "role")
    salary = _payload_value(payload, "salary")
    location = _payload_value(payload, "location", "city", "metro")
    contacts = _payload_value(payload, "contacts", "contact", "phone", "telegram")
    employer = _payload_value(payload, "employer", "company", "company_name")
    schedule = _payload_value(payload, "schedule", "employment", "work_format")
    description = _payload_value(payload, "description", "desc", "details", "text", "about", "about_me", "bio")

    lines: list[str] = [
        f"📄 <b>Объявление #{ad_id}</b>",
        "",
        "Статус: 🟡 <b>На модерации</b>",
        "",
    ]

    if role == "seeker":
        lines.append("🙋 <b>Соискатель</b>")
        if title:
            lines.append(f"Должность: {html.escape(title)}")
        if schedule:
            lines.append(f"График: {html.escape(schedule)}")
        if salary:
            lines.append(f"Зарплата: {html.escape(salary)}")
        if location:
            lines.append(f"Локация: {html.escape(location)}")
        if contacts:
            lines.append(f"Контакты: {html.escape(contacts)}")
        if description:
            lines.append(f"О себе: {html.escape(description)}")
    else:
        lines.append("💼 <b>Работодатель</b>")
        if employer:
            lines.append(f"Работодатель: {html.escape(employer)}")
        if title:
            lines.append(f"Должность: {html.escape(title)}")
        if salary:
            lines.append(f"Зарплата: {html.escape(salary)}")
        if location:
            lines.append(f"Локация: {html.escape(location)}")
        if contacts:
            lines.append(f"Контакты: {html.escape(contacts)}")
        if description:
            lines.append(f"Описание: {html.escape(description)}")

    return "\n".join(lines)


async def build_diagnostics_view(
    user_id: int,
    username: str | None,
    bot,
    *,
    include_menu_back: bool = False,
) -> tuple[str, InlineKeyboardMarkup | None]:
    lines: List[str] = []

    ok_sub, sub_line = await _check_subscription(bot, int(user_id))
    lines.append(sub_line)

    lim_line = await _limits_line(int(user_id), username)
    if lim_line:
        lines.append(lim_line)

    lines.append(_blocks_line(int(user_id)))

    moderation_line, pending_ads = await _moderation_state(int(user_id))
    lines.append(moderation_line)

    text = "🛠 Диагностика публикации\n\n" + "\n".join(lines) + "\n\n" + _final_line(lines)
    subscribe_url = None if ok_sub else _channel_url()
    kb = _diagnostics_kb(
        subscribe_url,
        pending_ads,
        include_menu_back=include_menu_back,
    )
    return text, kb


async def send_diagnostics(message: Message, user_id: int, bot) -> None:
    """
    Общая точка входа для:
    - /diagnostics
    - /диагностика
    - кнопки из /menu (callback)
    """
    username = (getattr(message.from_user, "username", None) or "").lstrip("@").strip() or None
    text, kb = await build_diagnostics_view(
        int(user_id),
        username,
        bot,
        include_menu_back=False,
    )

    await message.answer(
        text,
        reply_markup=kb,
        parse_mode=None,
    )


async def _render_diagnostics(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    await send_diagnostics(message, int(user.id), message.bot)


@router.message(Command("diagnostics"))
async def diagnostics_en(message: Message):
    await _render_diagnostics(message)


@router.message(Command("диагностика"))
async def diagnostics_ru(message: Message):
    await _render_diagnostics(message)
