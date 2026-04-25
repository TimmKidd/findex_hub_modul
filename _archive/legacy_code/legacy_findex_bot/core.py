import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.default import DefaultBotProperties
from redis.asyncio import Redis
from findex_bot.config import BOT_TOKEN

logging.basicConfig(level=logging.INFO)

redis = Redis(host='localhost', port=6379, db=0, decode_responses=True)
try:
    storage = RedisStorage(redis=redis)
    logging.info("Redis: FSM НЕ ПОТЕРЯЕТСЯ")
except Exception as e:
    logging.warning(f"Redis недоступен: {e}. MemoryStorage.")
    storage = MemoryStorage()

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=storage)