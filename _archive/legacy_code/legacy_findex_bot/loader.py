import logging
from aiogram import Bot, Dispatcher

# Для Redis FSM закомментируйте блок MemoryStorage и раскомментируйте RedisStorage
# from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder
# from redis.asyncio import Redis

from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

from findex_bot.config import BOT_TOKEN

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----- Используйте MemoryStorage для отладки и диагностики -----
async def create_storage():
    storage = MemoryStorage()
    logger.info("FSM: MemoryStorage")
    return storage

# ----- Если нужен Redis, раскомментируйте этот код -----
"""
async def create_storage():
    redis = Redis(
        host="localhost",
        port=6379,
        db=0
    )
    storage = RedisStorage(redis=redis, key_builder=DefaultKeyBuilder())
    logger.info("Redis: FSM НЕ ПОТЕРЯЕТСЯ")
    return storage
"""

async def get_bot_and_dp():
    storage = await create_storage()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=storage)
    return bot, dp

def register_routers(dp):
    from findex_bot.handlers.start import router as start_router
    from findex_bot.handlers.moderation import router as moderation_router
    dp.include_router(start_router)
    dp.include_router(moderation_router)

async def on_startup(bot):
    logger.info("Бот запущен!")

async def on_shutdown(bot):
    logger.info("Бот остановлен.")

async def setup_bot():
    bot, dp = await get_bot_and_dp()
    register_routers(dp)
    return bot, dp