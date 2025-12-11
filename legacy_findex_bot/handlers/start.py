from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardMarkup, InlineKeyboardButton

from findex_bot.handlers.moderation import send_to_moderation
from findex_bot.handlers.common import (
    FIELDS,
    build_post,
    generate_tags,
    parse_field_from_reason,
    user_profile_link,
)
from findex_bot.config import MODERATION_CHAT_ID

import logging

logger = logging.getLogger(__name__)

router = Router()

main_menu = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="✏️ Создать объявление")],
        [types.KeyboardButton(text="📁 Мои объявления (soon)")],
        [types.KeyboardButton(text="🔍 Поиск объявлений (soon)")],
        [types.KeyboardButton(text="❓ Помощь")],
    ],
    resize_keyboard=True
)

CATEGORIES = [
    "Аренда",
    "Вакансия",
    "Услуги",
    "Купля / Продажа"
]

DESCRIPTION_MAX_LENGTH = 3000

FIELDS = {
    "Аренда": [
        ("object", "🏢 Объект"),
        ("price", "💲 Цена"),
        ("location", "📍 Локация"),
        ("area", "🏠 Площадь"),
        ("contacts", "📞 Контакты"),
        ("description", "📝 Описание"),
    ],
    "Вакансия": [
        ("position", "👤 Должность"),
        ("salary", "💰 Зарплата"),
        ("location", "📍 Локация"),
        ("contacts", "📞 Контакты"),
        ("description", "📝 Описание"),
    ],
    "Услуги": [
        ("service", "🔧 Услуга"),
        ("price", "💲 Цена/Условия"),
        ("location", "📍 Локация"),
        ("contacts", "📞 Контакты"),
        ("description", "📝 Описание"),
    ],
    "Купля / Продажа": [
        ("item", "📦 Товар / Объект"),
        ("price", "💲 Цена"),
        ("location", "📍 Локация"),
        ("state", "📃 Состояние"),
        ("contacts", "📞 Контакты"),
        ("description", "📝 Описание"),
    ]
}

def build_preview(category: str, data: dict, user: types.User) -> str:
    post = build_post(category, data)
    tags = generate_tags(category, data)
    return f"{post}\n\nОт: {user_profile_link(user)}\n\n{tags}"

def cancel_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="❌ Отмена")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

def edit_description_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="✏️ Редактировать описание")
    builder.button(text="❌ Отмена")
    builder.adjust(1, 1)
    return builder.as_markup(resize_keyboard=True)

class UniversalCreateAdFSM(StatesGroup):
    waiting_for_category = State()
    waiting_for_next_field = State()
    waiting_for_photo = State()
    waiting_for_confirm = State()
    waiting_after_field_edit = State()
    edit_description_only = State()

@router.message(Command(commands=["start", "menu"]))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Добро пожаловать в FindexHub!\n\n"
        "Первый сервис для размещения бесплатных объявлений!\n\n"
        "Выберите действие из меню ниже ⬇️",
        reply_markup=main_menu
    )

@router.message(F.text == "❓ Помощь")
@router.message(F.text.casefold() == "помощь")
async def cmd_help(message: types.Message, state: FSMContext):
    await message.answer(
        "Добро пожаловать в FindexHub!\n\n"
        "✏️ <b>Создать объявление</b> — публикуйте бесплатные объявления раз в день, чтобы их увидела релевантная аудитория.\n"
        "📁 <b>Мои объявления</b> — смотрите свои публикации, обновляйте и отслеживайте их статус.\n"
        "🔍 <b>Поиск объявлений</b> — находите интересующие вас предложения других пользователей и фильтруйте по категориям.\n"
        "❓ <b>Помощь</b> — узнавайте о возможностях сервиса и получайте поддержку.\n\n"
        "Всё просто: выберите нужный пункт в меню, следуйте подсказкам.\n\n"
        "Если возникли вопросы или нужна поддержка — напишите нам в бот поддержки: @FindexHub_support_bot",
        parse_mode="HTML"
    )

@router.message(F.text == "✏️ Создать объявление")
async def start_create_ad(message: types.Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardBuilder()
    for cat in CATEGORIES:
        kb.button(text=cat)
    kb.button(text="❌ Отмена")
    kb.adjust(2)
    await message.answer(
        "Выберите <b>категорию</b> для вашего объявления:",
        reply_markup=kb.as_markup(resize_keyboard=True),
        parse_mode="HTML"
    )
    await state.set_state(UniversalCreateAdFSM.waiting_for_category)

@router.message(UniversalCreateAdFSM.waiting_for_category, F.text.in_(CATEGORIES))
async def set_category(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text, form={}, step=0, photo=None)
    await ask_next_field(message, state)

@router.message(UniversalCreateAdFSM.waiting_for_category, F.text.casefold() == "❌ отмена")
@router.message(UniversalCreateAdFSM.waiting_for_photo, F.text.casefold() == "❌ отмена")
@router.message(UniversalCreateAdFSM.waiting_for_next_field, F.text.casefold() == "❌ отмена")
@router.message(UniversalCreateAdFSM.waiting_for_confirm, F.text.casefold() == "❌ отмена")
@router.message(UniversalCreateAdFSM.waiting_after_field_edit, F.text.casefold() == "❌ отмена")
@router.message(UniversalCreateAdFSM.edit_description_only, F.text.casefold() == "❌ отмена")
async def universal_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Создание объявления отменено.", reply_markup=main_menu)

async def ask_next_field(message, state):
    data = await state.get_data()
    category = data["category"]
    step = data.get("step", 0)
    fields = FIELDS[category]
    if step < len(fields):
        _, label = fields[step]
        await message.answer(
            f"Введите\n<b>{label}</b>:",
            reply_markup=cancel_kb(),
            parse_mode="HTML"
        )
        await state.update_data(step=step)
        await state.set_state(UniversalCreateAdFSM.waiting_for_next_field)
    else:
        builder = ReplyKeyboardBuilder()
        builder.button(text="Пропустить")
        builder.button(text="❌ Отмена")
        builder.adjust(2)
        await message.answer(
            "Хотите добавить фотографию к объявлению?\n"
            "Пришлите фото или нажмите \"Пропустить\".",
            reply_markup=builder.as_markup(resize_keyboard=True)
        )
        await state.set_state(UniversalCreateAdFSM.waiting_for_photo)

@router.message(UniversalCreateAdFSM.waiting_for_next_field)
async def fill_field(message: types.Message, state: FSMContext):
    data = await state.get_data()
    category = data["category"]
    step = data["step"]
    form = data.get("form") or {}
    fields = FIELDS[category]
    if step < len(fields):
        key, _ = fields[step]
        if key == "description":
            if not message.text:
                await message.answer("Пожалуйста, введите текстовое значение для этого поля.")
                return
            if len(message.text) > DESCRIPTION_MAX_LENGTH:
                await message.answer(
                    f"Описание слишком длинное! Максимум — {DESCRIPTION_MAX_LENGTH} символов.\n"
                    f"Сейчас: {len(message.text)} символов.\nПожалуйста, сократите описание и попробуйте снова.",
                    reply_markup=edit_description_kb()
                )
                await state.set_state(UniversalCreateAdFSM.edit_description_only)
                return
        form[key] = message.text
        await state.update_data(form=form, step=step + 1)
        edit_mode = data.get("edit_mode", False)
        if edit_mode:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Редактировать объявление целиком", callback_data="edit_all_fields")],
                [InlineKeyboardButton(text="✅ Отправить на модерацию", callback_data="submit_for_moderation")]
            ])
            await message.answer(
                "Вы можете отправить объявление сразу на модерацию или пересмотреть все поля перед публикацией.",
                reply_markup=kb
            )
            await state.set_state(UniversalCreateAdFSM.waiting_after_field_edit)
        else:
            await ask_next_field(message, state)
    else:
        await ask_next_field(message, state)

@router.message(UniversalCreateAdFSM.edit_description_only, F.text == "✏️ Редактировать описание")
async def edit_description_only_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    category = data["category"]
    step = 0
    for idx, (key, _) in enumerate(FIELDS[category]):
        if key == "description":
            step = idx
            break
    await state.update_data(step=step)
    await message.answer("Введите новое описание (до 3000 символов):", reply_markup=cancel_kb())
    await state.set_state(UniversalCreateAdFSM.waiting_for_next_field)

@router.message(UniversalCreateAdFSM.edit_description_only)
async def edit_description_fallback(message: types.Message, state: FSMContext):
    await fill_field(message, state)

@router.message(UniversalCreateAdFSM.waiting_for_photo, F.photo)
async def get_photo(message: types.Message, state: FSMContext):
    largest = message.photo[-1]
    file_id = largest.file_id
    await state.update_data(photo=file_id)
    await finish_and_show_preview(message, state)

@router.message(UniversalCreateAdFSM.waiting_for_photo, F.text.casefold() == "пропустить")
async def skip_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo=None)
    await finish_and_show_preview(message, state)

async def finish_and_show_preview(message: types.Message, state: FSMContext):
    data = await state.get_data()
    category = data["category"]
    form = data["form"]
    preview_text = build_post(category, form)
    preview_with_tags = f"{preview_text}\n\nОт: {user_profile_link(message.from_user)}\n\n{generate_tags(category, form)}"
    builder = ReplyKeyboardBuilder()
    builder.button(text="✅ Отправить на модерацию")
    builder.button(text="❌ Отмена")
    builder.adjust(2)
    photo = data.get("photo")
    if photo:
        await message.answer_photo(
            photo,
            caption=preview_with_tags,
            parse_mode="HTML",
            reply_markup=builder.as_markup(resize_keyboard=True)
        )
    else:
        await message.answer(
            preview_with_tags,
            parse_mode="HTML",
            reply_markup=builder.as_markup(resize_keyboard=True)
        )
    await state.set_state(UniversalCreateAdFSM.waiting_for_confirm)

@router.message(UniversalCreateAdFSM.waiting_for_confirm, F.text == "✅ Отправить на модерацию")
async def send_to_moderation_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    category = data["category"]
    form = data["form"]
    photo = data.get("photo")
    post_preview = build_post(category, form)
    post_for_moderation = f"{post_preview}\n\nОт: {user_profile_link(message.from_user)}\n\n{generate_tags(category, form)}"
    await send_to_moderation(
        message.bot,
        post_for_moderation,
        message.from_user,
        message.from_user.id,
        photo=photo,
        category=category,
        form=form
    )
    await message.answer(
        "✅ Ваше объявление отправлено на модерацию! "
        "Вы получите отдельное уведомление о публикации или отклонении.",
        reply_markup=main_menu
    )
    await state.clear()

@router.callback_query(F.data == "edit_all_fields")
async def edit_all_fields_handler(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(edit_mode=False, step=0, photo=None)
    await call.message.answer("Редактируйте поля по очереди ниже ⬇️", reply_markup=types.ReplyKeyboardRemove())
    await ask_next_field(call.message, state)

@router.callback_query(F.data == "submit_for_moderation")
async def submit_for_moderation_handler(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category = data["category"]
    form = data["form"]
    photo = data.get("photo")
    post_preview = build_post(category, form)
    post_for_moderation = f"{post_preview}\n\nОт: {user_profile_link(call.from_user)}\n\n{generate_tags(category, form)}"
    await send_to_moderation(
        call.bot,
        post_for_moderation,
        call.from_user,
        call.from_user.id,
        photo=photo,
        category=category,
        form=form
    )
    await call.message.answer(
        "✅ Ваше объявление отправлено на модерацию!\nВы получите отдельное уведомление о публикации или отклонении.",
        reply_markup=main_menu,
        parse_mode="HTML"
    )
    await state.clear()

async def start_field_edit_mode(message, state, step_value):
    await state.update_data(edit_mode=True, step=step_value)
    await ask_next_field(message, state)