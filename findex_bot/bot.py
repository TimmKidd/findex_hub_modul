import os
import asyncio
import logging
import datetime
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from findex_bot.handlers.start import router as start_router
from findex_bot.handlers.forms import router as forms_router
from findex_bot.handlers.employer import router as employer_router
from findex_bot.handlers.seeker import router as seeker_router


@dataclass
class Config:
    bot_token: str
    moderation_chat_id: int
    main_channel_id: int
    thread_vacancies: int
    channel_username: str


def load_config() -> Config:
    base_dir = Path(__file__).resolve().parent
    env_path = base_dir / ".env"

    if env_path.is_file():
        load_dotenv(env_path)
    else:
        load_dotenv()

    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN не задан в .env")

    return Config(
        bot_token=bot_token,
        moderation_chat_id=int(os.getenv("MODERATION_CHAT_ID", "0")),
        main_channel_id=int(os.getenv("MAIN_CHANNEL_ID", "0")),
        thread_vacancies=int(os.getenv("THREAD_VACANCIES", "0")),
        channel_username=os.getenv("CHANNEL_USERNAME", ""),
    )


config = load_config()
logging.basicConfig(level=logging.INFO)

# ======================================================
# ЕДИНЫЙ ИСТОЧНИК ПРАВДЫ ДЛЯ handlers/forms.py
# ======================================================

# Очередь объявлений "на модерации"
ADS_PENDING: dict[str, dict] = {}

# Отклонённые объявления (для возврата на исправление)
ADS_REJECTED: dict[str, dict] = {}

# Опубликованные посты (для кнопки "Открыть публикацию")
# {ad_id: {"channel_id": int, "message_id": int, "url": str|None}}
PUBLISHED_POSTS: dict[str, dict] = {}

# Счётчик бесплатных публикаций (ТОЛЬКО опубликованных в основной канал)
# {user_id: {"date": "YYYY-MM-DD", "count": int}}
USER_PUB_COUNTER: dict[int, dict[str, int]] = {}

# Модераторы (безлимит)
UNLIMITED_USERS: set[int] = {80675147, 7107629211}
MODERATORS = UNLIMITED_USERS


def _today_str() -> str:
    return datetime.date.today().isoformat()


def can_publish_today(user_id: int) -> bool:
    """Проверка лимита. НЕ увеличивает счётчик."""
    if user_id in UNLIMITED_USERS:
        return True

    today = _today_str()
    data = USER_PUB_COUNTER.get(user_id)
    if not data or data.get("date") != today:
        return True

    return int(data.get("count", 0)) < 3


def record_published(user_id: int) -> int | str:
    """Увеличивает счётчик ТОЛЬКО ПОСЛЕ успешной публикации в основной канал."""
    if user_id in UNLIMITED_USERS:
        return "∞"

    today = _today_str()
    data = USER_PUB_COUNTER.get(user_id)

    if not data or data.get("date") != today:
        USER_PUB_COUNTER[user_id] = {"date": today, "count": 0}
        data = USER_PUB_COUNTER[user_id]

    data["count"] = int(data.get("count", 0)) + 1
    return max(0, 3 - data["count"])


def get_remaining_today(user_id: int) -> int | str:
    """Сколько осталось сегодня. НЕ увеличивает счётчик."""
    if user_id in UNLIMITED_USERS:
        return "∞"

    today = _today_str()
    data = USER_PUB_COUNTER.get(user_id)
    if not data or data.get("date") != today:
        return 3

    return max(0, 3 - int(data.get("count", 0)))


async def main():
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.include_router(start_router)
    dp.include_router(forms_router)
    dp.include_router(employer_router)
    dp.include_router(seeker_router)

    logging.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
