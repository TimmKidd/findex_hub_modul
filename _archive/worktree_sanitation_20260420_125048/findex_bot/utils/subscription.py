# findex_bot/utils/subscription.py

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
import logging
import datetime

ALLOWED_STATUSES = {"member", "administrator", "creator"}

logger = logging.getLogger("subscription")


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def is_subscribed(bot: Bot, channel_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        ok = member.status in ALLOWED_STATUSES

        logger.info(
            f"[{_now()}] SUB_CHECK user={user_id} status={member.status}"
        )

        return ok

    except TelegramBadRequest:
        logger.warning(
            f"[{_now()}] SUB_CHECK_FAIL user={user_id} TelegramBadRequest"
        )
        return False

    except Exception as e:
        logger.exception(
            f"[{_now()}] SUB_CHECK_ERROR user={user_id} err={e}"
        )
        return False
