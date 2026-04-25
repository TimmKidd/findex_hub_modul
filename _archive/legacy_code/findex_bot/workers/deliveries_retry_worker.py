# findex_bot/workers/deliveries_retry_worker.py
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
from typing import Optional

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from aiogram.client.default import DefaultBotProperties

from dotenv import load_dotenv

from findex_bot.db.db import get_sessionmaker
from findex_bot.db.repo import DeliveriesRepo, DeliveryTask

logger = logging.getLogger("deliveries_worker")

# =========================
# НАСТРОЙКИ (через env)
# =========================
BATCH_SIZE = int(os.getenv("DELIVERIES_WORKER_BATCH", "25"))
POLL_SECONDS = float(os.getenv("DELIVERIES_WORKER_POLL", "2.0"))
MAX_ATTEMPTS = int(os.getenv("DELIVERIES_WORKER_MAX_ATTEMPTS", "8"))

# backoff: 10s, 30s, 60s, 2m, 5m, 10m, 20m, 30m...
BACKOFF_STEPS = [10, 30, 60, 120, 300, 600, 1200, 1800]


def _build_backoff_seconds(attempts_before: int) -> int:
    """
    attempts_before — сколько уже было попыток ДО текущей ошибки.
    """
    idx = max(0, min(int(attempts_before), len(BACKOFF_STEPS) - 1))
    return int(BACKOFF_STEPS[idx])


def _ad_text_from_payload(payload: dict) -> str:
    position = str(payload.get("position", "") or "").strip()
    location = str(payload.get("location", "") or "").strip()
    salary = str(payload.get("salary", "") or "").strip()

    lines: list[str] = []
    if position:
        lines.append(f"<b>{position}</b>")
    if location:
        lines.append(f"📍 {location}")
    if salary:
        lines.append(f"💰 {salary}")

    return "\n".join(lines).strip()


def _open_kb(url: Optional[str]) -> Optional[InlineKeyboardMarkup]:
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔗 Открыть объявление", url=url)]]
    )


async def _send_one(bot: Bot, task: DeliveryTask) -> None:
    """
    Отправка одного уведомления юзеру.
    """
    url = (getattr(task, "public_url", None) or "").strip() or None
    payload = getattr(task, "payload", None) or {}

    head = "🔔 <b>Совпадение алерта!</b>"
    body = _ad_text_from_payload(payload)

    if not body:
        # запасной вариант, если payload вдруг пуст
        role = str(getattr(task, "role", "") or payload.get("role", "") or "").strip()
        body = role or "Новое объявление"

    text = (head + "\n\n" + body).strip()

    await bot.send_message(
        chat_id=int(task.user_tg_id),
        text=text,
        reply_markup=_open_kb(url),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def run_deliveries_worker(bot: Bot) -> None:
    """
    Бесконечный воркер:
    - берёт due deliveries (pending/failed у которых next_retry_at <= now или NULL)
    - отправляет
    - отмечает sent/failed (+backoff)
    """
    sm = get_sessionmaker()

    logger.info(
        "Deliveries worker started: batch=%s poll=%s max_attempts=%s",
        BATCH_SIZE,
        POLL_SECONDS,
        MAX_ATTEMPTS,
    )

    while True:
        try:
            async with sm() as session:
                tasks = await DeliveriesRepo.claim_due_tasks(
                    session,
                    batch_size=BATCH_SIZE,
                    max_attempts=MAX_ATTEMPTS,
                )

                if not tasks:
                    await session.commit()
                else:
                    for t in tasks:
                        try:
                            await _send_one(bot, t)
                            await DeliveriesRepo.mark_sent(session, delivery_id=t.delivery_id)
                        except Exception as e:
                            logger.exception(
                                "Delivery send failed: delivery_id=%s user_tg_id=%s",
                                getattr(t, "delivery_id", None),
                                getattr(t, "user_tg_id", None),
                            )
                            backoff = _build_backoff_seconds(getattr(t, "attempts", 0))
                            await DeliveriesRepo.mark_failed(
                                session,
                                delivery_id=t.delivery_id,
                                error=str(e),
                                backoff_seconds=backoff,
                            )

                    await session.commit()

        except asyncio.CancelledError:
            # корректное завершение (Ctrl+C)
            raise
        except Exception:
            logger.exception("Worker loop error")

        await asyncio.sleep(POLL_SECONDS)


# =========================
# CLI entrypoint
# =========================
def _load_env() -> None:
    """
    Подгружаем .env именно из корня проекта (как у тебя принято).
    """
    try:
        load_dotenv("/Users/tmkd/Desktop/tmkd/FindexHub/.env", override=True)
    except Exception:
        # если dotenv не установлен/не нужен — просто игнор
        pass


def _pick_token() -> Optional[str]:
    """
    Стараемся взять токен максимально “как в проекте”.
    """
    # 1) из env
    token = os.getenv("BOT_TOKEN")
    if token:
        return token.strip()

    # 2) из runtime.CONFIG (на всякий)
    try:
        import findex_bot.runtime as runtime  # локальный импорт

        cfg = getattr(runtime, "CONFIG", None)
        if cfg is None:
            return None

        for key in ("bot_token", "BOT_TOKEN", "main_bot_token", "MAIN_BOT_TOKEN"):
            v = getattr(cfg, key, None)
            if v:
                return str(v).strip()
    except Exception:
        return None

    return None


async def _main() -> None:
    """
    Запуск:
      python -m findex_bot.workers.deliveries_retry_worker
    """
    _load_env()
    token = _pick_token()

    if not token:
        raise RuntimeError("BOT_TOKEN not found (set env BOT_TOKEN or runtime.CONFIG.bot_token)")

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    try:
        await run_deliveries_worker(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
