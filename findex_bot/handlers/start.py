# findex_bot/handlers/start.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

router = Router()

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
    await show_roles(message, state)


@router.callback_query(F.data == "vacancies_menu")
async def vacancies_menu(callback: CallbackQuery, state: FSMContext):
    await show_roles(callback, state)
