# support_bot/support_bot.py
import os
import asyncio
import logging
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    BotCommand,
    BotCommandScopeDefault,
    MenuButtonCommands,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command

logging.basicConfig(level=logging.INFO)

# .env рядом с этим файлом (support_bot/.env)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

BOT_TOKEN = os.getenv("SUPPORT_BOT_TOKEN")
SUPPORT_GROUP_ID_RAW = os.getenv("SUPPORT_CHAT_ID")

if not BOT_TOKEN:
    raise RuntimeError("❌ SUPPORT_BOT_TOKEN не задан в .env (support_bot)")
if not SUPPORT_GROUP_ID_RAW:
    raise RuntimeError("❌ SUPPORT_CHAT_ID не задан в .env (support_bot)")

SUPPORT_GROUP_ID = int(SUPPORT_GROUP_ID_RAW)

# ✅ важно: timeout числом, parse_mode через DefaultBotProperties
session = AiohttpSession(timeout=30)
bot = Bot(
    token=BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# --- Храним последнее обращение пользователя (в памяти) ---
user_last_question: dict[int, dict[str, str]] = {}

# Кнопки для поддерживаемых тем
BUTTONS = [
    ("Проблемы с публикацией/размещением объявления", "publish_problem"),
    ("Проблемы с поиском и фильтрами (soon)", "search_filters_problem"),
    ("Вопрос по работе с личными сообщениями", "dm_question"),
    ("Ошибка в получении уведомлений", "notification_error"),
    ("Вопрос по управлению профилем (soon)", "profile_question_soon"),
    ("Проблемы отображения/поиска моих объявлений", "myads_problem"),
    ("Ошибка или баг в работе бота", "bot_error"),
    ("Вопросы по функциям сервиса", "service_feature_question"),
    ("Хочу предложить новую функцию", "suggest_feature"),
    ("Другое", "other"),
]

SOON_CALLBACKS = {"search_filters_problem", "profile_question_soon"}

# callback_data для меню
CB_MENU_START = "sb_menu_start"


def get_main_inline_keyboard() -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(text=text, callback_data=cb)] for (text, cb) in BUTTONS]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Меню саппорт-бота (то, что будет открываться по /menu)
    Минимально: кнопка Start (как ты просил).
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Start", callback_data=CB_MENU_START)],
        ]
    )


def is_support_group(event_chat_id: int | None) -> bool:
    return bool(event_chat_id) and int(event_chat_id) == SUPPORT_GROUP_ID


class SupportStates(StatesGroup):
    waiting_text = State()
    suggest_feature = State()
    reply_mode = State()  # саппорт пишет ответ пользователю


async def show_start(message: Message, state: FSMContext) -> None:
    """
    Единая функция: показывает стартовый экран саппорта
    """
    await state.clear()
    await message.answer(
        "👋 <b>Это официальный саппорт FindexHub</b>\n"
        "Все обращения обрабатываются через форму.\n"
        "Менеджер свяжется с вами при необходимости.\n\n"
        "Нажми кнопку ниже, чтобы создать обращение.",
        reply_markup=get_main_inline_keyboard(),
    )


# -------------------------
# ✅ STARTUP: ставим меню-кнопку слева от ввода + команды
# -------------------------
async def on_startup(dispatcher: Dispatcher) -> None:
    # 1) команды (чтобы Telegram красиво показывал подсказки)
    try:
        await bot.set_my_commands(
            commands=[
                BotCommand(command="start", description="Старт"),
                BotCommand(command="menu", description="Меню"),
            ],
            scope=BotCommandScopeDefault(),
        )
    except Exception as e:
        logging.exception("Не удалось set_my_commands: %r", e)

    # 2) кнопка меню слева от строки ввода (Bot Menu Button)
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logging.info("✅ Support bot: Menu Button установлен (MenuButtonCommands)")
    except Exception as e:
        logging.exception("Не удалось set_chat_menu_button: %r", e)


# ✅ Регистрируем startup ПРАВИЛЬНО (без lambda и без вызова on_startup())
dp.startup.register(on_startup)


# -------------------------
# ✅ /start
# -------------------------
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await show_start(message, state)


# -------------------------
# ✅ /menu (то, что ты называешь "главное меню саппорт-бота")
# -------------------------
@dp.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    # меню не должно оставлять пользователя в "режимах"
    await state.clear()
    await message.answer(
        "📋 <b>Меню поддержки</b>\n\nВыбери действие:",
        reply_markup=get_menu_keyboard(),
    )


# Кнопка "▶️ Start" из меню
@dp.callback_query(F.data == CB_MENU_START)
async def cb_menu_start(callback: CallbackQuery, state: FSMContext):
    if callback.message:
        await show_start(callback.message, state)
    await callback.answer()


# -------------------------
# остальная логика (без изменений)
# -------------------------
@dp.callback_query(F.data.in_(SOON_CALLBACKS))
async def soon_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Загрузка... Этот раздел пока в разработке.", show_alert=True)


@dp.callback_query(F.data == "suggest_feature")
async def feature_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Пожалуйста, опишите ваше предложение по 4 пунктам:\n"
        "1) Что добавить?\n"
        "2) Зачем это нужно?\n"
        "3) Кому это поможет?\n"
        "4) Пример использования.",
        reply_markup=None,
    )
    await state.set_state(SupportStates.suggest_feature)
    await state.update_data(last_callback="suggest_feature")
    await callback.answer()


@dp.message(SupportStates.suggest_feature)
async def handle_suggest_feature(message: Message, state: FSMContext):
    user = message.from_user
    if not user:
        return

    question = (message.text or "").strip()
    if not question:
        await message.answer("Напиши текст предложения одним сообщением 🙂")
        return

    user_last_question[user.id] = {"theme": "Хочу предложить новую функцию", "text": question}

    await send_support_message_to_group(
        theme_text="Хочу предложить новую функцию",
        user=user,
        question_text=question,
    )

    await message.answer(
        "Спасибо за вашу идею! Она передана команде разработки ✅",
        reply_markup=get_main_inline_keyboard(),
    )
    await state.clear()


@dp.callback_query(
    F.data.in_(
        {
            "publish_problem",
            "dm_question",
            "notification_error",
            "myads_problem",
            "bot_error",
            "service_feature_question",
            "other",
        }
    )
)
async def ask_for_problem_details(callback: types.CallbackQuery, state: FSMContext):
    selected_text = next((text for text, cb in BUTTONS if cb == callback.data), "Без темы")

    await state.set_state(SupportStates.waiting_text)
    await state.update_data(last_callback=callback.data)

    await callback.message.edit_text(
        f"Пожалуйста, опиши подробности по теме:\n<b>{selected_text}</b>\n\n"
        "Максимально подробно опиши проблему, вопрос или твой кейс.",
        reply_markup=None,
    )
    await callback.answer()


@dp.message(SupportStates.waiting_text)
async def handle_problem_details(message: Message, state: FSMContext):
    user = message.from_user
    if not user:
        return

    question = (message.text or "").strip()
    if not question:
        await message.answer("Напиши текст обращения одним сообщением 🙂")
        return

    data = await state.get_data()
    theme_callback = data.get("last_callback")
    theme_text = next((text for text, cb in BUTTONS if cb == theme_callback), "Без темы")

    user_last_question[user.id] = {"theme": theme_text, "text": question}

    await send_support_message_to_group(theme_text, user, question)

    await message.answer(
        f"✅ Обращение по теме <b>{theme_text}</b> отправлено в поддержку.\n"
        "Менеджер свяжется с тобой при необходимости.",
        reply_markup=get_main_inline_keyboard(),
    )
    await state.clear()


async def send_support_message_to_group(theme_text: str, user: types.User, question_text: str):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Ответить", callback_data=f"support_reply_{user.id}")]
        ]
    )

    username = f"@{user.username}" if user.username else "[без username]"
    msg = (
        f"🆘 <b>[ОБРАЩЕНИЕ]</b>\n"
        f"Тема: <b>{theme_text}</b>\n"
        f"От: {username} (id: <code>{user.id}</code>)\n\n"
        f"<b>Текст обращения:</b>\n{question_text}"
    )

    await bot.send_message(SUPPORT_GROUP_ID, msg, reply_markup=kb)


@dp.callback_query(F.data.regexp(r"^support_reply_(\d+)$"))
async def support_reply_callback(callback: CallbackQuery, state: FSMContext):
    chat_id = callback.message.chat.id if callback.message else None
    if not is_support_group(chat_id):
        await callback.answer("Недоступно.", show_alert=True)
        return

    user_id = int(callback.data.split("_")[-1])

    theme = user_last_question.get(user_id, {}).get("theme", "")
    question = user_last_question.get(user_id, {}).get("text", "")

    await state.set_state(SupportStates.reply_mode)
    await state.update_data(reply_to=user_id, reply_theme=theme, reply_question=question)

    preview = question.strip()
    if len(preview) > 600:
        preview = preview[:600] + "…"

    await callback.message.reply(
        f"✉️ Отправь следующее сообщение — и я отправлю его пользователю <code>{user_id}</code> в личку.\n\n"
        f"<b>Заявка (цитата):</b>\n"
        f"Тема: <b>{theme}</b>\n"
        f"«{preview}»",
    )
    await callback.answer()


@dp.message(SupportStates.reply_mode)
async def support_send_answer_to_user(message: Message, state: FSMContext):
    if not is_support_group(message.chat.id):
        return

    data = await state.get_data()
    user_id = data.get("reply_to")
    theme = data.get("reply_theme", "")
    question = data.get("reply_question", "")
    support_text = (message.text or "").strip()

    if not user_id:
        await message.reply("Не найден user_id для ответа. Нажми «Ответить» заново.")
        await state.clear()
        return

    if not support_text:
        await message.reply("Ответ пустой. Напиши текст одним сообщением.")
        return

    quote = question.strip()
    if len(quote) > 800:
        quote = quote[:800] + "…"

    out = (
        f"📝 <b>Твой запрос</b> (тема: <b>{theme}</b>):\n"
        f"«{quote}»\n\n"
        f"💬 <b>Ответ поддержки:</b>\n"
        f"{support_text}"
    )

    try:
        await bot.send_message(user_id, out)
        await message.reply("✅ Ответ отправлен пользователю в ЛС.")
    except Exception as e:
        await message.reply(f"❌ Ошибка отправки пользователю: <code>{e}</code>")
    finally:
        await state.clear()


@dp.callback_query()
async def fallback_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Некорректная кнопка.", show_alert=True)


async def main():
    try:
        await dp.start_polling(bot)
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
