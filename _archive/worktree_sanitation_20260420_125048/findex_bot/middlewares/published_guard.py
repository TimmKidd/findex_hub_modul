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

# ✅ callbacks, которые НЕ относятся к preview/модерации и НЕ должны глушиться этим middleware
# (важно держать этот allowlist рядом, чтобы случайно не отрезать новые фичи)
_ALLOW_CB_PREFIXES = (
    # 📩 Отклики (вся ветка)
    "respond:",          # respond:<ad_id>
    "respond_",          # respond_* (если появятся внутренние callback-и)
    "resp_",             # resp_* (owner/candidate actions)

    # меню/системные переходы (чтобы НИКОГДА не пострадали от preview-guard)
    "menu_open",         # твой “В меню” в карточках
    "menu_",             # menu_* (refresh/start/diag)
    "alerts_",           # alerts_* (ветка уведомлений)
    "al_",               # если где-то есть короткие алиасы
    "noop",              # общий noop

    # старые replies (исторически в проекте уже есть replies.py)
    "reply_to:",
    "show_contacts:",
)

_PREVIEW_MODE_MODERATION = getattr(runtime, "PREVIEW_MODE_MODERATION", "moderation")
_PREVIEW_MODE_PUBLISHED = getattr(runtime, "PREVIEW_MODE_PUBLISHED", "published")


def _get_preview_lock_storage() -> dict[tuple[int, int], str]:
    store = getattr(runtime, "PUBLISHED_PREVIEW_MESSAGES", None)
    if store is None:
        store = {}

    # обратная совместимость: раньше мог быть set[(chat_id,msg_id)]
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

        # ✅ 1) allowlist: эти ветки НЕ ТРОГАЕМ НИКОГДА
        if cb_data.startswith(_ALLOW_CB_PREFIXES):
            return await handler(event, data)

        # ✅ 2) это middleware вмешивается ТОЛЬКО в preview-кнопки
        if not cb_data.startswith(_PREVIEW_CB_PREFIXES):
            return await handler(event, data)

        # ✅ 3) если у callback нет сообщения — нечего защищать
        if not event.message:
            return await handler(event, data)

        chat_id = int(event.message.chat.id)
        msg_id = int(event.message.message_id)

        # ✅ 4) ЖЁСТКАЯ ГАРАНТИЯ:
        # вмешиваемся только если сообщение реально опознано как preview (store/pending)
        store = _get_preview_lock_storage()
        mode = store.get((chat_id, msg_id))
        if mode is None:
            mode = _pending_mode_for_message(chat_id, msg_id)

        # если это НЕ preview-сообщение — не лезем вообще
        if mode is None:
            return await handler(event, data)

        # ✅ 5) UX-стоп для тех, кому закрыли preview
        locked_users = getattr(runtime, "LOCKED_PREVIEW_USERS", set()) or set()
        try:
            if int(event.from_user.id) in locked_users:
                await event.answer("⛔ Предпросмотр уже закрыт. Создай новое объявление: /start", show_alert=True)
                return
        except Exception:
            pass

        if mode == _PREVIEW_MODE_PUBLISHED:
            await event.answer("✅ Объявление уже опубликовано", show_alert=True)
            return

        if mode == _PREVIEW_MODE_MODERATION:
            await event.answer("⏳ Объявление на модерации", show_alert=True)
            return

        return await handler(event, data)