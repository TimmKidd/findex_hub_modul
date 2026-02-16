# findex_bot/handlers/alerts.py
from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from findex_bot.utils.alerts import (
    ROLE_SEEKER,
    ROLE_EMPLOYER,
    add_alert,
    get_user_alerts,
    toggle_alert,
    delete_alert,
    format_alert_line,
    alerts_menu_keyboard,
    choose_target_keyboard,
    alert_card_keyboard,
)

logger = logging.getLogger(__name__)
router = Router()


class AlertFSM(StatesGroup):
    target_role = State()
    position = State()
    location = State()  # ✅ обязательна


CB_MENU = "al_menu"
CB_NEW = "al_new"
CB_LIST = "al_list"
CB_BACK = "al_back"


async def _safe_answer(cb: CallbackQuery, text: str | None = None, alert: bool = False):
    try:
        if text is None:
            await cb.answer()
        else:
            await cb.answer(text, show_alert=alert)
    except Exception:
        pass


def _clean_user_input(s: str) -> str:
    # минимальная чистка без “магии”: убираем лишние пробелы
    return " ".join((s or "").strip().split())


@router.message(Command("alerts"))
async def alerts_cmd(message: Message):
    await message.answer(
        "🔔 <b>Уведомления / Алерты</b>\n\n"
        "Алерт всегда состоит из 3 якорей:\n"
        "1) <b>роль</b> (Соискатель / Работодатель)\n"
        "2) <b>должность</b>\n"
        "3) <b>локация</b>\n",
        reply_markup=alerts_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == CB_MENU)
async def alerts_menu(cb: CallbackQuery):
    await _safe_answer(cb)
    await cb.message.answer(
        "🔔 <b>Уведомления / Алерты</b>",
        reply_markup=alerts_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == CB_NEW)
async def alerts_new(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    await state.clear()
    await state.set_state(AlertFSM.target_role)
    await cb.message.answer(
        "Кого ловим уведомлением?\n\nВыбери тип объявлений:",
        reply_markup=choose_target_keyboard(),
    )


@router.callback_query(F.data.startswith("al_target:"))
async def alerts_pick_target(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)

    pick = (cb.data or "").split(":", 1)[-1].strip()
    if pick not in (ROLE_SEEKER, ROLE_EMPLOYER):
        await _safe_answer(cb, "⚠️ Неверный выбор", alert=True)
        return

    await state.update_data(target_role=pick)
    await state.set_state(AlertFSM.position)

    what = "резюме (соискателей)" if pick == ROLE_SEEKER else "вакансии (работодателей)"
    await cb.message.answer(
        f"Ок. Будем ловить: <b>{what}</b>\n\n"
        "Теперь введи ключевые слова по <b>должности</b>.\n"
        "Пример: <code>кальянщик, бариста, официант</code>\n\n"
        "Можно одно слово или через запятую.",
        parse_mode="HTML",
    )


@router.message(AlertFSM.position)
async def alerts_set_position(message: Message, state: FSMContext):
    raw = _clean_user_input(message.text or "")
    if not raw:
        await message.answer("⚠️ Введи ключевые слова по должности.")
        return

    # ничего не парсим здесь — парсит add_alert внутри utils
    await state.update_data(position_raw=raw)
    await state.set_state(AlertFSM.location)

    await message.answer(
        "Теперь введи <b>локацию</b>.\n"
        "Пример: <code>Москва</code>, <code>Тверская</code>, <code>Химки</code>\n\n"
        "Для Москвы рекомендуем указать метро — так объявление найдут быстрее.",
        parse_mode="HTML",
    )


@router.message(AlertFSM.location)
async def alerts_set_location(message: Message, state: FSMContext):
    loc = _clean_user_input(message.text or "")
    if not loc:
        await message.answer("⚠️ Локация обязательна. Введи локацию текстом.")
        return

    st = await state.get_data()
    user_id = int(message.from_user.id)

    target_role = st.get("target_role")
    position_raw = _clean_user_input(st.get("position_raw") or "")

    if target_role not in (ROLE_SEEKER, ROLE_EMPLOYER) or not position_raw:
        await message.answer("⚠️ Состояние сбилось. Нажми ещё раз «Создать уведомление».")
        await state.clear()
        return

    try:
        a = await add_alert(user_id, target_role, position_raw, location_raw=loc)
    except Exception:
        await message.answer("⚠️ Должность и локация обязательны. Попробуй ещё раз.")
        await state.clear()
        return

    await state.clear()

    await message.answer(
        "✅ <b>Уведомление создано!</b>\n\n" + format_alert_line(a),
        parse_mode="HTML",
        reply_markup=alert_card_keyboard(a),
    )


@router.callback_query(F.data == CB_LIST)
async def alerts_list(cb: CallbackQuery):
    await _safe_answer(cb)

    user_id = int(cb.from_user.id)
    items = await get_user_alerts(user_id)

    if not items:
        await cb.message.answer(
            "📋 <b>Мои уведомления</b>\n\nПока пусто. Нажми «➕ Создать уведомление».",
            parse_mode="HTML",
            reply_markup=alerts_menu_keyboard(),
        )
        return

    await cb.message.answer("📋 <b>Мои уведомления</b>", parse_mode="HTML")

    # карточки: каждая со своими кнопками (toggle/del/back)
    for a in items:
        try:
            await cb.message.answer(
                format_alert_line(a),
                parse_mode="HTML",
                reply_markup=alert_card_keyboard(a),
            )
        except Exception:
            continue


@router.callback_query(F.data.startswith("al_toggle:"))
async def alerts_toggle(cb: CallbackQuery):
    await _safe_answer(cb)

    user_id = int(cb.from_user.id)
    alert_id = (cb.data or "").split(":", 1)[-1].strip()

    changed = await toggle_alert(user_id, alert_id)
    if not changed:
        await _safe_answer(cb, "⚠️ Алерт не найден", alert=True)
        return

    # обновляем текущую карточку (это и есть “канон” UX)
    try:
        await cb.message.edit_text(
            format_alert_line(changed),
            parse_mode="HTML",
            reply_markup=alert_card_keyboard(changed),
        )
    except Exception:
        await cb.message.answer(
            format_alert_line(changed),
            parse_mode="HTML",
            reply_markup=alert_card_keyboard(changed),
        )


@router.callback_query(F.data.startswith("al_del:"))
async def alerts_delete(cb: CallbackQuery):
    await _safe_answer(cb)

    user_id = int(cb.from_user.id)
    alert_id = (cb.data or "").split(":", 1)[-1].strip()

    ok = await delete_alert(user_id, alert_id)
    if not ok:
        await _safe_answer(cb, "⚠️ Не найдено", alert=True)
        return

    # гасим карточку
    try:
        await cb.message.edit_text(
            "🗑 Удалено",
            reply_markup=alerts_menu_keyboard(),
        )
    except Exception:
        await cb.message.answer(
            "🗑 Удалено",
            reply_markup=alerts_menu_keyboard(),
        )


@router.callback_query(F.data == CB_BACK)
async def alerts_back(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    await state.clear()
    await cb.message.answer(
        "🔔 <b>Уведомления / Алерты</b>",
        parse_mode="HTML",
        reply_markup=alerts_menu_keyboard(),
    )