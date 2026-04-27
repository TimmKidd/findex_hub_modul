# findex_bot/middlewares/throttle.py
import time
from collections import deque
from typing import Any, Awaitable, Callable, Dict, Deque

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery


class ThrottleMiddleware(BaseMiddleware):
    """
    Мягкий антиспам:
    - не банит
    - просто не пропускает слишком частые события
    """

    def __init__(self, window_seconds: int = 10, limit: int = 12, hint_seconds: int = 2):
        self.window_seconds = window_seconds
        self.limit = limit
        self.hint_seconds = hint_seconds
        self._hits: Dict[int, Deque[float]] = {}

    @staticmethod
    def _get_user_id(event: Any) -> int | None:
        if isinstance(event, Message) and event.from_user:
            return event.from_user.id
        if isinstance(event, CallbackQuery) and event.from_user:
            return event.from_user.id
        return None

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ):
        uid = self._get_user_id(event)
        if uid is None:
            return await handler(event, data)

        now = time.time()
        q = self._hits.setdefault(uid, deque())

        # чистим старые хиты
        while q and (now - q[0]) > self.window_seconds:
            q.popleft()

        q.append(now)

        if len(q) > self.limit:
            # мягкое сообщение, без show_alert (чтобы не бесить)
            if isinstance(event, CallbackQuery):
                await event.answer(f"Слишком часто. Подожди {self.hint_seconds} сек 🙃", show_alert=False)
                return
            if isinstance(event, Message):
                await event.answer(f"Ты слишком быстро пишешь/жмёшь. Подожди {self.hint_seconds} сек 🙃")
                return

        return await handler(event, data)
