# findex_bot/handlers/diagnostics.py
import logging
from typing import Tuple, List, Optional, Union

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import findex_bot.runtime as runtime

logger = logging.getLogger(__name__)
router = Router()

ALLOWED_STATUSES = {"member", "administrator", "creator"}


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


async def _check_subscription(bot, user_id: int) -> Tuple[bool, str]:
    """
    Возвращает (ok, human_text)
    """
    if user_id in (getattr(runtime, "MODERATORS", set()) or set()):
        return True, "✅ Подписка: ок (модератор)"

    target = _target_chat()
    if not target:
        return False, "❌ Подписка: канал не настроен"

    try:
        member = await bot.get_chat_member(chat_id=target, user_id=user_id)
        status = getattr(member, "status", None)
        if status in ALLOWED_STATUSES:
            return True, "✅ Подписка: ок"
        return False, "❌ Подписка: нет (не подписан)"
    except Exception as e:
        logger.exception("diagnostics: get_chat_member error: %r", e)
        # fail-closed как в middleware
        return False, "❌ Подписка: ошибка проверки (Telegram)"


def _limits_line(user_id: int) -> str:
    """
    Лимиты у тебя реализованы в handlers/forms.py через runtime.USER_PUB_COUNTER.
    Здесь аккуратно считаем оставшееся, без импорта forms.py (чтобы не тянуть роутеры).
    """
    try:
        # безлимит: модераторы или UNLIMITED_USERS
        moderators = set(getattr(runtime, "MODERATORS", set()) or set())
        unlimited = set(getattr(runtime, "UNLIMITED_USERS", set()) or set())
        if int(user_id) in moderators or int(user_id) in unlimited:
            return "✅ Лимиты: ок (безлимит)"

        LIMIT_PER_DAY = 3

        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        day_key = now.date().isoformat()

        store = getattr(runtime, "USER_PUB_COUNTER", {}) or {}
        data = store.get(int(user_id))

        if not data or data.get("date") != day_key:
            remaining = LIMIT_PER_DAY
        else:
            used = int(data.get("count", 0) or 0)
            remaining = max(0, LIMIT_PER_DAY - used)

        if remaining > 0:
            return f"✅ Лимиты: ок (осталось на сегодня UTC: {remaining}/3)"
        return "❌ Лимиты: исчерпан (0/3)"
    except Exception:
        return "⚠️ Лимиты: не удалось проверить"


def _blocks_line(user_id: int) -> str:
    blocked = getattr(runtime, "BLOCKED_USERS", set()) or set()
    return "❌ Блокировки: есть" if int(user_id) in blocked else "✅ Блокировки: нет"


def _moderation_line(user_id: int) -> str:
    """
    Проверяем, есть ли объявления в ADS_PENDING от этого юзера.
    В forms.py ты сохраняешь author_id + user_chat_id.
    """
    pending = getattr(runtime, "ADS_PENDING", {}) or {}
    try:
        uid = int(user_id)
        for _k, v in pending.items():
            if not isinstance(v, dict):
                continue
            author_id = int(v.get("author_id") or 0)
            user_chat_id = int(v.get("user_chat_id") or 0)
            if author_id == uid or user_chat_id == uid:
                return "❌ Модерация: есть объявления на проверке"
        return "✅ Модерация: нет объявлений на проверке"
    except Exception:
        return "⚠️ Модерация: не удалось проверить"


def _final_line(lines: List[str]) -> str:
    if any(l.startswith("❌") for l in lines):
        return "❌ Есть проблемы — смотри строки выше."
    return "✅ Всё ок — публикация должна проходить."


async def send_diagnostics(message: Message, user_id: int, bot) -> None:
    """
    Общая точка входа для:
    - /diagnostics
    - /диагностика
    - кнопки из /menu (callback)
    """
    lines: List[str] = []

    _ok_sub, sub_line = await _check_subscription(bot, user_id)
    lines.append(sub_line)

    lines.append(_limits_line(user_id))
    lines.append(_blocks_line(user_id))
    lines.append(_moderation_line(user_id))

    text = "🛠 Диагностика публикации\n\n" + "\n".join(lines) + "\n\n" + _final_line(lines)
    await message.answer(text)


async def _render_diagnostics(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    await send_diagnostics(message, user.id, message.bot)


@router.message(Command("diagnostics"))
async def diagnostics_en(message: Message):
    await _render_diagnostics(message)


@router.message(Command("диагностика"))
async def diagnostics_ru(message: Message):
    await _render_diagnostics(message)