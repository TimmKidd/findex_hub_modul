# findex_bot/bot.py
import os
import asyncio
import logging
from dataclasses import dataclass

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession

import findex_bot.runtime as runtime

from findex_bot.middlewares.subscription import SubscriptionMiddleware
from findex_bot.middlewares.fsm_watchdog import FSMWatchdogMiddleware
from findex_bot.middlewares.published_guard import PublishedPreviewGuardMiddleware

logging.basicConfig(level=logging.INFO, force=True)


# ---------------- CONFIG ----------------
@dataclass
class Config:
    bot_token: str
    moderation_chat_id: int
    main_channel_id: int
    thread_vacancies: int
    channel_username: str


def load_config() -> Config:
    load_dotenv("/Users/tmkd/Desktop/tmkd/FindexHub/.env")

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN not set in .env")

    moderation_chat_id = int(os.getenv("MODERATION_CHAT_ID", 0) or 0)
    if moderation_chat_id == 0:
        raise RuntimeError("MODERATION_CHAT_ID not set (or equals 0)")

    return Config(
        bot_token=token,
        moderation_chat_id=moderation_chat_id,
        main_channel_id=int(os.getenv("MAIN_CHANNEL_ID", 0) or 0),
        thread_vacancies=int(os.getenv("THREAD_VACANCIES", 0) or 0),
        channel_username=os.getenv("CHANNEL_USERNAME", "") or "",
    )


config = load_config()

# ---------- runtime INIT (важно: ДО импортов handlers) ----------
runtime.CONFIG = config
runtime.MODERATION_CHAT_ID = config.moderation_chat_id
runtime.MAIN_CHANNEL_ID = config.main_channel_id
runtime.THREAD_VACANCIES = config.thread_vacancies
runtime.CHANNEL_USERNAME = config.channel_username

# базовые хранилища (не затираем при перезапусках)
if not hasattr(runtime, "PUBLISHED_PREVIEW_MESSAGES"):
    runtime.PUBLISHED_PREVIEW_MESSAGES = {}
if not hasattr(runtime, "ADS_PENDING"):
    runtime.ADS_PENDING = {}
if not hasattr(runtime, "ADS_REJECTED"):
    runtime.ADS_REJECTED = {}
if not hasattr(runtime, "PUBLISHED_POSTS"):
    runtime.PUBLISHED_POSTS = {}
if not hasattr(runtime, "USER_PUB_COUNTER"):
    runtime.USER_PUB_COUNTER = {}

# alerts: in-memory store + redis handle
if not hasattr(runtime, "ALERTS_STORE"):
    runtime.ALERTS_STORE = {}
if not hasattr(runtime, "REDIS"):
    runtime.REDIS = None


# ---------------- ROUTERS ----------------
from findex_bot.handlers.fsm_watchdog import router as fsm_watchdog_router
from findex_bot.handlers.subscription import router as subscription_router
from findex_bot.handlers.start import router as start_router
from findex_bot.handlers.menu import router as menu_router
from findex_bot.handlers.help import router as help_router
from findex_bot.handlers.diagnostics import router as diagnostics_router

# ✅ модерация — раньше всех, чтобы никакие forms не перехватывали reject:
from findex_bot.handlers.moderation import router as moderation_router

from findex_bot.handlers.forms import router as forms_router
from findex_bot.handlers.employer import router as employer_router
from findex_bot.handlers.seeker import router as seeker_router
from findex_bot.handlers.replies import router as replies_router
from findex_bot.handlers.alerts import router as alerts_router

from findex_bot.handlers.debug_ping import (
    router as debug_ping_router,
    CallbackLoggerMiddleware,
)

from findex_bot.handlers.forms import SavedHintMiddleware


def build_bot() -> Bot:
    session = AiohttpSession(timeout=180)
    return Bot(
        token=config.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def _init_redis():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    try:
        import redis.asyncio as redis  # type: ignore
    except Exception:
        runtime.REDIS = None
        logging.warning("⚠️ redis package not installed -> alerts will use in-memory fallback")
        return

    try:
        r = redis.from_url(redis_url, decode_responses=True)
        await r.ping()
        runtime.REDIS = r
        logging.info(f"✅ Redis connected: {redis_url}")
    except Exception:
        runtime.REDIS = None
        logging.exception("⚠️ Redis not available -> alerts will use in-memory fallback")


async def _close_redis():
    try:
        r = getattr(runtime, "REDIS", None)
        if r is None:
            return
        if hasattr(r, "aclose"):
            await r.aclose()
        else:
            await r.close()
    except Exception:
        pass
    finally:
        runtime.REDIS = None


async def main():
    bot = build_bot()
    dp = Dispatcher()

    await _init_redis()

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("✅ Webhook deleted (drop_pending_updates=True)")
    except Exception:
        logging.exception("⚠️ delete_webhook failed")

    # ---------------- MIDDLEWARES ----------------
    dp.callback_query.middleware(CallbackLoggerMiddleware())
    dp.message.middleware(SavedHintMiddleware())
    dp.callback_query.middleware(PublishedPreviewGuardMiddleware())

    sub = SubscriptionMiddleware()
    dp.message.middleware(sub)
    dp.callback_query.middleware(sub)

    fsm_wd = FSMWatchdogMiddleware()
    dp.message.middleware(fsm_wd)
    dp.callback_query.middleware(fsm_wd)

    # ---------------- ROUTERS (ПОРЯДОК ВАЖЕН) ----------------
    dp.include_router(fsm_watchdog_router)
    dp.include_router(help_router)
    dp.include_router(menu_router)
    dp.include_router(alerts_router)
    dp.include_router(diagnostics_router)
    dp.include_router(start_router)

    # ✅ approve/reject/rejr — СНАЧАЛА модерация
    dp.include_router(moderation_router)

    dp.include_router(forms_router)
    dp.include_router(employer_router)
    dp.include_router(seeker_router)
    dp.include_router(replies_router)

    dp.include_router(subscription_router)
    dp.include_router(debug_ping_router)

    logging.info("✅ Bot started (polling)")

    try:
        await dp.start_polling(
            bot,
            polling_timeout=20,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        await _close_redis()
        try:
            await bot.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
