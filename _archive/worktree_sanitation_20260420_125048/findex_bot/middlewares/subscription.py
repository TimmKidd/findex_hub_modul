# findex_bot/middlewares/subscription.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, Set

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

# handlers/subscription.py ожидает эти имена:
CHECK_CB = "check_sub"  # callback_data кнопки "Проверить подписку"

# Допустимые статусы участника канала (Telegram API)
ALLOWED_STATUSES = {"member", "administrator", "creator"}


@dataclass
class SubscriptionMiddleware(BaseMiddleware):
    """
    Блокирует взаимодействие с ботом, если пользователь НЕ подписан на канал.

    ВАЖНО:
    - ДОЛЖЕН быть совместим с bot.py:
        SubscriptionMiddleware(channel_username=..., channel_id=..., moderators=...)
    - ДОЛЖЕН экспортировать CHECK_CB и ALLOWED_STATUSES
    """

    channel_username: str = ""
    channel_id: int = 0
    moderators: Set[int] | Iterable[int] = None

    def __post_init__(self) -> None:
        self.moderators = set(self.moderators or set())
        self.channel_username = (self.channel_username or "").lstrip("@")
        self.channel_id = int(self.channel_id or 0)

    def _is_configured(self) -> bool:
        # если ничего не настроено — НИЧЕГО НЕ РЕЖЕМ
        return bool(self.channel_id) or bool(self.channel_username)

    async def _get_user_status(self, bot, user_id: int) -> Optional[str]:
        """
        Пробуем получить статус участника.
        Сначала по channel_id, если его нет — по @username.
        """
        chat = None
        if self.channel_id:
            chat = self.channel_id
        elif self.channel_username:
            chat = f"@{self.channel_username}"

        if not chat:
            return None

        try:
            member = await bot.get_chat_member(chat_id=chat, user_id=int(user_id))
            return getattr(member, "status", None)
        except Exception:
            return None

    async def _is_allowed(self, bot, user_id: int) -> bool:
        if int(user_id) in self.moderators:
            return True

        if not self._is_configured():
            return True

        status = await self._get_user_status(bot, int(user_id))
        return (status or "") in ALLOWED_STATUSES

    def _is_service_update(self, event: Any) -> bool:
        # когда не можем определить пользователя — не режем
        if isinstance(event, Message):
            return event.from_user is None
        if isinstance(event, CallbackQuery):
            return event.from_user is None
        return True

    def _callback_is_check(self, event: CallbackQuery) -> bool:
        data = (event.data or "").strip()
        return data == CHECK_CB

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        # если это не message/callback — не трогаем
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        if self._is_service_update(event):
            return await handler(event, data)

        bot = data.get("bot")  # aiogram прокидывает bot в data
        user = event.from_user
        user_id = int(user.id)

        # КНОПКУ "Проверить подписку" НЕ БЛОКИРУЕМ НИКОГДА
        if isinstance(event, CallbackQuery) and self._callback_is_check(event):
            return await handler(event, data)

        allowed = await self._is_allowed(bot, user_id)
        if allowed:
            return await handler(event, data)

        # --- НЕ подписан: показываем сообщение и стопаем ---
        text = "🚫 Для работы с ботом нужна подписка на канал."
        if self.channel_username:
            text += f"\nПодпишись: @{self.channel_username}"
        elif self.channel_id:
            text += f"\nПодпишись на канал (id={self.channel_id})"

        if isinstance(event, CallbackQuery):
            try:
                await event.answer(text, show_alert=True)
            except Exception:
                pass
            return

        if isinstance(event, Message):
            try:
                await event.answer(text)
            except Exception:
                pass
            return
