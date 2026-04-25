# 4) findex_bot/handlers/fsm_watchdog.py

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)
router = Router()

CB_CONTINUE = "fsmwd:continue"
CB_RESTART = "fsmwd:restart"


async def _safe_answer(cb: CallbackQuery, text: str | None = None, alert: bool = False):
    try:
        if text is None:
            await cb.answer()
        else:
            await cb.answer(text, show_alert=alert)
    except Exception:
        pass


async def _safe_delete_message(cb: CallbackQuery):
    try:
        if cb.message:
            await cb.message.delete()
    except Exception:
        pass


def _state_key(state_name: Optional[str]) -> str:
    return (state_name or "").strip()


def _prompt_for_state(state_name: Optional[str]) -> str | None:
    s = _state_key(state_name)

    # Наши реальные states: title/schedule/salary/location/contacts/description/media_choice/media_wait/media_confirm/preview
    prompts: dict[str, str] = {
        # -------- SeekerForm --------
        "SeekerForm:title": "👤 Должность:",
        "SeekerForm:schedule": "🕒 График:",
        "SeekerForm:salary": "💲 Зарплата:",
        "SeekerForm:location": "📍 Локация:",
        "SeekerForm:contacts": (
            "📞 Контакты:\n"
            "ℹ️ Подсказка по контактам:\n"
            "• Telegram: @username\n"
            "• Телефон: +7 999 123-45-67\n"
            "• Email: name@mail.com\n"
            "• Любой удобный способ связи"
        ),
        "SeekerForm:description": "📝 О себе:",
        "SeekerForm:media_choice": "🖼 Фото:",
        "SeekerForm:media_wait": "Пришли ОДНО фото одним сообщением.",
        "SeekerForm:media_confirm": "Принял файл. Подтверждаешь?",
        "SeekerForm:preview": "Ты в предпросмотре. Можешь нажать кнопку поля и отредактировать.",

        # -------- EmployerForm --------
        "EmployerForm:title": "👤 Должность:",
        "EmployerForm:salary": "💲 Зарплата:",
        "EmployerForm:location": "📍 Локация:",
        "EmployerForm:contacts": (
            "📞 Контакты:\n"
            "ℹ️ Подсказка по контактам:\n"
            "• Telegram: @username\n"
            "• Телефон: +7 999 123-45-67\n"
            "• Email: name@mail.com\n"
            "• Любой удобный способ связи"
        ),
        "EmployerForm:description": "📝 Описание:",
        "EmployerForm:media_choice": "🎞 Медиа:",
        "EmployerForm:media_wait": "Пришли ОДНО фото или ОДНО короткое видео одним сообщением.",
        "EmployerForm:media_confirm": "Принял файл. Подтверждаешь?",
        "EmployerForm:preview": "Ты в предпросмотре. Можешь нажать кнопку поля и отредактировать.",
    }

    return prompts.get(s)


@router.callback_query(F.data.in_({CB_CONTINUE, "fsm_watchdog:continue", "watchdog:continue"}))
async def fsm_watchdog_continue(cb: CallbackQuery, state: FSMContext):
    current = await state.get_state()
    prompt = _prompt_for_state(current)

    await _safe_delete_message(cb)

    if prompt:
        if cb.message:
            await cb.message.answer(prompt)
        else:
            await cb.bot.send_message(cb.from_user.id, prompt)
        await _safe_answer(cb)
        return

    text = (
        "Продолжаем.\n\n"
        "Я вижу, что ты в процессе анкеты, но не могу определить конкретный шаг.\n"
        "Просто отправь следующий ответ по анкете, и я подхвачу."
    )
    if cb.message:
        await cb.message.answer(text)
    else:
        await cb.bot.send_message(cb.from_user.id, text)
    await _safe_answer(cb)


@router.callback_query(F.data.in_({CB_RESTART, "fsm_watchdog:restart", "watchdog:restart"}))
async def fsm_watchdog_restart(cb: CallbackQuery, state: FSMContext):
    await _safe_delete_message(cb)
    await state.clear()

    text = "Ок, начинаем заново ✅\nНажми /start и выбери сценарий заново."
    if cb.message:
        await cb.message.answer(text)
    else:
        await cb.bot.send_message(cb.from_user.id, text)

    await _safe_answer(cb)
