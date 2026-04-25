import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MODERATION_CHAT_ID = int(os.getenv("MODERATION_CHAT_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
THREAD_VACANCIES = int(os.getenv("THREAD_VACANCIES", 5))
THREAD_RENT = int(os.getenv("THREAD_RENT", 6))
THREAD_SELLBUY = int(os.getenv("THREAD_SELLBUY", 7))
THREAD_SERVICES = int(os.getenv("THREAD_SERVICES", 8))
MODERATOR_IDS = [int(x) for x in os.getenv("MODERATOR_IDS", "").split(",") if x.strip()]
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))