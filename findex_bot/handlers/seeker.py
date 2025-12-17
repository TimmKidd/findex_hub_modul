from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext

from findex_bot.states.vacancies import SeekerForm
from findex_bot.utils.vacancy_utils import is_valid_city_input
from findex_bot.utils.ui_utils import send_preview, filter_field_mat

router = Router()

# ---------- СОИСКАТЕЛЬ ----------

@router.callback_query(F.data == "vac_seeker")
async def seeker_start(callback: CallbackQuery, state: FSMContext):
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
        force_preview=False,    # ✅ ключевой флаг
        on_moderation=False,    # ✅ защита от повторной отправки
    )

    await state.set_state(SeekerForm.position)
    await callback.message.answer(
        "Соискатель\n\nУкажи 👤 должность.\n<i>Пример: Бариста, Официант, Администратор</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


# ---------- EDIT (inline) ----------

@router.callback_query(F.data == "seek_edit_position")
async def seek_edit_position(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_inline_edit=True, force_preview=False)
    await state.set_state(SeekerForm.position)
    await callback.message.answer(
        "✏️ Редактирование: 👤 Должность\n<i>Пример: Бариста, Официант, Администратор</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.callback_query(F.data == "seek_edit_schedule")
async def seek_edit_schedule(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_inline_edit=True, force_preview=False)
    await state.set_state(SeekerForm.schedule)
    await callback.message.answer(
        "✏️ Редактирование: 🕒 График\n<i>Пример: 5/2, 2/2, Сменный, Гибкий, Удалёнка</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.callback_query(F.data == "seek_edit_salary")
async def seek_edit_salary(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_inline_edit=True, force_preview=False)
    await state.set_state(SeekerForm.salary)
    await callback.message.answer(
        "✏️ Редактирование: 💲 Зарплата\n<i>Пример: от 80 000, 120 000, по договорённости</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.callback_query(F.data == "seek_edit_location")
async def seek_edit_location(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_inline_edit=True, force_preview=False)
    await state.set_state(SeekerForm.location)
    await callback.message.answer(
        "✏️ Редактирование: 📍 Локация\n<i>Пример: Москва, ЦАО / СПБ, Приморский</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.callback_query(F.data == "seek_edit_contacts")
async def seek_edit_contacts(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_inline_edit=True, force_preview=False)
    await state.set_state(SeekerForm.contacts)
    await callback.message.answer(
        "✏️ Редактирование: ☎️ Контакты\n<i>Пример: @username / +7... / WhatsApp</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.callback_query(F.data == "seek_edit_description")
async def seek_edit_description(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_inline_edit=True, force_preview=False)
    await state.set_state(SeekerForm.description)
    await callback.message.answer(
        "✏️ Редактирование: 📝 Описание\n<i>Коротко: опыт, навыки, условия</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


# ---------- ПОЛЯ ----------

@router.message(SeekerForm.position)
async def seeker_position(message: Message, state: FSMContext):
    if not await filter_field_mat(message, "position"):
        return

    txt = (message.text or "").strip()
    await state.update_data(position=txt)

    data = await state.get_data()
    if data.get("is_inline_edit") or data.get("force_preview"):
        await state.update_data(is_inline_edit=False, force_preview=False, on_moderation=False)
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
    if not await filter_field_mat(message, "schedule"):
        return

    txt = (message.text or "").strip()
    await state.update_data(schedule=txt)

    data = await state.get_data()
    if data.get("is_inline_edit") or data.get("force_preview"):
        await state.update_data(is_inline_edit=False, force_preview=False, on_moderation=False)
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
    if not await filter_field_mat(message, "salary"):
        return

    txt = (message.text or "").strip()
    await state.update_data(salary=txt)

    data = await state.get_data()
    if data.get("is_inline_edit") or data.get("force_preview"):
        await state.update_data(is_inline_edit=False, force_preview=False, on_moderation=False)
        await state.set_state(SeekerForm.preview)
        await send_preview(message, state, message.bot)
        return

    await state.set_state(SeekerForm.location)
    await message.answer(
        "Укажи 📍 локацию.\n<i>Пример: Москва, ЦАО / СПБ, Приморский</i>",
        parse_mode=ParseMode.HTML,
    )


@router.message(SeekerForm.location)
async def seeker_location(message: Message, state: FSMContext):
    if not await filter_field_mat(message, "location"):
        return

    txt = (message.text or "").strip()
    if not is_valid_city_input(txt):
        await message.answer("Локация некорректная. Напиши город/район ещё раз.")
        return

    await state.update_data(location=txt)

    data = await state.get_data()
    if data.get("is_inline_edit") or data.get("force_preview"):
        await state.update_data(is_inline_edit=False, force_preview=False, on_moderation=False)
        await state.set_state(SeekerForm.preview)
        await send_preview(message, state, message.bot)
        return

    await state.set_state(SeekerForm.contacts)
    await message.answer(
        "Укажи ☎️ контакты.\n<i>Пример: @username / +7... / WhatsApp</i>",
        parse_mode=ParseMode.HTML,
    )


@router.message(SeekerForm.contacts)
async def seeker_contacts(message: Message, state: FSMContext):
    if not await filter_field_mat(message, "contacts"):
        return

    txt = (message.text or "").strip()
    await state.update_data(contacts=txt)

    data = await state.get_data()
    if data.get("is_inline_edit") or data.get("force_preview"):
        await state.update_data(is_inline_edit=False, force_preview=False, on_moderation=False)
        await state.set_state(SeekerForm.preview)
        await send_preview(message, state, message.bot)
        return

    await state.set_state(SeekerForm.description)
    await message.answer(
        "Укажи 📝 описание.\n<i>Коротко: опыт, навыки, условия</i>",
        parse_mode=ParseMode.HTML,
    )


@router.message(SeekerForm.description)
async def seeker_description(message: Message, state: FSMContext):
    if not await filter_field_mat(message, "description"):
        return

    txt = (message.text or "").strip()
    await state.update_data(description=txt)

    # ✅ В соискателе описание всегда завершает ввод → предпросмотр
    await state.update_data(is_inline_edit=False, force_preview=False, on_moderation=False)
    await state.set_state(SeekerForm.preview)
    await send_preview(message, state, message.bot)
