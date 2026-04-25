from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from findex_bot.states.vacancies import EmployerForm, SeekerForm
from findex_bot.utils.vacancy_utils import contains_bad_words, get_ad_text
from findex_bot.utils.ui_utils import (
    get_full_edit_keyboard,
    send_ad_preview,
    filter_field_mat,
)

router = Router()

# ============================
# СОИСКАТЕЛЬ
# ============================

@router.callback_query(F.data == "seek_edit_position")
async def seeker_edit_pos(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer("Введи новую должность:")
    await state.set_state(SeekerForm.position)
    await cb.answer()

@router.message(SeekerForm.position)
async def seeker_set_position(message: Message, state: FSMContext):
    if contains_bad_words(message.text):
        await message.answer("🚫 Некорректный текст")
        return
    await state.update_data(position=message.text.strip())
    data = await state.get_data()
    kb = get_full_edit_keyboard("Соискатель")
    text = get_ad_text(data)
    await message.answer(text, reply_markup=kb)
    await state.set_state(SeekerForm.preview)

# ============================
# ОТПРАВКА НА МОДЕРАЦИЮ
# ============================

@router.callback_query(F.data == "send_to_moderation")
async def send_to_moderation(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = get_ad_text(data, include_author=True)
    await send_ad_preview(cb.message, text)
    await cb.answer("Отправлено на модерацию!")

