# findex_bot/middlewares/published_guard.py
from __future__ import annotations

from typing import Callable, Awaitable, Dict, Any, Optional

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery

import findex_bot.runtime as runtime


_PREVIEW_CB_PREFIXES = (
    # employer edit
    "emp_edit_",
    # seeker edit
    "seek_edit_",

    # media buttons (employer/seeker)
    "emp_media_",
    "seek_media_",

    # send to moderation (ВАЖНО: реальные callback'и)
    "send_employer:",
    "send_seeker:",
)

_PREVIEW_MODE_MODERATION = getattr(runtime, "PREVIEW_MODE_MODERATION", "moderation")
_PREVIEW_MODE_PUBLISHED = getattr(runtime, "PREVIEW_MODE_PUBLISHED", "published")


def _get_preview_lock_storage() -> dict[tuple[int, int], str]:
    store = getattr(runtime, "PUBLISHED_PREVIEW_MESSAGES", None)
    if store is None:
        store = {}

    if isinstance(store, set):
        converted: dict[tuple[int, int], str] = {}
        for item in store:
            try:
                chat_id, msg_id = item
                converted[(int(chat_id), int(msg_id))] = _PREVIEW_MODE_MODERATION
            except Exception:
                continue
        store = converted

    if not isinstance(store, dict):
        store = {}

    runtime.PUBLISHED_PREVIEW_MESSAGES = store
    return store


def _get_pending() -> dict:
    p = getattr(runtime, "ADS_PENDING", None)
    if p is None or not isinstance(p, dict):
        p = {}
        runtime.ADS_PENDING = p
    return p


def _bool_flag(ad: dict, *keys: str) -> bool:
    for k in keys:
        try:
            if bool(ad.get(k)):
                return True
        except Exception:
            continue
    return False


def _pending_mode_for_message(chat_id: int, msg_id: int) -> Optional[str]:
    pending = _get_pending()
    if not pending:
        return None

    for _, ad in pending.items():
        if not isinstance(ad, dict):
            continue
        try:
            pchat = int(ad.get("preview_chat_id") or 0)
            pmsg = int(ad.get("preview_message_id") or 0)
        except Exception:
            continue

        if pchat != int(chat_id) or pmsg != int(msg_id):
            continue

        is_published = _bool_flag(ad, "published", "is_published")
        on_moderation = _bool_flag(ad, "sent_to_moderation", "on_moderation", "moderation")

        if is_published:
            return _PREVIEW_MODE_PUBLISHED
        if on_moderation:
            return _PREVIEW_MODE_MODERATION

        return None

    return None


class PublishedPreviewGuardMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)

        if not event.from_user:
            return await handler(event, data)

        cb_data = (event.data or "").strip()

        if not cb_data.startswith(_PREVIEW_CB_PREFIXES):
            return await handler(event, data)

        locked_users = getattr(runtime, "LOCKED_PREVIEW_USERS", set()) or set()
        try:
            if int(event.from_user.id) in locked_users:
                await event.answer("⛔ Предпросмотр уже закрыт. Создай новое объявление: /start", show_alert=True)
                return
        except Exception:
            pass

        if not event.message:
            return await handler(event, data)

        chat_id = int(event.message.chat.id)
        msg_id = int(event.message.message_id)

        store = _get_preview_lock_storage()
        mode = store.get((chat_id, msg_id))

        if mode is None:
            mode = _pending_mode_for_message(chat_id, msg_id)

        if mode == _PREVIEW_MODE_PUBLISHED:
            await event.answer("✅ Объявление уже опубликовано", show_alert=True)
            return

        if mode == _PREVIEW_MODE_MODERATION:
            await event.answer("⏳ Объявление на модерации", show_alert=True)
            return

        return await handler(event, data)
