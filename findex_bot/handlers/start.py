from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode

router = Router()

@router.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Работодатель", callback_data="vac_employer")],
        [InlineKeyboardButton(text="Соискатель", callback_data="vac_seeker")]
    ])
    await message.answer(
        "👋 Добро пожаловать в FindexHub!\n\nВыберите роль:",
        reply_markup=kb
    )

@router.callback_query(F.data == "vacancies_menu")
async def vacancies_menu(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Работодатель", callback_data="vac_employer")],
        [InlineKeyboardButton(text="Соискатель", callback_data="vac_seeker")]
    ])
    await callback.message.edit_text("Кем ты являешься?", reply_markup=kb)
    await callback.answer()

