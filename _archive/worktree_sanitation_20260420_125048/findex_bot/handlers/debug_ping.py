# findex_bot/handlers/debug_ping.py
from __future__ import annotations

import logging
from typing import Any, Dict, Callable, Awaitable

from aiogram import Router, BaseMiddleware, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func

import findex_bot.runtime as runtime
from findex_bot.db.db import get_sessionmaker
from findex_bot.db.models import Ad
from findex_bot.utils.ui_utils import moderation_keyboard

router = Router()
logger = logging.getLogger(__name__)

PAGE_SIZE = 10

CB_PENDING_LIST = "mod_pending_list"
CB_PENDING_OPEN = "mod_pending_open"


def _is_moderator(user_id: int) -> bool:
    return int(user_id) in (getattr(runtime, "MODERATORS", set()) or set())


def _payload_value(payload: dict[str, Any] | None, *keys: str) -> str:
    p = payload or {}
    for key in keys:
        val = p.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s:
            return s
    return ""


async def _count_pending() -> int:
    async with get_sessionmaker()() as session:
        stmt = select(func.count()).select_from(Ad).where(Ad.status == "pending")
        res = await session.execute(stmt)
        return int(res.scalar_one() or 0)


async def _load_pending_page(page: int = 0) -> list[Ad]:
    page = max(int(page), 0)
    async with get_sessionmaker()() as session:
        stmt = (
            select(Ad)
            .where(Ad.status == "pending")
            .order_by(Ad.updated_at.asc(), Ad.id.asc())
            .limit(PAGE_SIZE)
            .offset(page * PAGE_SIZE)
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())


async def _get_pending_by_id(ad_id: int) -> Ad | None:
    async with get_sessionmaker()() as session:
        stmt = select(Ad).where(
            Ad.id == int(ad_id),
            Ad.status == "pending",
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()


def _queue_text(ads: list[Ad], total: int, page: int) -> str:
    if total <= 0 or not ads:
        return "🟢 <b>Очередь модерации пуста</b>"

    start_idx = page * PAGE_SIZE + 1
    end_idx = min(page * PAGE_SIZE + len(ads), total)

    lines = [
        "🗂 <b>Очередь модерации</b>",
        "",
        f"Всего ожидают: <b>{total}</b>",
        f"Показано: <b>{start_idx}-{end_idx}</b>",
        "",
    ]

    for ad in ads:
        payload = getattr(ad, "payload", None) or {}
        title = _payload_value(payload, "title", "position", "job_title") or "Без названия"
        location = _payload_value(payload, "location", "city", "metro")
        role = str(getattr(ad, "role", "") or "").strip() or "—"

        row = f"#{int(ad.id)} · {role} · {title}"
        if location:
            row += f" · {location}"
        lines.append(row)

    return "\n".join(lines)


def _queue_kb(ads: list[Ad], page: int, total: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for ad in ads:
        rows.append([
            InlineKeyboardButton(
                text=f"📄 Открыть #{int(ad.id)}",
                callback_data=f"{CB_PENDING_OPEN}:{int(ad.id)}:{int(page)}",
            )
        ])

    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"{CB_PENDING_LIST}:{page - 1}",
            )
        )
    if (page + 1) * PAGE_SIZE < total:
        nav_row.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"{CB_PENDING_LIST}:{page + 1}",
            )
        )
    if nav_row:
        rows.append(nav_row)

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _copy_original_moderation_card(callback: CallbackQuery, ad: Ad) -> bool:
    """
    Единственно правильный путь:
    копируем ИМЕННО оригинальное сообщение из чата модерации и
    после копирования навешиваем рабочую moderation_keyboard(ad_id).
    Никакой реконструкции из payload.
    """
    if not callback.message:
        return False

    payload = getattr(ad, "payload", None) or {}
    source_chat_id = payload.get("moderation_chat_id")
    source_message_id = payload.get("moderation_message_id")

    if not source_chat_id or not source_message_id:
        logger.warning(
            "mod_pending_open: missing moderation refs ad_id=%s payload_keys=%s",
            getattr(ad, "id", None),
            list(payload.keys()),
        )
        return False

    target_chat_id = int(callback.message.chat.id)

    try:
        copied = await callback.bot.copy_message(
            chat_id=target_chat_id,
            from_chat_id=int(source_chat_id),
            message_id=int(source_message_id),
        )

        await callback.bot.edit_message_reply_markup(
            chat_id=target_chat_id,
            message_id=int(copied.message_id),
            reply_markup=moderation_keyboard(int(ad.id)),
        )

        await callback.answer("Карточка открыта")
        return True
    except Exception:
        logger.exception(
            "mod_pending_open: copy/edit failed ad_id=%s source_chat_id=%s source_message_id=%s target_chat_id=%s",
            getattr(ad, "id", None),
            source_chat_id,
            source_message_id,
            target_chat_id,
        )
        return False


async def _render_pending_queue(target: Message | CallbackQuery, page: int = 0) -> None:
    page = max(int(page), 0)
    total = await _count_pending()
    ads = await _load_pending_page(page=page)

    text = _queue_text(ads, total, page)
    kb = _queue_kb(ads, page, total)

    if isinstance(target, Message):
        await target.answer(text, reply_markup=kb, parse_mode="HTML")
        return

    try:
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            raise
    finally:
        try:
            await target.answer()
        except Exception:
            pass


@router.message(F.text == "/намодерации")
async def pending_ads_cmd(message: Message):
    user = message.from_user
    if not user or not _is_moderator(int(user.id)):
        return
    await _render_pending_queue(message, page=0)


@router.callback_query(F.data.startswith(f"{CB_PENDING_LIST}:"))
async def pending_ads_page(callback: CallbackQuery):
    user = callback.from_user
    if not user or not _is_moderator(int(user.id)):
        return

    parts = (callback.data or "").split(":")
    try:
        page = int(parts[1])
    except Exception:
        page = 0

    await _render_pending_queue(callback, page=page)


@router.callback_query(F.data.startswith(f"{CB_PENDING_OPEN}:"))
async def pending_ads_open(callback: CallbackQuery):
    user = callback.from_user
    if not user or not _is_moderator(int(user.id)):
        return

    parts = (callback.data or "").split(":")
    try:
        ad_id = int(parts[1])
    except Exception:
        try:
            await callback.answer("⚠️ Некорректные данные", show_alert=True)
        except Exception:
            pass
        return

    ad = await _get_pending_by_id(ad_id)
    if ad is None:
        try:
            await callback.answer("⚠️ Объявление уже не находится на модерации", show_alert=True)
        except Exception:
            pass
        return

    opened = await _copy_original_moderation_card(callback, ad)
    if opened:
        return

    try:
        await callback.answer("⚠️ Не удалось открыть оригинальную карточку модерации", show_alert=True)
    except Exception:
        pass


@router.message(F.text.in_({"ping", "пинг"}))
async def debug_ping(message: Message):
    await message.answer("🟢 debug_ping: сообщение дошло")


@router.callback_query(F.data.startswith("fix_rej:"))
async def dbg_fixrej(callback: CallbackQuery):
    """
    ✅ Диагностическая ловушка.
    Если этот alert появляется — значит callback дошёл до роутера
    и НЕ был заблокирован middleware'ами выше.
    """
    await callback.answer("DBG: fix_rej дошел", show_alert=True)


class CallbackLoggerMiddleware(BaseMiddleware):
    """
    ЛОГГЕР CALLBACK-ДАННЫХ

    ВАЖНО:
    - НИЧЕГО НЕ БЛОКИРУЕТ
    - ВСЕГДА вызывает handler(...)
    - Используется ТОЛЬКО для логов
    - Обычные callback'и НЕ должны логироваться как ERROR
    """

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        try:
            if isinstance(event, CallbackQuery):
                cb_data = event.data or "<empty>"
                logger.debug("[DEBUG CALLBACK_DATA] %s", cb_data)
        except Exception:
            logger.exception("CallbackLoggerMiddleware: failed to log callback data")

        return await handler(event, data)
