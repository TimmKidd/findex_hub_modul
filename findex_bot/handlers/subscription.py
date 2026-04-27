# findex_bot/handlers/subscription.py
from __future__ import annotations

import os
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.enums import ParseMode

from findex_bot.middlewares.subscription import CHECK_CB, ALLOWED_STATUSES

logger = logging.getLogger(__name__)
router = Router()


def _target_chat() -> str | int | None:
    username = (os.getenv("CHANNEL_USERNAME", "") or "").lstrip("@").strip()
    ch_id_raw = (os.getenv("MAIN_CHANNEL_ID", "") or "").strip()

    channel_id = 0
    try:
        channel_id = int(ch_id_raw) if ch_id_raw else 0
    except Exception:
        channel_id = 0

    if username:
        return f"@{username}"
    if channel_id:
        return channel_id
    return None


async def _is_subscribed(bot, user_id: int) -> bool:
    target = _target_chat()
    if not target:
        # если конфиг канала пуст — считаем НЕ подписан, чтобы не открывать доступ
        return False

    try:
        member = await bot.get_chat_member(chat_id=target, user_id=user_id)
        status = getattr(member, "status", None)
        return status in ALLOWED_STATUSES
    except Exception as e:
        logger.exception("subscription check failed: %r", e)
        return False


@router.callback_query(F.data == CHECK_CB)
async def subscription_check(callback: CallbackQuery):
    ok = await _is_subscribed(callback.bot, callback.from_user.id)

    if ok:
        # ✅ ВАЖНО: без <code> и без блоков, чтобы /start не копировался как код
        text = (
            "✅ Подписка подтверждена!\n\n"
            "Чтобы создать объявление — нажми /start"
        )
        try:
            await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=None)
        except Exception:
            # если нельзя редактировать — просто отправим новым сообщением
            try:
                await callback.message.answer(text, parse_mode=ParseMode.HTML)
            except Exception:
                pass

        try:
            await callback.answer("✅ Ок", show_alert=False)
        except Exception:
            pass
        return

    # НЕ подписан
    try:
        await callback.answer("❌ Подписку пока не вижу. Подпишись и нажми ещё раз.", show_alert=True)
    except Exception:
        pass
