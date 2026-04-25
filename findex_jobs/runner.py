# findex_jobs/runner.py
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions

from findex_bot.db.db import get_sessionmaker
from findex_bot.db.repo import RespondRepo

logger = logging.getLogger(__name__)

JOBS_LOCK_ID = int(os.getenv("JOBS_LOCK_ID", "987654321"))
JOBS_TICK_SECONDS = int(os.getenv("JOBS_TICK_SECONDS", "60"))

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _kb_open_candidate(respond_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Открыть диалог", callback_data=f"respond_resume:{respond_id}")],
        [InlineKeyboardButton(text="❌ Закрыть отклик", callback_data=f"resp_cand_cancel:{respond_id}")],
    ])


def _kb_open_owner(respond_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Открыть диалог", callback_data=f"respond_resume:{respond_id}")],
        [InlineKeyboardButton(text="❌ Закрыть отклик", callback_data=f"resp_owner_close:{respond_id}")],
    ])


async def _send_candidate(bot: Bot, chat_id: int, text: str, respond_id: int) -> None:
    await bot.send_message(
        chat_id=int(chat_id),
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_open_candidate(int(respond_id)),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def _send_owner(bot: Bot, chat_id: int, text: str, respond_id: int) -> None:
    await bot.send_message(
        chat_id=int(chat_id),
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_open_owner(int(respond_id)),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def tick(bot: Bot) -> None:
    now = _now_utc()
    async with get_sessionmaker()() as session:
        repo = RespondRepo(session)

        if not await repo.try_acquire_jobs_lock(JOBS_LOCK_ID):
            return  # не лидер

        # 12h ping candidate (если молчит после INVITED)
        for r in await repo.pick_for_ping12(now_utc=now):
            try:
                if not await repo.reserve_ping12(int(r.id)):
                    continue
                await _send_candidate(
                    bot,
                    int(r.candidate_chat_id),
                    "👋 Напоминаю про отклик: работодатель заинтересовался.\nЕсли актуально — напиши в диалоге 🙂",
                    int(r.id),
                )
            except Exception:
                logger.exception("ping12 failed respond_id=%s", getattr(r, "id", None))

        # 36h ping candidate
        for r in await repo.pick_for_ping36(now_utc=now):
            try:
                if not await repo.reserve_ping36(int(r.id)):
                    continue
                await _send_candidate(
                    bot,
                    int(r.candidate_chat_id),
                    "🙂 Проверю актуальность: тебе всё ещё интересно?\nЕсли нет — можешь закрыть отклик, чтобы он не висел.",
                    int(r.id),
                )
            except Exception:
                logger.exception("ping36 failed respond_id=%s", getattr(r, "id", None))

        # 24h ping owner (кандидат писал, владелец молчит)
        for r in await repo.pick_for_owner24(now_utc=now):
            try:
                if not await repo.reserve_ping_owner24(int(r.id)):
                    continue
                await _send_owner(
                    bot,
                    int(r.author_chat_id),
                    "👀 Кандидат ответил в отклике.\nЕсли актуально — продолжи диалог, чтобы не потерять контакт.",
                    int(r.id),
                )
            except Exception:
                logger.exception("ping_owner24 failed respond_id=%s", getattr(r, "id", None))


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set (BOT_TOKEN/TELEGRAM_BOT_TOKEN)")

    bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)

    while True:
        try:
            await tick(bot)
        except Exception:
            logger.exception("jobs tick failed")
        await asyncio.sleep(JOBS_TICK_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())