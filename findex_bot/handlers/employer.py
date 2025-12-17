from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext

from findex_bot.states.vacancies import EmployerForm
from findex_bot.utils.vacancy_utils import is_valid_city_input
from findex_bot.utils.ui_utils import (
    send_preview,
    filter_field_mat,
)

router = Router()


# ---------- РАБОТОДАТЕЛЬ ----------

@router.callback_query(F.data == "vac_employer")
async def employer_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    username = callback.from_user.username
    author = f"@{username}" if username else f"id{callback.from_user.id}"

    await state.update_data(
        position="",
        salary="",
        location="",
        contacts="",
        description="",
        media_type=None,
        media_id=None,
        role="Работодатель",
        author_id=callback.from_user.id,
        author=author,
        is_inline_edit=False,
        force_preview=False,    # ✅ ключевой флаг для возврата в предпросмотр
        on_moderation=False,    # ✅ защита от повторной отправки
    )

    await state.set_state(EmployerForm.position)
    await callback.message.answer(
        "Работодатель\n\nУкажи 👤 должность.\n"
        "<i>Пример: Бармен, Официант, Администратор</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )
    await callback.answer()


# ---------- INLINE EDIT (Employer) ----------

@router.callback_query(F.data == "emp_edit_position")
async def emp_edit_position(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_inline_edit=True, force_preview=False)
    await state.set_state(EmployerForm.position)
    await callback.message.answer(
        "✏️ Редактирование: 👤 Должность\n<i>Пример: Бармен, Официант, Администратор</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.callback_query(F.data == "emp_edit_salary")
async def emp_edit_salary(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_inline_edit=True, force_preview=False)
    await state.set_state(EmployerForm.salary)
    await callback.message.answer(
        "✏️ Редактирование: 💲 Зарплата\n<i>Пример: 120000, до 200000, от 80k, по договорённости</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.callback_query(F.data == "emp_edit_location")
async def emp_edit_location(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_inline_edit=True, force_preview=False)
    await state.set_state(EmployerForm.location)
    await callback.message.answer(
        "✏️ Редактирование: 📍 Локация\n<i>Пример: Москва, Санкт-Петербург, Дистанционно</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.callback_query(F.data == "emp_edit_contacts")
async def emp_edit_contacts(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_inline_edit=True, force_preview=False)
    await state.set_state(EmployerForm.contacts)
    await callback.message.answer(
        "✏️ Редактирование: ☎️ Контакты\n<i>Пример: @username, email@example.com, +7 777 1234567</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.callback_query(F.data == "emp_edit_description")
async def emp_edit_description(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_inline_edit=True, force_preview=False)
    await state.set_state(EmployerForm.description)
    await callback.message.answer(
        "✏️ Редактирование: 📝 Описание\n<i>Опиши вакансию (до 2000 символов)</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


# ---------- ПОЛЯ ----------

@router.message(EmployerForm.position)
async def employer_position(message: Message, state: FSMContext):
    if not await filter_field_mat(message, "position"):
        return

    txt = (message.text or "").strip()
    await state.update_data(position=txt)

    data = await state.get_data()
    if data.get("is_inline_edit") or data.get("force_preview"):
        # ✅ после исправления/редактирования — сразу предпросмотр
        await state.update_data(is_inline_edit=False, force_preview=False, on_moderation=False)
        await state.set_state(EmployerForm.preview)
        await send_preview(message, state, message.bot)
        return

    await state.set_state(EmployerForm.salary)
    await message.answer(
        "Укажи 💲 зарплату.\n"
        "<i>Пример: 120000, до 200000, от 80k, по договорённости</i>",
        parse_mode=ParseMode.HTML,
    )


@router.message(EmployerForm.salary)
async def employer_salary(message: Message, state: FSMContext):
    if not await filter_field_mat(message, "salary"):
        return

    txt = (message.text or "").strip()
    await state.update_data(salary=txt)

    data = await state.get_data()
    if data.get("is_inline_edit") or data.get("force_preview"):
        await state.update_data(is_inline_edit=False, force_preview=False, on_moderation=False)
        await state.set_state(EmployerForm.preview)
        await send_preview(message, state, message.bot)
        return

    await state.set_state(EmployerForm.location)
    await message.answer(
        "Укажи 📍 локацию.\n"
        "<i>Пример: Москва, Санкт-Петербург, Дистанционно</i>",
        parse_mode=ParseMode.HTML,
    )


@router.message(EmployerForm.location)
async def employer_location(message: Message, state: FSMContext):
    if not await filter_field_mat(message, "location"):
        return

    txt = (message.text or "").strip()

    if not is_valid_city_input(txt):
        await message.answer("В названии города разрешены только буквы, пробелы и тире.")
        return

    await state.update_data(location=txt)

    data = await state.get_data()
    if data.get("is_inline_edit") or data.get("force_preview"):
        await state.update_data(is_inline_edit=False, force_preview=False, on_moderation=False)
        await state.set_state(EmployerForm.preview)
        await send_preview(message, state, message.bot)
        return

    await state.set_state(EmployerForm.contacts)
    await message.answer(
        "Укажи ☎️ контакты.\n"
        "<i>Пример: @username, email@example.com, +7 777 1234567</i>",
        parse_mode=ParseMode.HTML,
    )


@router.message(EmployerForm.contacts)
async def employer_contacts(message: Message, state: FSMContext):
    if not await filter_field_mat(message, "contacts"):
        return

    txt = (message.text or "").strip()
    await state.update_data(contacts=txt)

    data = await state.get_data()
    if data.get("is_inline_edit") or data.get("force_preview"):
        await state.update_data(is_inline_edit=False, force_preview=False, on_moderation=False)
        await state.set_state(EmployerForm.preview)
        await send_preview(message, state, message.bot)
        return

    await state.set_state(EmployerForm.description)
    await message.answer(
        "Опиши 📝 вакансию (до 2000 символов).",
        parse_mode=ParseMode.HTML,
    )


@router.message(EmployerForm.description)
async def employer_description(message: Message, state: FSMContext):
    if not await filter_field_mat(message, "description"):
        return

    description = (message.text or "").strip()

    if len(description) < 10:
        await message.answer("Описание слишком короткое!")
        return

    await state.update_data(description=description)

    data = await state.get_data()
    if data.get("is_inline_edit") or data.get("force_preview"):
        await state.update_data(is_inline_edit=False, force_preview=False, on_moderation=False)
        await state.set_state(EmployerForm.preview)
        await send_preview(message, state, message.bot)
        return

    await state.set_state(EmployerForm.media_choice)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📎 Прикрепить фото/видео", callback_data="add_media")],
            [InlineKeyboardButton(text="⛔ Пропустить", callback_data="skip_media")],
        ]
    )
    await message.answer("Прикрепи фото/видео или пропусти.", reply_markup=kb)


# ---------- MEDIA ----------

@router.callback_query(F.data == "add_media")
async def employer_add_media(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EmployerForm.waiting_media)
    await callback.message.answer("Отправь фото или видео.")
    await callback.answer()


@router.callback_query(F.data == "skip_media")
async def employer_skip_media(callback: CallbackQuery, state: FSMContext):
    await state.update_data(media_type=None, media_id=None)
    await state.set_state(EmployerForm.preview)
    await send_preview(callback.message, state, callback.bot)
    await callback.answer()


@router.message(EmployerForm.waiting_media, F.photo | F.video)
async def employer_get_media(message: Message, state: FSMContext):
    if message.photo:
        await state.update_data(media_type="photo", media_id=message.photo[-1].file_id)
    elif message.video:
        await state.update_data(media_type="video", media_id=message.video.file_id)
    else:
        await message.answer("Пришли фото или видео.")
        return

    await state.set_state(EmployerForm.preview)
    await send_preview(message, state, message.bot)
