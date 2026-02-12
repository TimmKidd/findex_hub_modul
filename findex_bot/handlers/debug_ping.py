# findex_bot/handlers/debug_ping.py
import logging
from typing import Any, Dict, Callable, Awaitable

from aiogram import Router, BaseMiddleware, F
from aiogram.types import Message, CallbackQuery

router = Router()
logger = logging.getLogger(__name__)


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
    """

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        try:
            if isinstance(event, CallbackQuery):
                logger.error("[DEBUG CALLBACK_DATA] %s", event.data)
        except Exception:
            pass

        # 🔴 КРИТИЧНО: без этого кнопки НЕ работают
        return await handler(event, data)
