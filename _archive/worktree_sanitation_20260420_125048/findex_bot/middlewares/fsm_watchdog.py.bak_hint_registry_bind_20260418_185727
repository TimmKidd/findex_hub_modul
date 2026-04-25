# 5) findex_bot/middlewares/fsm_watchdog.py

from __future__ import annotations

import asyncio

import os
import time
import logging
from typing import Any, Awaitable, Callable, Optional

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from findex_bot.states.vacancies import EmployerForm, SeekerForm
from findex_bot.handlers.responds import RespondFSM
from findex_bot.handlers.responds import RespondFSM
from aiogram.fsm.context import FSMContext

logger = logging.getLogger(__name__)

FSM_WD_CONTINUE = "fsmwd:continue"
FSM_WD_RESTART = "fsmwd:restart"

K_LAST_TS = "fsm_last_ts"
K_LAST_STATE = "fsm_last_state"
K_LAST_PROMPT_TS = "fsm_wd_prompt_ts"

DEFAULT_TIMEOUT_SEC = 60 * 60
DEFAULT_COOLDOWN_SEC = 60


def _now_ts() -> int:
    return int(time.time())


def _get_timeout_sec() -> int:
    try:
        return max(60, int(os.getenv("FSM_WATCHDOG_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SEC))))
    except Exception:
        return DEFAULT_TIMEOUT_SEC


def _get_cooldown_sec() -> int:
    try:
        return max(5, int(os.getenv("FSM_WATCHDOG_COOLDOWN_SECONDS", str(DEFAULT_COOLDOWN_SEC))))
    except Exception:
        return DEFAULT_COOLDOWN_SEC




async def _delete_message_later(msg: Message, delay_sec: float = 2.5) -> None:
    try:
        await asyncio.sleep(delay_sec)
        await msg.delete()
    except Exception:
        pass



def _clean_thread_hint_for_state(current_state: str, hint_key: str | None = None) -> str:
    hk = str(hint_key or "").strip().lower()
    s = str(current_state or "")

    if hk == "contact_mode":
        return "Нажми одну из кнопок выше: 🔒 Отклики через бота или 📞 Контакты в объявлении."

    if hk == "media_choice":
        return "Нажми одну из кнопок выше: ➕ Добавить медиа или ⏭ Без медиа."

    if hk == "media_wait":
        return "Сейчас нужен файл: отправь фото или короткое видео."

    if hk == "respond_intro_choice" or s.endswith(":form_intro_choice"):
        return "👆 Нажми кнопку «⚡ Откликнуться за 1 минуту» выше."

    if hk == "respond_saved_choice" or s.endswith(":form_saved_choice"):
        return "Нажми одну из кнопок выше: ⚡ Быстрый отклик или ✏️ Заполнить заново."

    if hk == "respond_form_preview" or s.endswith(":form_preview"):
        return "Используй кнопки выше: измени поле или отправь отклик."

    if s.endswith(":form_citizenship_pick"):
        return "Здесь нужно выбрать гражданство кнопкой выше. Если страны нет в списке — нажми «🌍 Другая страна»."

    if s.endswith(":media_confirm"):
        return "Нажми одну из кнопок выше: ✅ Подтвердить, 🔁 Заменить или 🗑 Удалить."

    if s.endswith(":preview"):
        return "Используй кнопки выше: исправить поле, изменить медиа или отправить объявление на модерацию."

    if s.endswith(":media_choice"):
        return "Нажми одну из кнопок выше."

    return "Нажми одну из кнопок выше."

def _is_private_event(event: Any) -> bool:
    msg = None
    if isinstance(event, Message):
        msg = event
    elif isinstance(event, CallbackQuery):
        msg = event.message
    if not msg:
        return False
    return getattr(msg.chat, "type", None) == "private"


class FSMWatchdogMiddleware(BaseMiddleware):
    _patched: bool = False

    def __init__(self) -> None:
        super().__init__()
        self.timeout_sec = _get_timeout_sec()
        self.cooldown_sec = _get_cooldown_sec()

        if not FSMWatchdogMiddleware._patched:
            self._patch_fsmcontext()
            FSMWatchdogMiddleware._patched = True
            logger.info("FSMWatchdogMiddleware: FSMContext patched")

    def _patch_fsmcontext(self) -> None:
        orig_set_state = FSMContext.set_state
        orig_update_data = FSMContext.update_data
        orig_clear = FSMContext.clear

        async def patched_set_state(self_ctx: FSMContext, state: Any) -> None:
            await orig_set_state(self_ctx, state)
            try:
                await orig_update_data(self_ctx, **{K_LAST_TS: _now_ts(), K_LAST_STATE: str(state)})
            except Exception:
                pass

        async def patched_update_data(self_ctx: FSMContext, **kwargs: Any) -> dict:
            try:
                kwargs.setdefault(K_LAST_TS, _now_ts())
            except Exception:
                pass
            return await orig_update_data(self_ctx, **kwargs)

        async def patched_clear(self_ctx: FSMContext) -> None:
            try:
                await orig_update_data(self_ctx, **{K_LAST_TS: 0, K_LAST_STATE: "", K_LAST_PROMPT_TS: 0})
            except Exception:
                pass
            await orig_clear(self_ctx)

        FSMContext.set_state = patched_set_state  # type: ignore[assignment]
        FSMContext.update_data = patched_update_data  # type: ignore[assignment]
        FSMContext.clear = patched_clear  # type: ignore[assignment]

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        if not _is_private_event(event):
            return await handler(event, data)

        state: Optional[FSMContext] = data.get("state")
        if state is None:
            return await handler(event, data)

        if isinstance(event, CallbackQuery) and isinstance(getattr(event, "data", None), str):
            if event.data in (FSM_WD_CONTINUE, FSM_WD_RESTART):
                return await handler(event, data)

        current_state = await state.get_state()
        st_data = await state.get_data()
        if isinstance(event, Message):
            try:
                logger.warning(
                    "FSM_WD_DEBUG user_id=%s state=%r keys=%s text=%r",
                    int(getattr(getattr(event, "from_user", None), "id", 0) or 0),
                    current_state,
                    sorted(list((st_data or {}).keys())),
                    ((getattr(event, "text", None) or getattr(event, "caption", None) or "")[:120]),
                )
            except Exception:
                pass

        # CLEAN THREAD callback-only guard v2
        if isinstance(event, Message):
            callback_only_states = {
                str(SeekerForm.preview),
                str(SeekerForm.media_choice),
                str(SeekerForm.media_confirm),
                str(SeekerForm.media_wait),
                str(EmployerForm.preview),
                str(EmployerForm.media_choice),
                str(EmployerForm.media_confirm),
            }
            current_state_s = str(current_state or "")
            if (
                current_state_s in callback_only_states
                or current_state_s.endswith(":form_citizenship_pick")
                or current_state_s.endswith(":form_preview")
                or current_state_s.endswith(":form_saved_choice")
                or current_state_s.endswith(":form_intro_choice")
            ):
                raw_text = ((getattr(event, "text", None) or getattr(event, "caption", None) or "")).strip()

                # Do not eat slash-commands like /start
                if raw_text.startswith("/"):
                    return await handler(event, data)

                try:
                    await event.delete()
                except Exception:
                    pass

                hint_now = _now_ts()
                try:
                    last_hint_ts = int(st_data.get("clean_thread_hint_ts") or 0)
                except Exception:
                    last_hint_ts = 0

                if (hint_now - last_hint_ts) >= 3:
                    try:
                        hint_key = st_data.get("clean_thread_hint_key")
                        hint = await event.answer(_clean_thread_hint_for_state(current_state, hint_key))
                        asyncio.create_task(_delete_message_later(hint, 2.5))
                    except Exception:
                        pass
                    try:
                        await state.update_data(**{"clean_thread_hint_ts": hint_now})
                    except Exception:
                        pass

                return None

        if not current_state:
            return await handler(event, data)

        st_data = await state.get_data()
        if st_data.get("on_moderation") is True:
            return await handler(event, data)

        now = _now_ts()
        last_ts = int(st_data.get(K_LAST_TS) or 0)

        if last_ts <= 0:
            try:
                await state.update_data(**{K_LAST_TS: now, K_LAST_STATE: str(current_state)})
            except Exception:
                pass
            return await handler(event, data)

        idle = now - last_ts
        if idle < self.timeout_sec:
            return await handler(event, data)

        last_prompt = int(st_data.get(K_LAST_PROMPT_TS) or 0)
        if (now - last_prompt) < self.cooldown_sec:
            return None

        try:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Продолжить", callback_data=FSM_WD_CONTINUE),
                        InlineKeyboardButton(text="🔄 Начать заново", callback_data=FSM_WD_RESTART),
                    ]
                ]
            )
            text = "Похоже, ты завис в анкете и давно не отвечал.\n\nЧто делаем?"

            if isinstance(event, Message):
                await event.answer(text, reply_markup=kb)
            elif isinstance(event, CallbackQuery) and event.message:
                await event.message.answer(text, reply_markup=kb)
                try:
                    await event.answer()
                except Exception:
                    pass
        except Exception as e:
            logger.exception("FSMWatchdogMiddleware: failed to send watchdog prompt: %s", e)

        try:
            await state.update_data(**{K_LAST_PROMPT_TS: now, K_LAST_STATE: str(current_state)})
        except Exception:
            pass

        return None
