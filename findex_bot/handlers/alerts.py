# findex_bot/handlers/alerts.py
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from findex_bot.utils.moscow_metro import (
    METRO_PICK_CALLBACK,
    METRO_LINE_CALLBACK,
    METRO_STATION_CALLBACK,
    METRO_CLOSE_CALLBACK,
    metro_location_keyboard,
    metro_lines_keyboard,
    metro_stations_keyboard,
    resolve_station,
    build_moscow_location,
)
from findex_bot.utils.moscow_metro import metro_location_keyboard

logger = logging.getLogger(__name__)
from findex_bot.utils.obs import log_event
router = Router()


# ---------------------------
# Lazy imports (anti-circular)
# ---------------------------
def _u():
    from findex_bot.utils import alerts as u  # type: ignore
    return u


def _menu_mod():
    from findex_bot.handlers import menu as menu_mod  # type: ignore
    return menu_mod


def _diag_mod():
    from findex_bot.handlers import diagnostics as diag  # type: ignore
    return diag


# ---------------------------
# FSM
# ---------------------------
class AlertFSM(StatesGroup):
    target_role = State()
    position = State()
    location = State()


# ---------------------------
# Callback constants
# ---------------------------
CB_MENU = "al_menu"
CB_NEW = "al_new"
CB_LIST = "al_list"
CB_BACK = "al_back"
CB_BACK_TO_MAIN = "al_back_main"
CB_RECHECK = "al_recheck"

# alias from menu.py
CB_OPEN_ALIAS = "alerts_open"


# ---------------------------
# Cleanup / temp UI helpers
# ---------------------------
CLEANUP_STATE_KEY = "_alerts_cleanup_message_ids"
TEMP_ALERT_SECONDS = 4


async def _temp_message(message: Message, text: str, seconds: int = TEMP_ALERT_SECONDS) -> None:
    msg = await message.answer(text)

    async def _delete_later() -> None:
        await asyncio.sleep(seconds)
        with contextlib.suppress(Exception):
            await msg.delete()

    asyncio.create_task(_delete_later())


async def _cleanup_reset(state: FSMContext) -> None:
    await state.update_data(**{CLEANUP_STATE_KEY: []})


async def _cleanup_track_message_id(state: FSMContext, message_id: int) -> None:
    data = await state.get_data()
    ids = list(data.get(CLEANUP_STATE_KEY, []) or [])
    if message_id not in ids:
        ids.append(int(message_id))
    await state.update_data(**{CLEANUP_STATE_KEY: ids})


async def _cleanup_track_user_message(state: FSMContext, message: Message) -> None:
    await _cleanup_track_message_id(state, int(message.message_id))


async def _cleanup_track_bot_message(state: FSMContext, message: Message) -> None:
    await _cleanup_track_message_id(state, int(message.message_id))


async def _cleanup_run(state: FSMContext, bot, chat_id: int) -> None:
    data = await state.get_data()
    ids = list(data.get(CLEANUP_STATE_KEY, []) or [])

    for message_id in ids:
        with contextlib.suppress(Exception):
            await bot.delete_message(chat_id=chat_id, message_id=int(message_id))

    await state.update_data(**{CLEANUP_STATE_KEY: []})


# ---------------------------
# Access / diagnostics
# ---------------------------
async def _alerts_access_state(bot, user_id: int) -> dict[str, Any]:
    """
    Толерантный адаптер под diagnostics._check_subscription():
    - (ok_sub, sub_line)
    - (ok_sub, sub_line, subscribe_url)
    - dict
    """
    diag = _diag_mod()

    ok_sub = False
    sub_line = "Подписка: нет (не подписан)"
    subscribe_url = ""

    try:
        res = await diag._check_subscription(bot, user_id)
    except Exception:
        logger.exception("alerts: _check_subscription failed user_id=%s", user_id)
        res = None

    try:
        if isinstance(res, dict):
            ok_sub = bool(res.get("ok_sub", res.get("ok", res.get("subscribed", False))))
            sub_line = str(res.get("sub_line", res.get("text", sub_line)) or sub_line)
            subscribe_url = str(res.get("subscribe_url", res.get("url", "")) or "")
        elif isinstance(res, (list, tuple)):
            if len(res) >= 3:
                ok_sub = bool(res[0])
                sub_line = str(res[1] or sub_line)
                subscribe_url = str(res[2] or "")
            elif len(res) == 2:
                ok_sub = bool(res[0])
                sub_line = str(res[1] or sub_line)
            elif len(res) == 1:
                ok_sub = bool(res[0])
    except Exception:
        logger.exception("alerts: failed to parse _check_subscription result user_id=%s", user_id)

    import findex_bot.runtime as runtime

    is_blocked = False
    try:
        is_blocked = bool(runtime.is_blocked(int(user_id)))
    except Exception:
        is_blocked = False

    return {
        "ok_sub": bool(ok_sub),
        "sub_line": str(sub_line or "Подписка: нет (не подписан)"),
        "subscribe_url": str(subscribe_url or ""),
        "is_blocked": bool(is_blocked),
    }


def _alerts_blocked_text() -> str:
    return (
        "🔔 <b>Уведомления / Алерты</b>\n\n"
        "⛔ Доступ к уведомлениям ограничен.\n\n"
        "Если это ошибка — обратись в поддержку."
    )


def _alerts_blocked_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=CB_BACK_TO_MAIN)],
        ]
    )


def _alerts_frozen_prefix(sub_line: str, subscribe_url: str) -> str:
    parts = [
        "🔔 <b>Уведомления / Алерты</b>",
        "",
        f"❌ {sub_line}",
    ]

    if subscribe_url:
        parts.append(f"👉 Подписаться: {subscribe_url}")
        parts.append("")

    parts.append("❌ Уведомления временно не работают, пока нет подписки на канал.")
    return "\n".join(parts)


def _alerts_frozen_home_keyboard(subscribe_url: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if subscribe_url:
        rows.append([InlineKeyboardButton(text="📣 Подписаться на канал", url=subscribe_url)])

    rows.append([InlineKeyboardButton(text="🔄 Проверить снова", callback_data=CB_RECHECK)])
    rows.append([InlineKeyboardButton(text="📋 Мои уведомления", callback_data=CB_LIST)])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=CB_BACK_TO_MAIN)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _guard_or_frozen(event: CallbackQuery | Message, access: dict[str, Any]) -> bool:
    """
    True  -> можно продолжать
    False -> доступ запрещён, экран уже показан
    """
    if access["is_blocked"]:
        text = _alerts_blocked_text()
        kb = _alerts_blocked_kb()

        if isinstance(event, CallbackQuery):
            try:
                await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                await event.message.answer(text, parse_mode="HTML", reply_markup=kb)
        else:
            await event.answer(text, parse_mode="HTML", reply_markup=kb)

        return False

    if not access["ok_sub"]:
        text = _alerts_frozen_prefix(access["sub_line"], access["subscribe_url"])
        kb = _alerts_frozen_home_keyboard(access["subscribe_url"])

        if isinstance(event, CallbackQuery):
            try:
                await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                await event.message.answer(text, parse_mode="HTML", reply_markup=kb)
        else:
            await event.answer(text, parse_mode="HTML", reply_markup=kb)

        return False

    return True


# ---------------------------
# Helpers
# ---------------------------
async def _set_menu_surface(user_id: int, surface: str) -> None:
    r = getattr(runtime, "REDIS", None)
    if r is None:
        return
    await r.set(f"menu:surface:{int(user_id)}", str(surface), ex=3600)


async def _clear_menu_surface(user_id: int) -> None:
    r = getattr(runtime, "REDIS", None)
    if r is None:
        return
    await r.delete(f"menu:surface:{int(user_id)}")


async def _safe_answer(cb: CallbackQuery, text: str | None = None, alert: bool = False):
    try:
        if text is None:
            await cb.answer()
        else:
            await cb.answer(text, show_alert=alert)
    except Exception:
        pass


def _clean_user_input(s: str) -> str:
    return " ".join((s or "").strip().split())


def _alerts_location_prompt() -> str:
    return (
        "Теперь введи <b>локацию</b>.\n"
        "Пример: <code>Москва</code>, <code>Тверская</code>, <code>Химки</code>\n\n"
        "Для Москвы рекомендуем указать метро — так объявление найдут быстрее."
    )


async def _edit_alerts_metro_card(cb: CallbackQuery, text: str, reply_markup=None) -> None:
    if not cb.message:
        return
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        if "message is not modified" in str(e).lower():
            return
        raise


async def _finish_alert_create(message: Message, state: FSMContext, *, owner_user_id: int, location_value: str) -> None:
    u = _u()

    st = await state.get_data()
    user_id = int(owner_user_id)

    target_role = st.get("target_role")
    position_raw = _clean_user_input(st.get("position_raw") or "")

    if target_role not in (u.ROLE_SEEKER, u.ROLE_EMPLOYER) or not position_raw:
        await _cleanup_run(state, message.bot, int(message.chat.id))
        await _temp_message(message, "⚠️ Состояние сбилось. Нажми ещё раз «Создать уведомление».")
        await state.clear()
        return

    try:
        a = await u.add_alert(user_id, target_role, position_raw, location_raw=location_value)
    except ValueError as e:
        await _temp_message(message, str(e))
        return
    except RuntimeError as e:
        await _cleanup_run(state, message.bot, int(message.chat.id))
        await _temp_message(message, str(e))
        await state.clear()
        return
    except Exception:
        await _cleanup_run(state, message.bot, int(message.chat.id))
        await _temp_message(message, "⚠️ Должность и локация обязательны. Попробуй ещё раз.")
        await state.clear()
        return

    await _cleanup_run(state, message.bot, int(message.chat.id))
    await state.clear()

    log_event(
        logger,
        "alert_created",
        user_id=user_id,
        role=target_role,
        location=location_value,
        position_raw=position_raw,
        alert_id=a.get("id"),
        source="metro",
        result="ok",
    )

    await message.answer(
        "✅ <b>Уведомление создано!</b>\n\n" + u.format_alert_line(a),
        parse_mode="HTML",
        reply_markup=u.alert_card_keyboard(a),
    )


def _welcome_text() -> str:
    return (
        "🔔 <b>Уведомления / Алерты</b>\n\n"
        "Фильтры: тип + должность + локация.\n"
        "Для Москвы можно указать метро (пример: Москва, Тверская).\n\n"
        "ℹ️ Доступ зависит от типа объявления:\n"
        "• Соискатель → 1 уведомление на 30 дней\n"
        "• Работодатель → 2 уведомления на 30 дней"
    )


def _alerts_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать уведомление", callback_data=CB_NEW)],
            [InlineKeyboardButton(text="📋 Мои уведомления", callback_data=CB_LIST)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=CB_BACK_TO_MAIN)],
        ]
    )


def _is_list_message(text: str | None) -> bool:
    t = (text or "").strip()
    return "Мои уведомления" in t


def _alerts_limits_diag_text(user_id: int, items: list[dict]) -> str:
    u = _u()

    seeker_active = len(u.active_alerts_for_role(items, u.ROLE_SEEKER))
    employer_active = len(u.active_alerts_for_role(items, u.ROLE_EMPLOYER))

    seeker_limit = u.get_max_alerts(user_id, u.ROLE_SEEKER)
    employer_limit = u.get_max_alerts(user_id, u.ROLE_EMPLOYER)

    return (
        "🧾 <b>Лимиты уведомлений</b>\n\n"
        f"👤 Соискатель: {seeker_active}/{seeker_limit}\n"
        f"💼 Работодатель: {employer_active}/{employer_limit}\n\n"
        "ℹ️ Уведомления действуют 30 дней."
    )


def _render_alerts_list_text(items: list[dict]) -> str:
    u = _u()
    lines = ["📋 <b>Мои уведомления</b>\n"]

    for i, a in enumerate(items, 1):
        lines.append(f"{i}. {u.format_alert_line(a)}")

    text = "\n\n".join(lines)
    if len(text) > 3900:
        text = text[:3900] + "\n\n…(список обрезан, слишком много уведомлений)"
    return text


def _render_alerts_list_kb(items: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for i, a in enumerate(items, 1):
        aid = str(a.get("id") or "")
        enabled = bool(a.get("enabled", True))

        toggle_text = ("🔕 Выкл" if enabled else "🔔 Вкл") + f" #{i}"
        del_text = "🗑 Удалить" + f" #{i}"

        rows.append(
            [
                InlineKeyboardButton(text=toggle_text, callback_data=f"al_toggle:{aid}"),
                InlineKeyboardButton(text=del_text, callback_data=f"al_del:{aid}"),
            ]
        )

    rows.append([InlineKeyboardButton(text="➕ Создать уведомление", callback_data=CB_NEW)])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=CB_BACK)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_frozen_list_kb(items: list[dict], subscribe_url: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if subscribe_url:
        rows.append([InlineKeyboardButton(text="📣 Подписаться на канал", url=subscribe_url)])

    rows.append([InlineKeyboardButton(text="🔄 Проверить снова", callback_data=CB_RECHECK)])

    for i, a in enumerate(items, 1):
        aid = str(a.get("id") or "")
        enabled = bool(a.get("enabled", True))

        toggle_text = f"🔕 Выкл #{i}" if enabled else f"🔒 Вкл #{i}"
        del_text = f"🗑 Удалить #{i}"

        rows.append(
            [
                InlineKeyboardButton(text=toggle_text, callback_data=f"al_toggle:{aid}"),
                InlineKeyboardButton(text=del_text, callback_data=f"al_del:{aid}"),
            ]
        )

    rows.append([InlineKeyboardButton(text="➕ Создать уведомление", callback_data=CB_NEW)])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=CB_BACK)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _edit_or_answer_message(
    cb: CallbackQuery,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception:
        await cb.message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


async def _show_alerts_home(cb: CallbackQuery) -> None:
    with contextlib.suppress(Exception):
        menu_mod = _menu_mod()
        await menu_mod._set_menu_surface(int(cb.from_user.id), "alerts_root")

    access = await _alerts_access_state(cb.bot, int(cb.from_user.id))

    ok = await _guard_or_frozen(cb, access)
    if not ok:
        return

    u = _u()
    user_id = int(cb.from_user.id)
    items = await u.get_user_alerts(user_id)

    text = _welcome_text() + "\n\n" + _alerts_limits_diag_text(user_id, items)

    await _edit_or_answer_message(
        cb,
        text=text,
        reply_markup=_alerts_home_keyboard(),
    )


async def _show_alerts_list(cb: CallbackQuery, user_id: int) -> None:
    with contextlib.suppress(Exception):
        menu_mod = _menu_mod()
        await menu_mod._clear_menu_surface(int(user_id))

    u = _u()
    access = await _alerts_access_state(cb.bot, user_id)

    if access["is_blocked"]:
        await _edit_or_answer_message(
            cb,
            text=_alerts_blocked_text(),
            reply_markup=_alerts_blocked_kb(),
        )
        return

    items = await u.get_user_alerts(user_id)

    if not items:
        base_text = "📋 <b>Мои уведомления</b>\n\nПока пусто. Нажми «➕ Создать уведомление»."
    else:
        base_text = _render_alerts_list_text(items)

    if not access["ok_sub"]:
        text = _alerts_frozen_prefix(access["sub_line"], access["subscribe_url"]) + "\n\n" + base_text
        kb = _render_frozen_list_kb(items, access["subscribe_url"])
    else:
        if not items:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Создать уведомление", callback_data=CB_NEW)],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=CB_BACK)],
                ]
            )
        else:
            kb = _render_alerts_list_kb(items)
        text = base_text

    await _edit_or_answer_message(cb, text=text, reply_markup=kb)


async def _edit_or_send_list(cb: CallbackQuery, user_id: int) -> None:
    await _show_alerts_list(cb, user_id)


# ============================================================
# UI entry points
# ============================================================
@router.message(Command("alerts"))
async def alerts_cmd(message: Message, state: FSMContext):
    with contextlib.suppress(Exception):
        await state.clear()

    log_event(
        logger,
        "alert_home_open",
        user_id=message.from_user.id,
        source="command",
        result="ok",
    )

    with contextlib.suppress(Exception):
        menu_mod = _menu_mod()
        await menu_mod._set_menu_surface(int(message.from_user.id), "alerts_root")

    access = await _alerts_access_state(message.bot, int(message.from_user.id))

    ok = await _guard_or_frozen(message, access)
    if not ok:
        return

    u = _u()
    user_id = int(message.from_user.id)
    items = await u.get_user_alerts(user_id)

    text = _welcome_text() + "\n\n" + _alerts_limits_diag_text(user_id, items)

    await message.answer(
        text,
        reply_markup=_alerts_home_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == CB_MENU)
async def alerts_menu(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    with contextlib.suppress(Exception):
        await state.clear()
    log_event(
        logger,
        "alert_home_open",
        user_id=cb.from_user.id,
        source="menu_callback",
        callback_data=cb.data,
        result="ok",
    )
    await _show_alerts_home(cb)


@router.callback_query(F.data == CB_OPEN_ALIAS)
async def alerts_open_alias(cb: CallbackQuery, state: FSMContext):
    await alerts_menu(cb, state)


@router.callback_query(F.data == CB_RECHECK)
async def alerts_recheck(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    with contextlib.suppress(Exception):
        await state.clear()
    log_event(
        logger,
        "alert_home_open",
        user_id=cb.from_user.id,
        source="recheck_callback",
        callback_data=cb.data,
        result="ok",
    )
    await _show_alerts_home(cb)


@router.callback_query(F.data == CB_NEW)
async def alerts_new(cb: CallbackQuery, state: FSMContext):
    u = _u()
    await _safe_answer(cb)

    log_event(
        logger,
        "alert_create_start",
        user_id=cb.from_user.id,
        callback_data=cb.data,
        result="ok",
    )

    access = await _alerts_access_state(cb.bot, int(cb.from_user.id))

    ok = await _guard_or_frozen(cb, access)
    if not ok:
        await state.clear()
        return

    await state.clear()
    await state.set_state(AlertFSM.target_role)
    await _cleanup_reset(state)

    text = (
        "Кого ловим уведомлением?\n\n"
        f"{u.limits_text(u.ROLE_SEEKER, cb.from_user.id)}\n"
        f"{u.limits_text(u.ROLE_EMPLOYER, cb.from_user.id)}\n\n"
        "Выбери тип объявлений:"
    )

    try:
        await cb.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=u.choose_target_keyboard(),
        )
    except Exception:
        msg = await cb.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=u.choose_target_keyboard(),
        )
        await _cleanup_track_bot_message(state, msg)


@router.callback_query(F.data.startswith("al_target:"))
async def alerts_pick_target(cb: CallbackQuery, state: FSMContext):
    u = _u()
    await _safe_answer(cb)

    access = await _alerts_access_state(cb.bot, int(cb.from_user.id))
    ok = await _guard_or_frozen(cb, access)
    if not ok:
        await state.clear()
        return

    pick = (cb.data or "").split(":", 1)[-1].strip()
    if pick not in (u.ROLE_SEEKER, u.ROLE_EMPLOYER):
        log_event(
            logger,
            "alert_target_picked",
            user_id=cb.from_user.id,
            callback_data=cb.data,
            result="fail",
        )
        await _safe_answer(cb, "⚠️ Неверный выбор", alert=True)
        return

    current_alerts = await u.get_user_alerts(int(cb.from_user.id))
    active_now = len(u.active_alerts_for_role(current_alerts, pick))
    max_allowed = u.get_max_alerts(int(cb.from_user.id), pick)

    if not u.can_create_alert(int(cb.from_user.id), pick, current_alerts):
        log_event(
            logger,
            "alert_target_limit_reached",
            user_id=cb.from_user.id,
            callback_data=cb.data,
            role=pick,
            active_now=active_now,
            max_allowed=max_allowed,
            result="limit_reached",
        )
        await state.clear()
        await _temp_message(
            cb.message,
            f"{u.LIMIT_REACHED_TEXT}\n\n"
            f"Сейчас занято: {active_now}/{max_allowed}",
        )
        return

    await state.update_data(target_role=pick)
    await state.set_state(AlertFSM.position)

    log_event(
        logger,
        "alert_target_picked",
        user_id=cb.from_user.id,
        callback_data=cb.data,
        role=pick,
        active_now=active_now,
        max_allowed=max_allowed,
        result="ok",
    )

    what = "резюме (соискателей)" if pick == u.ROLE_SEEKER else "вакансии (работодателей)"
    msg = await cb.message.answer(
        f"Ок. Будем ловить: <b>{what}</b>\n\n"
        f"{u.limits_text(pick, cb.from_user.id)}\n\n"
        "Теперь введи <b>одну вакансию</b>.\n"
        "Пример: <code>бариста</code>\n\n"
        "Один алерт = одна вакансия.",
        parse_mode="HTML",
    )
    await _cleanup_track_bot_message(state, msg)


@router.message(AlertFSM.position)
async def alerts_set_position(message: Message, state: FSMContext):
    access = await _alerts_access_state(message.bot, int(message.from_user.id))
    ok = await _guard_or_frozen(message, access)
    if not ok:
        await state.clear()
        return

    await _cleanup_track_user_message(state, message)

    raw = _clean_user_input(message.text or "")
    if not raw:
        log_event(
            logger,
            "alert_position_accepted",
            user_id=message.from_user.id,
            result="fail",
        )
        await _temp_message(message, "⚠️ Введи вакансию.")
        return

    parts = [x.strip() for x in raw.split(",") if x.strip()]
    if len(parts) != 1:
        log_event(
            logger,
            "alert_position_accepted",
            user_id=message.from_user.id,
            position_raw=raw,
            result="fail",
        )
        await _temp_message(
            message,
            "⚠️ Один алерт можно настроить только на одну вакансию. Для каждой вакансии создай отдельный алерт.",
        )
        return

    await state.update_data(position_raw=raw)
    await state.set_state(AlertFSM.location)

    log_event(
        logger,
        "alert_position_accepted",
        user_id=message.from_user.id,
        position_raw=raw,
        result="ok",
    )

    msg = await message.answer(
        "Теперь введи <b>локацию</b>.\n"
        "Пример: <code>Москва</code>, <code>Тверская</code>, <code>Химки</code>\n\n"
        "Для Москвы рекомендуем указать метро — так объявление найдут быстрее.",
        parse_mode="HTML",
        reply_markup=metro_location_keyboard(),
    )
    await _cleanup_track_bot_message(state, msg)


@router.message(AlertFSM.location)
async def alerts_set_location(message: Message, state: FSMContext):
    u = _u()

    access = await _alerts_access_state(message.bot, int(message.from_user.id))
    ok = await _guard_or_frozen(message, access)
    if not ok:
        await state.clear()
        return

    await _cleanup_track_user_message(state, message)

    loc = _clean_user_input(message.text or "")
    if not loc:
        log_event(
            logger,
            "alert_location_text",
            user_id=message.from_user.id,
            result="fail",
        )
        await _temp_message(message, "⚠️ Локация обязательна. Введи локацию текстом.")
        return

    st = await state.get_data()
    user_id = int(message.from_user.id)

    target_role = st.get("target_role")
    position_raw = _clean_user_input(st.get("position_raw") or "")

    if target_role not in (u.ROLE_SEEKER, u.ROLE_EMPLOYER) or not position_raw:
        await _cleanup_run(state, message.bot, int(message.chat.id))
        await _temp_message(message, "⚠️ Состояние сбилось. Нажми ещё раз «Создать уведомление».")
        await state.clear()
        return

    try:
        a = await u.add_alert(user_id, target_role, position_raw, location_raw=loc)
    except ValueError as e:
        await _temp_message(message, str(e))
        return
    except RuntimeError as e:
        await _cleanup_run(state, message.bot, int(message.chat.id))
        await _temp_message(message, str(e))
        await state.clear()
        return
    except Exception:
        await _cleanup_run(state, message.bot, int(message.chat.id))
        await _temp_message(message, "⚠️ Должность и локация обязательны. Попробуй ещё раз.")
        await state.clear()
        return

    await _cleanup_run(state, message.bot, int(message.chat.id))
    await state.clear()

    log_event(
        logger,
        "alert_created",
        user_id=message.from_user.id,
        role=target_role,
        location=loc,
        position_raw=position_raw,
        alert_id=a.get("id"),
        source="text",
        result="ok",
    )

    await message.answer(
        "✅ <b>Уведомление создано!</b>\n\n" + u.format_alert_line(a),
        parse_mode="HTML",
        reply_markup=u.alert_card_keyboard(a),
    )


@router.callback_query(StateFilter(AlertFSM.location), F.data == METRO_CLOSE_CALLBACK)
async def alerts_metro_close(cb: CallbackQuery):
    await _safe_answer(cb)
    try:
        await _edit_alerts_metro_card(cb, _alerts_location_prompt(), reply_markup=metro_location_keyboard())
    except Exception:
        pass


@router.callback_query(StateFilter(AlertFSM.location), F.data.startswith(METRO_PICK_CALLBACK))
async def alerts_metro_pick(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)

    log_event(
        logger,
        "alert_metro_open",
        user_id=cb.from_user.id,
        callback_data=cb.data,
        result="ok",
    )

    access = await _alerts_access_state(cb.bot, int(cb.from_user.id))
    ok = await _guard_or_frozen(cb, access)
    if not ok:
        await state.clear()
        return

    parts = (cb.data or "").split(":")
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    try:
        await _edit_alerts_metro_card(cb, "Выбери линию метро Москвы:", reply_markup=metro_lines_keyboard(page))
    except Exception:
        pass


@router.callback_query(StateFilter(AlertFSM.location), F.data.startswith(METRO_LINE_CALLBACK + ":"))
async def alerts_metro_line_pick(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)

    log_event(
        logger,
        "alert_metro_line_open",
        user_id=cb.from_user.id,
        callback_data=cb.data,
        result="ok",
    )

    access = await _alerts_access_state(cb.bot, int(cb.from_user.id))
    ok = await _guard_or_frozen(cb, access)
    if not ok:
        await state.clear()
        return

    parts = (cb.data or "").split(":")
    if len(parts) < 3:
        return
    line_uid = parts[1]
    page = int(parts[2]) if parts[2].isdigit() else 0
    try:
        await _edit_alerts_metro_card(cb, "Выбери станцию метро:", reply_markup=metro_stations_keyboard(line_uid, page))
    except Exception:
        pass


@router.callback_query(StateFilter(AlertFSM.location), F.data.startswith(METRO_STATION_CALLBACK + ":"))
async def alerts_metro_station_pick(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)

    access = await _alerts_access_state(cb.bot, int(cb.from_user.id))
    ok = await _guard_or_frozen(cb, access)
    if not ok:
        await state.clear()
        return

    if not cb.message:
        return

    parts = (cb.data or "").split(":")
    if len(parts) < 3 or not parts[2].isdigit():
        return

    line_uid = parts[1]
    station = resolve_station(line_uid, int(parts[2]))
    if not station:
        log_event(
            logger,
            "alert_metro_station_pick",
            user_id=cb.from_user.id,
            callback_data=cb.data,
            result="fail",
        )
        await _safe_answer(cb, "⚠️ Не удалось определить станцию", alert=True)
        return

    location_value = build_moscow_location(station)
    log_event(
        logger,
        "alert_metro_station_pick",
        user_id=cb.from_user.id,
        callback_data=cb.data,
        station=location_value,
        result="delegated",
    )
    await _finish_alert_create(cb.message, state, owner_user_id=int(cb.from_user.id), location_value=location_value)


@router.callback_query(F.data == CB_LIST)
async def alerts_list(cb: CallbackQuery):
    await _safe_answer(cb)
    user_id = int(cb.from_user.id)
    log_event(
        logger,
        "alert_list_open",
        user_id=user_id,
        callback_data=cb.data,
        result="ok",
    )
    await _show_alerts_list(cb, user_id)


@router.callback_query(F.data.startswith("al_toggle:"))
async def alerts_toggle(cb: CallbackQuery):
    u = _u()
    await _safe_answer(cb)

    user_id = int(cb.from_user.id)
    alert_id = (cb.data or "").split(":", 1)[-1].strip()

    alerts = await u.get_user_alerts(user_id)
    current = None
    for a in alerts:
        if str(a.get("id") or "") == alert_id:
            current = a
            break

    if current is None:
        log_event(
            logger,
            "alert_toggle",
            user_id=user_id,
            alert_id=alert_id,
            callback_data=cb.data,
            result="not_found",
        )
        await _safe_answer(cb, "⚠️ Алерт не найден", alert=True)
        return

    access = await _alerts_access_state(cb.bot, user_id)

    if access["is_blocked"]:
        await _safe_answer(cb, "⚠️ Доступ ограничен", alert=True)
        await _show_alerts_list(cb, user_id)
        return

    currently_enabled = bool(current.get("enabled", True))

    if not access["ok_sub"] and not currently_enabled:
        await _safe_answer(cb, "⚠️ Нужна подписка на канал", alert=True)
        await _show_alerts_list(cb, user_id)
        return

    changed = await u.toggle_alert(user_id, alert_id)
    if not changed:
        log_event(
            logger,
            "alert_toggle",
            user_id=user_id,
            alert_id=alert_id,
            callback_data=cb.data,
            result="not_found",
        )
        await _safe_answer(cb, "⚠️ Алерт не найден", alert=True)
        return

    log_event(
        logger,
        "alert_toggle",
        user_id=user_id,
        alert_id=alert_id,
        callback_data=cb.data,
        enabled=changed.get("enabled"),
        result="ok",
    )

    if _is_list_message(getattr(cb.message, "text", None)):
        await _edit_or_send_list(cb, user_id)
        return

    try:
        await cb.message.edit_text(
            u.format_alert_line(changed),
            parse_mode="HTML",
            reply_markup=u.alert_card_keyboard(changed),
        )
    except Exception:
        await cb.message.answer(
            u.format_alert_line(changed),
            parse_mode="HTML",
            reply_markup=u.alert_card_keyboard(changed),
        )


@router.callback_query(F.data.startswith("al_del:"))
async def alerts_delete(cb: CallbackQuery):
    u = _u()
    await _safe_answer(cb)

    user_id = int(cb.from_user.id)
    alert_id = (cb.data or "").split(":", 1)[-1].strip()

    access = await _alerts_access_state(cb.bot, user_id)
    if access["is_blocked"]:
        await _safe_answer(cb, "⚠️ Доступ ограничен", alert=True)
        await _show_alerts_list(cb, user_id)
        return

    ok = await u.delete_alert(user_id, alert_id)
    if not ok:
        log_event(
            logger,
            "alert_delete",
            user_id=user_id,
            alert_id=alert_id,
            callback_data=cb.data,
            result="not_found",
        )
        await _safe_answer(cb, "⚠️ Не найдено", alert=True)
        return

    log_event(
        logger,
        "alert_delete",
        user_id=user_id,
        alert_id=alert_id,
        callback_data=cb.data,
        result="ok",
    )

    if _is_list_message(getattr(cb.message, "text", None)):
        await _edit_or_send_list(cb, user_id)
        return

    try:
        await cb.message.edit_text(
            "🗑 Удалено",
            reply_markup=_alerts_home_keyboard(),
        )
    except Exception:
        await cb.message.answer(
            "🗑 Удалено",
            reply_markup=_alerts_home_keyboard(),
        )


@router.callback_query(F.data == CB_BACK)
async def alerts_back(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    await state.clear()
    log_event(
        logger,
        "alert_back_home",
        user_id=cb.from_user.id,
        callback_data=cb.data,
        result="ok",
    )
    await _show_alerts_home(cb)


@router.callback_query(F.data == CB_BACK_TO_MAIN)
async def alerts_back_to_main(cb: CallbackQuery, state: FSMContext):
    await _safe_answer(cb)
    await state.clear()
    log_event(
        logger,
        "alert_back_main",
        user_id=cb.from_user.id,
        callback_data=cb.data,
        result="ok",
    )
    menu_mod = _menu_mod()
    await menu_mod._send_or_edit_menu(cb)


# ============================================================
# PUBLIC API: forms.py ждёт именно это имя
# ============================================================
async def fire_alerts_on_publish(bot, ad: Any, url: str | None = None):
    u = _u()

    def _get(obj: Any, key: str, default: Any = "") -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    ad_id = str(_get(ad, "id", "")) or "0"

    payload = _get(ad, "payload", {}) or {}
    if not isinstance(payload, dict):
        payload = {}

    role = (payload.get("role") or _get(ad, "role", "") or "").strip()

    position = (
        payload.get("position")
        or payload.get("title")
        or _get(ad, "position", "")
        or _get(ad, "title", "")
        or ""
    ).strip()

    location = (
        payload.get("location")
        or payload.get("city")
        or _get(ad, "location", "")
        or _get(ad, "city", "")
        or ""
    ).strip()

    ad_data = {"role": role, "position": position, "location": location}

    try:
        publisher_user_id = int(
            payload.get("author_id")
            or _get(ad, "author_user_id", 0)
            or _get(ad, "author_id", 0)
            or 0
        )
    except Exception:
        publisher_user_id = 0

    await u.notify_on_published(
        bot,
        ad_data=ad_data,
        url=url or "",
        ad_id=ad_id,
        publisher_user_id=publisher_user_id,
    )