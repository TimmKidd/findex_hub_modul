# findex_bot/handlers/menu.py
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

import findex_bot.runtime as runtime

from findex_bot.handlers.diagnostics import send_diagnostics
from findex_bot.handlers.start import show_roles  # ✅ используем единую логику /start

router = Router()

CB_DIAG = "menu_diag"
CB_START = "menu_start"
CB_ALERTS = "alerts_open"  # ✅ вход в алерты (handlers/alerts.py)


def _menu_kb(channel_username: str) -> InlineKeyboardMarkup:
    channel_username = (channel_username or "").lstrip("@").strip()
    channel_url = f"https://t.me/{channel_username}" if channel_username else "https://t.me/"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Уведомления", callback_data=CB_ALERTS)],  # ✅ АЛЕРТЫ
            [InlineKeyboardButton(text="🛠 Диагностика", callback_data=CB_DIAG)],
            [InlineKeyboardButton(text="🆘 Support", url="https://t.me/Findex_support_bot")],
            [InlineKeyboardButton(text="📣 Канал — обязательная подписка", url=channel_url)],
            [InlineKeyboardButton(text="▶️ Start", callback_data=CB_START)],
        ]
    )


def _get_channel_username_from_runtime() -> str:
    try:
        cfg = getattr(runtime, "CONFIG", None)
        if not cfg:
            return ""
        return getattr(cfg, "channel_username", "") or ""
    except Exception:
        return ""


@router.message(Command("menu"))
async def menu_cmd(message: Message):
    kb = _menu_kb(_get_channel_username_from_runtime())
    await message.answer(
        "📋 <b>Главное меню FindexHub</b>\n\nВыбери нужный раздел:",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data == CB_DIAG)
async def menu_diag(callback: CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass

    if not callback.message:
        try:
            await callback.bot.send_message(chat_id=callback.from_user.id, text="⚠️ Не найдено сообщение для диагностики.")
        except Exception:
            pass
        return

    await send_diagnostics(callback.message, callback.from_user.id, callback.bot)


@router.callback_query(F.data == CB_START)
async def menu_start(callback: CallbackQuery, state: FSMContext):
    await show_roles(callback, state)
