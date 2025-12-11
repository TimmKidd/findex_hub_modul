from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode

from findex_bot.states.vacancies import EmployerForm, SeekerForm, ModRejectionForm
from findex_bot.utils.vacancy_utils import get_ad_text
from findex_bot.utils.ui_utils import (
    moderation_keyboard,
    rejection_keyboard,
    send_ad_preview,
    send_preview,
)

router = Router()


# ------ ОТКЛОНЕНИЕ: переход от кнопки "Отклонить" к выбору причины ------

@router.callback_query(F.data.startswith("mod_reject"))
async def mod_reject_callback(callback: CallbackQuery, state: FSMContext):
    # импортируем ядро, чтобы не ловить циклические импорты
    from findex_bot import bot as core

    ad_id = callback.data.split(":")[1]
    ad_data = core.ADS_PENDING.get(ad_id)

    if not ad_data:
        await callback.answer("Объявление не найдено!", show_alert=True)
        return

    # если по объявлению уже было принято решение — не даём повторно тыкать
    if ad_id in core.PROCESSED_ADS:
        await callback.answer("Это объявление уже обработано ранее.", show_alert=True)
        return

    # убираем старую клавиатуру у сообщения с модерацией
    await callback.message.edit_reply_markup(reply_markup=None)

    media_id = ad_data.get("media_id")
    media_type = ad_data.get("media_type")
    base_text = get_ad_text(ad_data, include_author=True) + "\n\nВыберите причину отклонения:"

    if media_id and media_type == "photo":
        await callback.bot.send_photo(
            chat_id=core.config.moderation_chat_id,
            photo=media_id,
            caption=base_text,
            reply_markup=rejection_keyboard(ad_id),
        )
    elif media_id and media_type == "video":
        await callback.bot.send_video(
            chat_id=core.config.moderation_chat_id,
            video=media_id,
            caption=base_text,
            reply_markup=rejection_keyboard(ad_id),
        )
    else:
        await callback.bot.send_message(
            chat_id=core.config.moderation_chat_id,
            text=base_text,
            reply_markup=rejection_keyboard(ad_id),
        )

    await callback.answer()


# ------ ОБРАБОТКА ВЫБОРА ПРИЧИНЫ ОТКЛОНЕНИЯ ------

@router.callback_query(F.data.startswith("mod_reason"))
async def mod_reason_callback(callback: CallbackQuery, state: FSMContext):
    """
    Формат данных:
    mod_reason:<ad_id>:<reason_type>
    """
    from findex_bot import bot as core

    _, ad_id, reason_type = callback.data.split(":")

    # защита от повторных решений
    if ad_id in core.PROCESSED_ADS:
        await callback.answer("По этому объявлению решение уже принято ранее.", show_alert=True)
        return

    ad_data = core.ADS_PENDING.get(ad_id)
    if not ad_data:
        await callback.answer("Объявление не найдено!", show_alert=True)
        return

    author_id = ad_data.get("author_id")

    # --- Шаблонные причины из словаря REJECTION_REASON_TEXTS ---
    if reason_type in core.REJECTION_REASON_TEXTS:
        reason_text = core.REJECTION_REASON_TEXTS[reason_type]

        # кнопка пользователю — сразу к нужному полю на редактирование
        edit_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"Редактировать {reason_text.split()[0].lower()}",
                        callback_data=f"edit_after_reject:{ad_id}:{reason_type}",
                    )
                ]
            ]
        )

        if author_id:
            await callback.bot.send_message(
                chat_id=author_id,
                text=f"❌ Ваша заявка отклонена модератором.\nПричина: {reason_text}",
                reply_markup=edit_kb,
            )

        extra_text = f"✖ Отклонено: причина — {reason_text}"
        await send_ad_preview(
            core.config.moderation_chat_id,
            ad_data,
            callback.bot,
            extra_text=extra_text,
        )

        # помечаем объявление как окончательно обработанное
        core.PROCESSED_ADS.add(ad_id)

        await callback.answer("Отклонено — причина отправлена пользователю.", show_alert=True)

    # --- Кастомная причина: "Другая причина" ---
    elif reason_type == "custom":
        await state.set_state(ModRejectionForm.awaiting_reason)
        await state.update_data(ad_id=ad_id)

        await callback.message.answer(
            "Напишите вашу причину отклонения и отправьте её отдельным сообщением.",
            reply_markup=ReplyKeyboardRemove(),
        )
        await callback.answer()


# ------ КАСТОМНАЯ ПРИЧИНА ОТКЛОНЕНИЯ (текстом) ------

@router.message(ModRejectionForm.awaiting_reason)
async def mod_custom_reason(message: Message, state: FSMContext):
    from findex_bot import bot as core

    state_data = await state.get_data()
    ad_id = state_data.get("ad_id")

    if not ad_id:
        await message.answer("Ошибка: не найдено объявление для отклонения.")
        await state.clear()
        return

    # защита от повторного решения
    if ad_id in core.PROCESSED_ADS:
        await message.answer("По этому объявлению решение уже принято ранее.")
        await state.clear()
        return

    ad_data = core.ADS_PENDING.get(ad_id)
    author_id = ad_data.get("author_id") if ad_data else None

    custom_reason = (message.text or "").strip()
    if not ad_data or not custom_reason:
        await message.answer("Ошибка. Не найдено объявление или причина пуста.")
        await state.clear()
        return

    edit_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Редактировать объявление",
                    callback_data=f"edit_after_reject:{ad_id}:all",
                )
            ]
        ]
    )

    if author_id:
        await message.bot.send_message(
            chat_id=author_id,
            text=f"❌ Ваша заявка отклонена модератором.\nПричина: {custom_reason}",
            reply_markup=edit_kb,
        )

    extra_text = f"✖ Отклонено: причина — {custom_reason}"
    await send_ad_preview(
        core.config.moderation_chat_id,
        ad_data,
        message.bot,
        extra_text=extra_text,
    )

    core.PROCESSED_ADS.add(ad_id)

    await message.answer("Причина отклонения отправлена!", reply_markup=ReplyKeyboardRemove())
    await state.clear()


# ------ МГНОВЕННОЕ РЕДАКТИРОВАНИЕ ПОСЛЕ ОТКЛОНЕНИЯ ------

@router.callback_query(F.data.startswith("edit_after_reject"))
async def edit_after_reject(callback: CallbackQuery, state: FSMContext):
    from findex_bot import bot as core

    _, ad_id, reason_type = callback.data.split(":")
    ad_data = core.ADS_PENDING.get(ad_id)
    if not ad_data:
        await callback.answer("Объявление не найдено!", show_alert=True)
        return

    role = ad_data.get("role", "Работодатель")

    await state.clear()
    await state.update_data(**ad_data)

    # ---- СОИСКАТЕЛЬ ----
    if role == "Соискатель":
        if reason_type == "position":
            await state.update_data(is_inline_edit=True)
            await state.set_state(SeekerForm.position)
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text="Измени 👤 должность.\n<i>Пример: Бариста, Официант, Администратор</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove(),
            )
        elif reason_type == "schedule":
            await state.update_data(is_inline_edit=True)
            await state.set_state(SeekerForm.schedule)
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text="Измени 🕒 график.\n<i>Пример: 5/2, 2/2, Сменный, Гибкий, Удалёнка</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove(),
            )
        elif reason_type == "salary":
            await state.update_data(is_inline_edit=True)
            await state.set_state(SeekerForm.salary)
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text="Измени 💲 зарплату (ожидания).\n<i>Пример: от 80 000, 120 000, по договорённости</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove(),
            )
        elif reason_type == "location":
            await state.update_data(is_inline_edit=True)
            await state.set_state(SeekerForm.location)
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text="Измени 📍 локацию.\n<i>Пример: Москва, Санкт-Петербург, Дистанционно</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove(),
            )
        elif reason_type == "contacts":
            await state.update_data(is_inline_edit=True)
            await state.set_state(SeekerForm.contacts)
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text="Измени ☎️ контакты.\n<i>Пример: @username, email@example.com, +7 777 1234567</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove(),
            )
        elif reason_type == "description":
            await state.update_data(is_inline_edit=True)
            await state.set_state(SeekerForm.description)
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text="Измени 📝 блок «О себе» (до 2000 символов).\n<i>Опыт, навыки, что ищешь и т.д.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove(),
            )
        else:  # all / кастом
            await state.set_state(SeekerForm.preview)
            await send_preview(callback.from_user.id, state, callback.bot)

    # ---- РАБОТОДАТЕЛЬ ----
    else:
        if reason_type == "position":
            await state.update_data(is_inline_edit=True)
            await state.set_state(EmployerForm.position)
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text="Измени 👤 должность.\n<i>Пример: Бармен, Официант, Администратор</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove(),
            )
        elif reason_type == "salary":
            await state.update_data(is_inline_edit=True)
            await state.set_state(EmployerForm.salary)
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text="Измени 💲 зарплату.\n<i>Пример: 120000, до 200000, от 80k, по договорённости</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove(),
            )
        elif reason_type == "location":
            await state.update_data(is_inline_edit=True)
            await state.set_state(EmployerForm.location)
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text="Измени 📍 локацию.\n<i>Пример: Москва, Санкт-Петербург, Дистанционно</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove(),
            )
        elif reason_type == "contacts":
            await state.update_data(is_inline_edit=True)
            await state.set_state(EmployerForm.contacts)
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text="Измени ☎️ контакты.\n<i>Пример: @username, email@example.com, +7 777 1234567</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove(),
            )
        elif reason_type == "description":
            await state.update_data(is_inline_edit=True)
            await state.set_state(EmployerForm.description)
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text="Измени 📝 описание (до 2000 символов).\n<i>Требования, задачи, что предлагаем и т.д.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=ReplyKeyboardRemove(),
            )
        else:  # all / кастом
            await state.set_state(EmployerForm.preview)
            await send_preview(callback.from_user.id, state, callback.bot)

    await callback.answer()

# ------ УНИВЕРСАЛЬНАЯ ДОЗАПИСЬ ПОЛЕЙ ПОСЛЕ ОТКЛОНЕНИЯ (СОИСКАТЕЛЬ) ------

@router.message(SeekerForm.position)
@router.message(SeekerForm.schedule)
@router.message(SeekerForm.salary)
@router.message(SeekerForm.location)
@router.message(SeekerForm.contacts)
@router.message(SeekerForm.description)
async def edit_field_after_reject_seeker(message: Message, state: FSMContext):
    current_state = await state.get_state()
    field = None
    next_state = None

    if current_state == SeekerForm.position.state:
        field, next_state = "position", SeekerForm.preview
    elif current_state == SeekerForm.schedule.state:
        field, next_state = "schedule", SeekerForm.preview
    elif current_state == SeekerForm.salary.state:
        field, next_state = "salary", SeekerForm.preview
    elif current_state == SeekerForm.location.state:
        field, next_state = "location", SeekerForm.preview
    elif current_state == SeekerForm.contacts.state:
        field, next_state = "contacts", SeekerForm.preview
    elif current_state == SeekerForm.description.state:
        field, next_state = "description", SeekerForm.preview
    else:
        return

    await state.update_data(**{field: (message.text or "").strip()})
    data = await state.get_data()

    if data.get("is_inline_edit"):
        await state.update_data(is_inline_edit=False)
        await state.set_state(next_state)
        await send_preview(message, state, message.bot)


# ------ ОДОБРЕНИЕ (ПУБЛИКАЦИЯ) ОБЪЯВЛЕНИЯ ------

@router.callback_query(F.data.startswith("mod_approve"))
async def mod_approve_callback(callback: CallbackQuery):
    from findex_bot import bot as core

    ad_id = callback.data.split(":")[1]
    ad_data = core.ADS_PENDING.get(ad_id)
    if not ad_data:
        await callback.answer("Объявление не найдено!", show_alert=True)
        return

    # защита от повторного нажатия "Опубликовать"
    if ad_id in core.PROCESSED_ADS:
        await callback.answer("Это объявление уже обработано!", show_alert=True)
        return

    main_channel_id = core.config.main_channel_id
    channel_username = core.config.channel_username.lstrip("@")
    text_public = get_ad_text(ad_data, include_author=False)
    author_id = ad_data.get("author_id")
    moderator = callback.from_user.username
    moderator_text = f"@{moderator}" if moderator else f"id{callback.from_user.id}"

    # Публикация в основной канал
    if ad_data.get("media_type") == "photo":
        sent_msg = await callback.bot.send_photo(
            main_channel_id,
            photo=ad_data["media_id"],
            caption=text_public,
        )
    elif ad_data.get("media_type") == "video":
        sent_msg = await callback.bot.send_video(
            main_channel_id,
            video=ad_data["media_id"],
            caption=text_public,
        )
    else:
        sent_msg = await callback.bot.send_message(
            main_channel_id,
            text_public,
        )

    post_url = f"https://t.me/{channel_username}/{sent_msg.message_id}"

    # Запись в модераторский чат
    mod_text = f"✅ Опубликовано!\nМодератор: {moderator_text}\nСсылка: {post_url}"
    await send_ad_preview(
        core.config.moderation_chat_id,
        ad_data,
        callback.bot,
        extra_text=mod_text,
    )

    # помечаем объявление как окончательно обработанное
    core.PROCESSED_ADS.add(ad_id)

    # Уведомление автору + обновление счётчика бесплатных публикаций
    if author_id:
        core.increment_pub_counter(author_id)
        _, remaining = core.check_and_update_limit(author_id)

        await callback.bot.send_message(
            chat_id=author_id,
            text=(
                f"✅ Ваше объявление опубликовано!\n"
                f"Ссылка на объявление: {post_url}\n\n"
                f"Осталось бесплатных публикаций сегодня: {remaining}/3\n\n"
                f"Чтобы добавить следующее объявление — просто нажми /start"
            ),
        )

    # убираем кнопки "Одобрить / Отклонить" у модератора
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Объявление опубликовано!")

