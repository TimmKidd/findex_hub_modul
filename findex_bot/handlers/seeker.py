from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext

from findex_bot.states.vacancies import SeekerForm
from findex_bot.utils.vacancy_utils import contains_bad_words, is_valid_city_input
from findex_bot.utils.ui_utils import send_preview

router = Router()


# ---------- СОИСКАТЕЛЬ ----------

@router.callback_query(F.data == "vac_seeker")
async def seeker_start(callback: CallbackQuery, state: FSMContext):
    """
    Старт формы Соискателя после нажатия кнопки "Соискатель" в меню.
    """
    await state.clear()
    username = callback.from_user.username
    author = f"@{username}" if username else f"id{callback.from_user.id}"

    await state.update_data(
        position="",
        schedule="",
        salary="",
        location="",
        contacts="",
        description="",
        media_type=None,
        media_id=None,
        role="Соискатель",
        author_id=callback.from_user.id,
        author=author,
        is_inline_edit=False,
    )

    await state.set_state(SeekerForm.position)
    await callback.message.answer(
        "Соискатель\n\nУкажи 👤 должность.\n<i>Пример: Бариста, Официант, Администратор</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


# === ПОЛЯ ===

@router.message(SeekerForm.position)
async def seeker_position(message: Message, state: FSMContext):
    # просто сохраняем должность и идём дальше, без фильтров и проверок
    txt = (message.text or "").strip()
    await state.update_data(position=txt)

    data = await state.get_data()
    if data.get("is_inline_edit"):
        await state.update_data(is_inline_edit=False)
        await state.set_state(SeekerForm.preview)
        await send_preview(message, state, message.bot)
        return

    await state.set_state(SeekerForm.schedule)
    await message.answer(
        "Укажи 🕒 график.\n<i>Пример: 5/2, 2/2, Сменный, Гибкий, Удалёнка</i>",
        parse_mode=ParseMode.HTML,
    )


@router.message(SeekerForm.schedule)
async def seeker_schedule(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    await state.update_data(schedule=txt)

    data = await state.get_data()
    if data.get("is_inline_edit"):
        await state.update_data(is_inline_edit=False)
        await state.set_state(SeekerForm.preview)
        await send_preview(message, state, message.bot)
        return

    await state.set_state(SeekerForm.salary)
    await message.answer(
        "Укажи 💲 зарплатные ожидания.\n<i>Пример: от 80 000, 120 000, по договорённости</i>",
        parse_mode=ParseMode.HTML,
    )


@router.message(SeekerForm.salary)
async def seeker_salary(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    await state.update_data(salary=txt)

    data = await state.get_data()
    if data.get("is_inline_edit"):
        await state.update_data(is_inline_edit=False)
        await state.set_state(SeekerForm.preview)
        await send_preview(message, state, message.bot)
        return

    await state.set_state(SeekerForm.location)
    await message.answer(
        "Укажи 📍 локацию.\n<i>Пример: Москва, Санкт-Петербург, Дистанционно</i>",
        parse_mode=ParseMode.HTML,
    )


@router.message(SeekerForm.location)
async def seeker_location(message: Message, state: FSMContext):
    txt = (message.text or "").strip()

    if not is_valid_city_input(txt):
        await message.answer(
            "В названии города разрешены только буквы, пробелы и тире.",
        )
        return

    await state.update_data(location=txt)

    data = await state.get_data()
    if data.get("is_inline_edit"):
        await state.update_data(is_inline_edit=False)
        await state.set_state(SeekerForm.preview)
        await send_preview(message, state, message.bot)
        return

    await state.set_state(SeekerForm.contacts)
    await message.answer(
        "Укажи ☎️ контакты.\n<i>Пример: @username, email@example.com, +7 777 1234567</i>",
        parse_mode=ParseMode.HTML,
    )


@router.message(SeekerForm.contacts)
async def seeker_contacts(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    await state.update_data(contacts=txt)

    data = await state.get_data()
    if data.get("is_inline_edit"):
        await state.update_data(is_inline_edit=False)
        await state.set_state(SeekerForm.preview)
        await send_preview(message, state, message.bot)
        return

    await state.set_state(SeekerForm.description)
    await message.answer(
        "Опиши 📝 себя (до 2000 символов).\n<i>Опыт, навыки, что ищешь и т.д.</i>",
        parse_mode=ParseMode.HTML,
    )


@router.message(SeekerForm.description)
async def seeker_description(message: Message, state: FSMContext):
    description = (message.text or "").strip()

    if len(description) < 10:
        await message.answer("Описание слишком короткое! Напиши чуть подробнее.")
        return

    await state.update_data(description=description)
    data = await state.get_data()

    if data.get("is_inline_edit"):
        await state.update_data(is_inline_edit=False)
        await state.set_state(SeekerForm.preview)
        await send_preview(message, state, message.bot)
        return

    await state.set_state(SeekerForm.media_choice)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📎 Прикрепить фото/видео", callback_data="add_media_seeker"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⛔ Пропустить", callback_data="skip_media_seeker"
                )
            ],
        ]
    )
    await message.answer("Прикрепи фото/видео или пропусти", reply_markup=kb)


# === MEDIA ===

@router.callback_query(F.data == "add_media_seeker")
async def seeker_add_media(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SeekerForm.waiting_media)
    await callback.message.answer("Отправь фото или видео.")
    await callback.answer()


@router.callback_query(F.data == "skip_media_seeker")
async def seeker_skip_media(callback: CallbackQuery, state: FSMContext):
    await state.update_data(media_type=None, media_id=None)
    await state.set_state(SeekerForm.preview)
    await send_preview(callback.message, state, callback.bot)
    await callback.answer()


@router.message(SeekerForm.waiting_media, F.photo | F.video)
async def seeker_get_media(message: Message, state: FSMContext):
    if message.photo:
        await state.update_data(
            media_type="photo",
            media_id=message.photo[-1].file_id,
        )
    elif message.video:
        await state.update_data(
            media_type="video",
            media_id=message.video.file_id,
        )
    else:
        await message.answer("Пришли фото или видео.")
        return

    await state.set_state(SeekerForm.preview)
    await send_preview(message, state, message.bot)

