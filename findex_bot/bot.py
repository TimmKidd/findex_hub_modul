import os
import asyncio
import logging
import re
import datetime
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

from findex_bot.utils.vacancy_utils import (
    contains_bad_words,
    is_valid_city_input,
    get_ad_text,
)
from findex_bot.utils.ui_utils import (
    get_full_edit_keyboard,
    moderation_keyboard,
    rejection_keyboard,
    send_ad_preview,
    send_preview,
    filter_field_mat,
)
from findex_bot.states.vacancies import EmployerForm as ExtEmployerForm, SeekerForm as ExtSeekerForm
from findex_bot.handlers.start import router as start_router
from findex_bot.handlers.forms import router as forms_router
from findex_bot.handlers.employer import router as employer_router
from findex_bot.handlers.seeker import router as seeker_router

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.client.default import DefaultBotProperties


@dataclass
class Config:
    bot_token: str
    moderation_chat_id: int
    main_channel_id: int
    thread_vacancies: int
    channel_username: str


def load_config() -> Config:
    base_dir = Path(__file__).resolve().parent
    env_path = base_dir / ".env"

    if env_path.is_file():
        load_dotenv(env_path)
    else:
        load_dotenv()

    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN не задан в .env")

    return Config(
        bot_token=bot_token,
        moderation_chat_id=int(os.getenv("MODERATION_CHAT_ID", "0")),
        main_channel_id=int(os.getenv("MAIN_CHANNEL_ID", "0")),
        thread_vacancies=int(os.getenv("THREAD_VACANCIES", "0")),
        channel_username=os.getenv("CHANNEL_USERNAME", ""),
    )


config = load_config()
logging.basicConfig(level=logging.INFO)
router = Router()


# Локальные стейты (оставляем для совместимости с существующей логикой)

class EmployerForm(StatesGroup):
    position = State()
    salary = State()
    location = State()
    contacts = State()
    description = State()
    media_choice = State()
    waiting_media = State()
    preview = State()


class SeekerForm(StatesGroup):
    position = State()
    schedule = State()
    salary = State()
    location = State()
    contacts = State()
    description = State()  # "О себе"
    media_choice = State()
    waiting_media = State()
    preview = State()


class ModRejectionForm(StatesGroup):
    awaiting_reason = State()


ADS_PENDING: dict[str, dict] = {}

# Набор объявлений, которые уже получили финальное решение модерации
PROCESSED_ADS: set[str] = set()

# ---- Счётчик бесплатных публикаций по пользователям ----
# {user_id: {"date": "YYYY-MM-DD", "count": int}}
USER_PUB_COUNTER: dict[int, dict[str, int]] = {}

# ---- Пользователи с безлимитом (модераторы) ----
UNLIMITED_USERS: set[int] = {
    80675147,
    7107629211,
}

# Старое имя, если где-то ещё используется
MODERATORS = UNLIMITED_USERS


def check_and_update_limit(user_id: int):
    """
    Проверяет дневной лимит публикаций И СРАЗУ ЖЕ увеличивает счётчик,
    если публикация разрешена.

    Возвращает (can_post: bool, remaining: int | str):

    - can_post: можно ли сейчас отправить объявление
    - remaining: сколько БУДЕТ оставаться после этой отправки
      (или "∞" для безлимитных пользователей).
    """

    # 🔓 Безлимитные пользователи (модераторы)
    if user_id in UNLIMITED_USERS:
        return True, "∞"

    today = datetime.date.today().isoformat()
    data = USER_PUB_COUNTER.get(user_id)

    # если ещё ничего не было или день сменился — начинаем с нуля
    if not data or data.get("date") != today:
        USER_PUB_COUNTER[user_id] = {"date": today, "count": 0}
        data = USER_PUB_COUNTER[user_id]

    count = data["count"]

    # если уже 3/3 — дальше нельзя
    if count >= 3:
        return False, 0

    # разрешаем публикацию и сразу увеличиваем счётчик
    data["count"] = count + 1
    remaining = 3 - data["count"]  # сколько осталось после этой отправки

    return True, remaining


def increment_pub_counter(user_id: int):
    """
    Увеличивает счётчик публикаций пользователя на 1 за текущий день.
    Для безлимитных пользователей (модераторов) — счётчик не трогаем.
    """

    if user_id in UNLIMITED_USERS:
        return

    today = datetime.date.today().isoformat()
    data = USER_PUB_COUNTER.get(user_id)

    if not data or data.get("date") != today:
        USER_PUB_COUNTER[user_id] = {"date": today, "count": 0}
        data = USER_PUB_COUNTER[user_id]

    USER_PUB_COUNTER[user_id]["count"] = data["count"] + 1


def make_hashtag(text: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "", text or "")
    return f"#{cleaned}" if cleaned else ""


def is_valid_city_input(city: str) -> bool:
    if not city:
        return False
    city = city.strip()
    return bool(re.fullmatch(r"[A-Za-zА-Яа-яЁё\s\-]+", city))


def get_ad_text(data, include_author: bool = False) -> str:
    role = data.get("role", "Работодатель")
    position = data.get("position", "")
    location = data.get("location", "")
    salary = data.get("salary", "")
    contacts = data.get("contacts", "")
    description = data.get("description", "")
    schedule = data.get("schedule", "")

    tags = f"#FindexHub {make_hashtag(position)} {make_hashtag(location)}"

    if role == "Соискатель":
        text = (
            f"{role}\n\n"
            f"👤 Должность: {position}\n"
            f"🕒 График: {schedule}\n"
            f"💲 Зарплата: {salary}\n"
            f"📍 Локация: {location}\n"
            f"☎️ Контакты: {contacts}\n"
            f"📝 О себе:\n{description}\n\n"
            f"{tags}"
        )
    else:
        text = (
            f"{role}\n\n"
            f"👤 Должность: {position}\n"
            f"💲 Зарплата: {salary}\n"
            f"📍 Локация: {location}\n"
            f"☎️ Контакты: {contacts}\n"
            f"📝 Описание:\n{description}\n\n"
            f"{tags}"
        )

    if include_author and data.get("author"):
        text += f"\n\nАвтор: {data.get('author')}"
    return text


@router.callback_query(F.data == "vacancies_menu")
async def vacancies_menu(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Работодатель", callback_data="vac_employer")],
            [InlineKeyboardButton(text="Соискатель", callback_data="vac_seeker")],
        ]
    )
    await callback.message.edit_text("Кем ты являешься?", reply_markup=kb)
    await callback.answer()


# ---------- РАБОТОДАТЕЛЬ ----------

# ------ ОТПРАВКА НА МОДЕРАЦИЮ (Работодатель) ------


@router.callback_query(F.data == "emp_send_mod")
async def employer_send_mod(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id

    # --- проверка лимита перед отправкой на модерацию ---
    can_post, remaining = check_and_update_limit(user_id)
    if not can_post:
        await callback.message.answer(
            "❌ Лимит бесплатных публикаций на сегодня исчерпан.\n"
            "Доступно: 0/3\n\n"
            "Новые объявления можно будет отправить завтра."
        )
        await callback.answer()
        return

    mod_chat_id = config.moderation_chat_id
    text_moderation = get_ad_text(data, include_author=True)
    media_id = data.get("media_id")
    media_type = data.get("media_type")
    ad_id = f"{user_id}_{int(datetime.datetime.utcnow().timestamp())}"
    ad_data = data.copy()
    ad_data["ad_id"] = ad_id
    ADS_PENDING[ad_id] = ad_data

    try:
        if media_id and media_type == "photo":
            await callback.bot.send_photo(
                chat_id=mod_chat_id,
                photo=media_id,
                caption=text_moderation,
                reply_markup=moderation_keyboard(ad_id),
            )
        elif media_id and media_type == "video":
            await callback.bot.send_video(
                chat_id=mod_chat_id,
                video=media_id,
                caption=text_moderation,
                reply_markup=moderation_keyboard(ad_id),
            )
        else:
            await callback.bot.send_message(
                chat_id=mod_chat_id,
                text=text_moderation,
                reply_markup=moderation_keyboard(ad_id),
            )
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка при отправке на модерацию: {e}")
        return

    await callback.message.answer("✅ Ваше объявление отправлено на модерацию!")


# ------ ОТПРАВКА НА МОДЕРАЦИЮ (Соискатель) ------


@router.callback_query(F.data == "seek_send_mod")
async def seeker_send_mod(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id

    can_post, remaining = check_and_update_limit(user_id)
    if not can_post:
        await callback.message.answer(
            "❌ Лимит бесплатных публикаций на сегодня исчерпан.\n"
            "Доступно: 0/3\n\n"
            "Новые объявления можно будет отправить завтра."
        )
        await callback.answer()
        return

    mod_chat_id = config.moderation_chat_id
    text_moderation = get_ad_text(data, include_author=True)
    media_id = data.get("media_id")
    media_type = data.get("media_type")
    ad_id = f"{user_id}_{int(datetime.datetime.utcnow().timestamp())}"
    ad_data = data.copy()
    ad_data["ad_id"] = ad_id
    ADS_PENDING[ad_id] = ad_data

    try:
        if media_id and media_type == "photo":
            await callback.bot.send_photo(
                chat_id=mod_chat_id,
                photo=media_id,
                caption=text_moderation,
                reply_markup=moderation_keyboard(ad_id),
            )
        else:
            await callback.bot.send_message(
                chat_id=mod_chat_id,
                text=text_moderation,
                reply_markup=moderation_keyboard(ad_id),
            )
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка при отправке на модерацию: {e}")
        return

    await callback.message.answer("✅ Твоё резюме отправлено на модерацию!")


# ---- Шаблонные причины отклонения ----

REJECTION_REASON_TEXTS = {
    "position": "Должность некорректная",
    "salary": "Зарплата некорректная",
    "location": "Локация некорректная",
    "contacts": "Контакты некорректные",
    "description": "Описание некорректное",
}


# ------ МОДЕРАЦИЯ: ШАГ 1. Нажали «Отклонить» ------


@router.callback_query(F.data.startswith("mod_reject"))
async def mod_reject_callback(callback: CallbackQuery, state: FSMContext):
    """
    Модератор нажал кнопку «Отклонить» под объявлением в мод-канале.
    Показываем новое сообщение с выбором причины отклонения.
    """
    try:
        _, ad_id = callback.data.split(":", 1)
    except ValueError:
        await callback.answer("Некорректные данные кнопки.", show_alert=True)
        return

    ad_data = ADS_PENDING.get(ad_id)
    if not ad_data:
        await callback.answer("Объявление не найдено.", show_alert=True)
        return

    # Удаляем старую клаву «Одобрить / Отклонить»
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    media_id = ad_data.get("media_id")
    media_type = ad_data.get("media_type")

    base_text = get_ad_text(ad_data, include_author=True) + "\n\nВыберите причину отклонения:"
    kb = rejection_keyboard(ad_id)

    bot = callback.bot
    chat_id = config.moderation_chat_id

    # Показываем то же объявление с новой клавой причин
    if media_id and media_type == "photo":
        await bot.send_photo(
            chat_id=chat_id,
            photo=media_id,
            caption=base_text,
            reply_markup=kb,
        )
    elif media_id and media_type == "video":
        await bot.send_video(
            chat_id=chat_id,
            video=media_id,
            caption=base_text,
            reply_markup=kb,
        )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=base_text,
            reply_markup=kb,
        )

    await callback.answer("Выбери причину отклонения.")


# ------ МОДЕРАЦИЯ: ШАГ 2. Модератор выбрал причину ------


@router.callback_query(F.data.startswith("mod_reason"))
async def mod_reason_callback(callback: CallbackQuery, state: FSMContext):
    """
    Модератор выбрал одну из причин:
    - шаблонная (position/salary/location/contacts/description)
    - custom (своя причина)
    """
    try:
        _, ad_id, reason_type = callback.data.split(":")
    except ValueError:
        await callback.answer("Некорректные данные кнопки.", show_alert=True)
        return

    ad_data = ADS_PENDING.get(ad_id)
    if not ad_data:
        await callback.answer("Объявление не найдено.", show_alert=True)
        return

    # Анти-дубль: если объявление уже окончательно обработано — не даём второй раз
    if ad_id in PROCESSED_ADS and reason_type != "custom":
        await callback.answer("Это объявление уже обработано.", show_alert=True)
        return

    author_id = ad_data.get("author_id")

    # --- Шаблонная причина ---
    if reason_type in REJECTION_REASON_TEXTS:
        reason_text = REJECTION_REASON_TEXTS[reason_type]

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

        # Сообщение пользователю
        if author_id:
            await callback.bot.send_message(
                chat_id=author_id,
                text=f"❌ Ваше объявление отклонено модератором.\nПричина: {reason_text}",
                reply_markup=edit_kb,
            )

        extra_text = f"✖ Отклонено: причина — {reason_text}"
        await send_ad_preview(
            config.moderation_chat_id,
            ad_data,
            callback.bot,
            extra_text=extra_text,
        )

        PROCESSED_ADS.add(ad_id)
        await callback.answer("Отклонено, причина отправлена пользователю.", show_alert=True)
        return

    # --- Своя причина (custom) ---
    if reason_type == "custom":
        await state.set_state(ModRejectionForm.awaiting_reason)
        await state.update_data(ad_id=ad_id)
        await callback.message.answer(
            "Напиши свою причину отклонения и отправь одним сообщением.",
            reply_markup=ReplyKeyboardRemove(),
        )
        await callback.answer()
        return

    await callback.answer("Неизвестный тип причины.", show_alert=True)


# ------ МОДЕРАЦИЯ: ШАГ 3. Пользователь жмёт «Редактировать …» после отказа ------


@router.callback_query(F.data.startswith("edit_after_reject"))
async def edit_after_reject(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь нажал кнопку «Редактировать …» из лички после отклонения.
    Открываем нужный State в зависимости от роли и поля.
    """
    try:
        _, ad_id, reason_type = callback.data.split(":")
    except ValueError:
        await callback.answer("Некорректные данные кнопки.", show_alert=True)
        return

    ad_data = ADS_PENDING.get(ad_id)
    if not ad_data:
        await callback.answer("Объявление не найдено.", show_alert=True)
        return

    role = ad_data.get("role", "Работодатель")

    await state.clear()
    await state.update_data(**ad_data)

    # --- Соискатель ---
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
        else:
            # all / кастом – просто показываем предпросмотр
            await state.set_state(SeekerForm.preview)
            await send_preview(callback.from_user.id, state, callback.bot)

        await callback.answer()
        return

    # --- Работодатель ---
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
    else:
        # all / кастом – показываем предпросмотр
        await state.set_state(EmployerForm.preview)
        await send_preview(callback.from_user.id, state, callback.bot)

    await callback.answer()


# ------ МОДЕРАЦИЯ: ШАГ 4. Модератор вводит свою причину (custom) ------


@router.message(ModRejectionForm.awaiting_reason)
async def mod_custom_reason(message: Message, state: FSMContext):
    state_data = await state.get_data()
    ad_id = state_data.get("ad_id")

    if not ad_id:
        await message.answer("Не удалось определить объявление для отклонения.")
        await state.clear()
        return

    ad_data = ADS_PENDING.get(ad_id)
    if not ad_data:
        await message.answer("Объявление не найдено.")
        await state.clear()
        return

    if ad_id in PROCESSED_ADS:
        await message.answer("Это объявление уже обработано.")
        await state.clear()
        return

    custom_reason = (message.text or "").strip()
    if not custom_reason:
        await message.answer("Причина пустая. Напиши текст причины.")
        return

    author_id = ad_data.get("author_id")

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
            text=f"❌ Ваше объявление отклонено модератором.\nПричина: {custom_reason}",
            reply_markup=edit_kb,
        )

    extra_text = f"✖ Отклонено: причина — {custom_reason}"
    await send_ad_preview(
        config.moderation_chat_id,
        ad_data,
        message.bot,
        extra_text=extra_text,
    )

    PROCESSED_ADS.add(ad_id)
    await message.answer("Причина отклонения отправлена пользователю.")
    await state.clear()


# ------ МОДЕРАЦИЯ: ОДОБРЕНИЕ ------


@router.callback_query(F.data.startswith("mod_approve"))
async def mod_approve_callback(callback: CallbackQuery):
    """
    Модератор нажал «Одобрить».
    Публикуем объявление в основной канал, отмечаем как обработанное,
    считаем лимит для автора.
    """
    try:
        _, ad_id = callback.data.split(":")
    except ValueError:
        await callback.answer("Некорректные данные кнопки.", show_alert=True)
        return

    ad_data = ADS_PENDING.get(ad_id)
    if not ad_data:
        await callback.answer("Объявление не найдено.", show_alert=True)
        return

    if ad_id in PROCESSED_ADS:
        await callback.answer("Это объявление уже обработано.", show_alert=True)
        return

    main_channel_id = config.main_channel_id
    channel_username = config.channel_username.lstrip("@")
    text_public = get_ad_text(ad_data, include_author=False)

    author_id = ad_data.get("author_id")
    moderator = callback.from_user.username
    moderator_text = f"@{moderator}" if moderator else f"id{callback.from_user.id}"

    # Публикация в канал
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
            text=text_public,
        )

    post_url = f"https://t.me/{channel_username}/{sent_msg.message_id}"

    # Сообщение в мод-чат
    mod_text = f"✅ Опубликовано!\nМодератор: {moderator_text}\nСсылка: {post_url}"
    await send_ad_preview(
        config.moderation_chat_id,
        ad_data,
        callback.bot,
        extra_text=mod_text,
    )

    # Сообщение автору + лимит
    if author_id:
        # лимит уже увеличен в момент отправки на модерацию
        # здесь только считаем, сколько осталось

        if author_id in UNLIMITED_USERS:
            remaining = "∞"
        else:
            today = datetime.date.today().isoformat()
            data = USER_PUB_COUNTER.get(author_id)
            if not data or data.get("date") != today:
                remaining = 3
            else:
                remaining = max(0, 3 - data["count"])

        await callback.bot.send_message(
            chat_id=author_id,
            text=(
                f"✅ Ваше объявление опубликовано!\n"
                f"Ссылка: {post_url}\n\n"
                f"Осталось бесплатных публикаций сегодня: {remaining}/3\n\n"
                f"Чтобы добавить следующее объявление — нажми /start"
            ),
        )

    PROCESSED_ADS.add(ad_id)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.answer("Объявление опубликовано!")


# ------ ТОЧКА ВХОДА БОТА ------


async def main():
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # подключаем все роутеры
    dp.include_router(start_router)  # /start и выбор роли
    dp.include_router(forms_router)  # общие формы/модерация
    dp.include_router(employer_router)  # работодатель
    dp.include_router(seeker_router)  # соискатель

    logging.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
