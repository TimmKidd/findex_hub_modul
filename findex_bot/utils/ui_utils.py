from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext

from findex_bot.utils.vacancy_utils import (
    contains_bad_words,
    is_valid_city_input,
    get_ad_text,
)


def get_full_edit_keyboard(role: str) -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура для предпросмотра объявления.
    Разные кнопки для Работодателя и Соискателя.
    """
    if role == "Соискатель":
        keyboard = [
            [
                InlineKeyboardButton(
                    text="👤 Должность",
                    callback_data="seek_edit_position",
                ),
                InlineKeyboardButton(
                    text="🕒 График",
                    callback_data="seek_edit_schedule",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💲 Зарплата",
                    callback_data="seek_edit_salary",
                ),
                InlineKeyboardButton(
                    text="📍 Локация",
                    callback_data="seek_edit_location",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="☎️ Контакты",
                    callback_data="seek_edit_contacts",
                ),
                InlineKeyboardButton(
                    text="📝 Описание",
                    callback_data="seek_edit_description",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✅ Отправить на модерацию",
                    callback_data="seek_send_mod",
                )
            ],
        ]
    else:  # Работодатель
        keyboard = [
            [
                InlineKeyboardButton(
                    text="👤 Должность",
                    callback_data="emp_edit_position",
                ),
                InlineKeyboardButton(
                    text="💲 Зарплата",
                    callback_data="emp_edit_salary",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📍 Локация",
                    callback_data="emp_edit_location",
                ),
                InlineKeyboardButton(
                    text="☎️ Контакты",
                    callback_data="emp_edit_contacts",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📝 Описание",
                    callback_data="emp_edit_description",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✅ Отправить на модерацию",
                    callback_data="emp_send_mod",
                )
            ],
        ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def moderation_keyboard(ad_id: str) -> InlineKeyboardMarkup:
    """
    Клавиатура под объявлением в модераторском чате:
    [Одобрить] [Отклонить]
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить",
                    callback_data=f"mod_approve:{ad_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"mod_reject:{ad_id}",
                ),
            ]
        ]
    )


def rejection_keyboard(ad_id: str) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора причины отклонения.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Должность некорректная",
                    callback_data=f"mod_reason:{ad_id}:position",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Зарплата некорректная",
                    callback_data=f"mod_reason:{ad_id}:salary",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Локация некорректная",
                    callback_data=f"mod_reason:{ad_id}:location",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Контакты некорректные",
                    callback_data=f"mod_reason:{ad_id}:contacts",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Описание некорректное",
                    callback_data=f"mod_reason:{ad_id}:description",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Другая причина",
                    callback_data=f"mod_reason:{ad_id}:custom",
                )
            ],
        ]
    )


async def send_ad_preview(
    chat_id: int,
    ad_data: dict,
    bot,
    extra_text: str | None = None,
):
    """
    Универсальная отправка объявления в мод-чат:
    - если есть фото/видео — отправляем медиа с caption
    - если медиа нет — обычный текст
    """
    text = get_ad_text(ad_data, include_author=True)
    if extra_text:
        text = f"{text}\n\n{extra_text}"

    media_id = ad_data.get("media_id")
    media_type = ad_data.get("media_type")

    if media_id and media_type == "photo":
        await bot.send_photo(
            chat_id=chat_id,
            photo=media_id,
            caption=text,
            parse_mode=ParseMode.HTML,
        )
    elif media_id and media_type == "video":
        await bot.send_video(
            chat_id=chat_id,
            video=media_id,
            caption=text,
            parse_mode=ParseMode.HTML,
        )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
        )


async def send_preview(
    message_or_chat: Message | int,
    state: FSMContext,
    bot,
):
    """
    Предпросмотр объявления пользователю (ОДНО сообщение):
    - если есть медиа — фото/видео + caption = текст объявления
    - если нет — просто текст + инлайн-клавиатура
    """
    data = await state.get_data()
    role = data.get("role", "Работодатель")

    text = get_ad_text(data, include_author=False)
    keyboard = get_full_edit_keyboard(role)

    # message_or_chat может быть Message или просто chat_id
    if isinstance(message_or_chat, Message):
        chat_id = message_or_chat.chat.id
    else:
        chat_id = int(message_or_chat)

    media_id = data.get("media_id")
    media_type = data.get("media_type")

    if media_id and media_type == "photo":
        await bot.send_photo(
            chat_id=chat_id,
            photo=media_id,
            caption=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
    elif media_id and media_type == "video":
        await bot.send_video(
            chat_id=chat_id,
            video=media_id,
            caption=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )


_FIELD_TITLES = {
    "position": "должность",
    "schedule": "график",
    "salary": "зарплату",
    "location": "локацию",
    "contacts": "контакты",
    "description": "описание",
}


async def filter_field_mat(message: Message, field: str) -> bool:
    """
    Асинхронный фильтр мата для полей вакансии/резюме.
    Если находит мат — шлёт предупреждение и возвращает False.
    """
    text = (message.text or "").lower()

    if contains_bad_words(text):
        field_title = _FIELD_TITLES.get(field, "это поле")
        await message.answer(
            f"Без мата, пожалуйста 🙂\n"
            f"Переформулируй {field_title} без нецензурной лексики."
        )
        return False

    return True

