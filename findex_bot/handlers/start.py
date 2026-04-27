# findex_bot/handlers/start.py
from __future__ import annotations

import asyncio
import logging
import contextlib

import findex_bot.runtime as runtime
from findex_bot.utils.ui_surface import enter_surface, get_surface

from aiogram import Router, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from findex_bot.utils.hints_registry import (
    MENU_ALERTS_ROOT_TRASH,
    MENU_DIAG_PUBLICATION_TRASH,
    MENU_DIAG_PENDING_CARD_TRASH,
    MENU_RESPONDS_ROOT_TRASH,
    MENU_ROOT_TRASH,
    RESPOND_ACTIVE_CARD_TRASH,
    WELCOME_ROLES_TRASH,
    get_hint_text,
)
from findex_bot.utils.obs import log_event

router = Router()
logger = logging.getLogger(__name__)

# Эти callback_data должны обрабатываться ТОЛЬКО в:
# - findex_bot/handlers/employer.py  (@router.callback_query(F.data == "vac_employer"))
# - findex_bot/handlers/seeker.py    (@router.callback_query(F.data == "vac_seeker"))
CB_VAC_EMPLOYER = "vac_employer"
CB_VAC_SEEKER = "vac_seeker"


def _roles_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏢 Работодатель", callback_data=CB_VAC_EMPLOYER)],
            [InlineKeyboardButton(text="👤 Соискатель", callback_data=CB_VAC_SEEKER)],
        ]
    )


async def _safe_cb_answer(cb: CallbackQuery, text: str | None = None, alert: bool = False) -> None:
    try:
        if text is None:
            await cb.answer()
        else:
            await cb.answer(text, show_alert=alert)
    except Exception:
        pass


async def show_roles(message_or_cb: Message | CallbackQuery, state: FSMContext) -> None:
    """
    Единая функция показа выбора роли.
    Используется и в /start, и в кнопке "Меню вакансий" (vacancies_menu).

    ВАЖНО:
    - тут НЕЛЬЗЯ делать state.set_state(...)
    - тут НЕЛЬЗЯ создавать draft / писать ad_id
    Потому что draft создаётся строго в employer.py/seeker.py по нажатию кнопок роли.
    """
    with contextlib.suppress(Exception):
        r = getattr(runtime, "REDIS", None)
        u = getattr(message_or_cb, "from_user", None)
        if r is not None and u is not None:
            await r.delete(f"menu:root_view:{int(u.id)}")
            await r.delete(f"menu:surface:{int(u.id)}")
            await r.delete(f"respond:active_view:{int(u.id)}")

    with contextlib.suppress(Exception):
        u = getattr(message_or_cb, "from_user", None)
        if u is not None:
            await enter_surface(int(u.id), "roles")

    u = getattr(message_or_cb, "from_user", None)
    log_event(
        logger,
        "roles_open",
        user_id=getattr(u, "id", None),
        source="message" if isinstance(message_or_cb, Message) else "callback",
        result="ok",
    )

    await state.clear()

    text = "👋 Добро пожаловать в FindexHub!\n\nВыбери роль:"
    kb = _roles_kb()

    if isinstance(message_or_cb, Message):
        await message_or_cb.answer(text, reply_markup=kb)
        return

    cb = message_or_cb
    await _safe_cb_answer(cb)

    # Иногда callback может прийти без message — отправим в личку
    if not cb.message:
        try:
            await cb.bot.send_message(chat_id=cb.from_user.id, text=text, reply_markup=kb)
        except Exception:
            pass
        return

    # Если можно — редактируем текущее, иначе отправим новое
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        try:
            await cb.message.answer(text, reply_markup=kb)
        except Exception:
            pass


@router.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    raw = (getattr(message, "text", "") or "").strip()

    if raw.startswith("/start resp_"):
        return await start_from_deeplink(message, state)

    await show_roles(message, state)


@router.callback_query(F.data == "vacancies_menu")
async def vacancies_menu(callback: CallbackQuery, state: FSMContext):
    await show_roles(callback, state)


WELCOME_CLEAN_THREAD_HINT = get_hint_text(WELCOME_ROLES_TRASH)





async def _has_active_respond_view(user_id: int) -> bool:
    try:
        r = getattr(runtime, "REDIS", None)
        if r is None:
            return False
        v = await r.get(f"respond:active_view:{int(user_id)}")
        return bool(v)
    except Exception:
        return False




async def _get_menu_surface(user_id: int) -> str | None:
    try:
        r = getattr(runtime, "REDIS", None)
        if r is None:
            return None
        v = await r.get(f"menu:surface:{int(user_id)}")
        if not v:
            return None
        if isinstance(v, bytes):
            try:
                return v.decode("utf-8", errors="ignore") or None
            except Exception:
                return None
        return str(v) or None
    except Exception:
        return None


async def _send_welcome_clean_thread_hint(message: Message) -> None:
    hint = None
    try:
        hint = await message.bot.send_message(
            chat_id=message.chat.id,
            text=WELCOME_CLEAN_THREAD_HINT,
        )
        await asyncio.sleep(4)
    except Exception:
        return
    finally:
        with contextlib.suppress(Exception):
            if hint:
                await hint.delete()


@router.message(StateFilter(None), F.text)
async def welcome_menu_clean_thread(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw:
        return
    if raw.startswith("/"):
        return

    current_state = await state.get_state()
    if current_state:
        return

    with contextlib.suppress(Exception):
        await message.delete()

    user_id = int(message.from_user.id)
    shadow_surface = None
    with contextlib.suppress(Exception):
        shadow_surface = await get_surface(user_id)

    legacy_surface = None
    hint_text = None

    if await _has_active_respond_view(user_id):
        legacy_surface = "respond_active_card"
        hint_text = get_hint_text(RESPOND_ACTIVE_CARD_TRASH)
    else:
        surface = await _get_menu_surface(user_id)
        if surface == "root":
            legacy_surface = "menu_root"
            hint_text = get_hint_text(MENU_ROOT_TRASH)
        elif surface == "diag_publication":
            legacy_surface = "menu_diag_publication"
            hint_text = get_hint_text(MENU_DIAG_PUBLICATION_TRASH)
        elif surface == "diag_pending_card":
            legacy_surface = "menu_diag_pending_card"
            hint_text = get_hint_text(MENU_DIAG_PENDING_CARD_TRASH)
        elif surface == "alerts_root":
            legacy_surface = "menu_alerts_root"
            hint_text = get_hint_text(MENU_ALERTS_ROOT_TRASH)
        elif surface == "responds_root":
            legacy_surface = "menu_responds_root"
            hint_text = get_hint_text(MENU_RESPONDS_ROOT_TRASH)
        else:
            legacy_surface = "roles"
            hint_text = get_hint_text(WELCOME_ROLES_TRASH)

    if shadow_surface and shadow_surface != legacy_surface:
        logger.warning(
            "start fallback shadow mismatch: user_id=%s legacy_surface=%s shadow_surface=%s",
            user_id,
            legacy_surface,
            shadow_surface,
        )

    if hint_text:
        log_event(
            logger,
            "start_clean_thread_trash",
            user_id=user_id,
            legacy_surface=legacy_surface,
            shadow_surface=shadow_surface,
            result="ok",
        )
        hint = None
        try:
            hint = await message.bot.send_message(
                chat_id=message.chat.id,
                text=hint_text,
            )
            await asyncio.sleep(4)
        except Exception:
            return
        finally:
            with contextlib.suppress(Exception):
                if hint:
                    await hint.delete()
        return

    await _send_welcome_clean_thread_hint(message)

