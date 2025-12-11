import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv
import asyncio

logging.basicConfig(level=logging.INFO)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID"))

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# --- Словарь для хранения вопросов (user_id: {'theme':..., 'text':...}) ---
# Для продакшена: заменить на БД!
user_last_question = {}

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
SOON_CALLBACKS = ["search_filters_problem", "profile_question_soon"]

def get_main_inline_keyboard():
    keyboard = [[InlineKeyboardButton(text=text, callback_data=callback)] for (text, callback) in BUTTONS]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

class SupportStates(StatesGroup):
    waiting_text = State()
    suggest_feature = State()
    last_callback = State()
    reply_to_user_id = State()
    reply_theme = State()
    reply_question = State()

@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Здравствуйте! Чем можем помочь? Выберите подходящий пункт:",
        reply_markup=get_main_inline_keyboard(),
    )

@dp.callback_query(F.data.in_(SOON_CALLBACKS))
async def soon_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Загрузка... Этот раздел пока в разработке.", show_alert=True)

@dp.callback_query(F.data == "suggest_feature")
async def feature_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Пожалуйста, опишите ваше предложение по 4 пунктам:\n"
        "1. Что добавить?\n"
        "2. Зачем это нужно?\n"
        "3. Кому это поможет?\n"
        "4. Пример использования.",
        reply_markup=None,
    )
    await state.set_state(SupportStates.suggest_feature)
    await state.update_data(last_callback="suggest_feature")
    await callback.answer()

@dp.message(SupportStates.suggest_feature)
async def handle_suggest_feature(message: Message, state: FSMContext):
    user = message.from_user
    question = message.text
    user_last_question[user.id] = {"theme": "Хочу предложить новую функцию", "text": question}
    await send_support_message_to_group(
        "Хочу предложить новую функцию",
        user,
        question
    )
    await message.answer(
        "Спасибо за вашу идею! Она передана команде разработки ✅",
        reply_markup=get_main_inline_keyboard(),
    )
    await state.clear()

@dp.callback_query(
    F.data.in_([
        "publish_problem",
        "dm_question",
        "notification_error",
        "myads_problem",
        "bot_error",
        "service_feature_question",
        "other",
    ])
)
async def ask_for_problem_details(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SupportStates.waiting_text)
    await state.update_data(last_callback=callback.data)
    selected_text = next((text for text, cb in BUTTONS if cb == callback.data), "")
    await callback.message.edit_text(
        f"Пожалуйста, опишите подробности по теме:\n<b>{selected_text}</b>\n"
        "Максимально подробно опишите проблему, вопрос или ваш кейс.",
        parse_mode="HTML",
        reply_markup=None,
    )
    await callback.answer()

@dp.message(SupportStates.waiting_text)
async def handle_problem_details(message: Message, state: FSMContext):
    user = message.from_user
    data = await state.get_data()
    theme_callback = data.get("last_callback")
    theme_text = next((text for text, cb in BUTTONS if cb == theme_callback), "Без темы")
    question = message.text
    user_last_question[user.id] = {"theme": theme_text, "text": question}
    await send_support_message_to_group(theme_text, user, question)
    await message.answer(
        f"Ваше обращение по теме <b>{theme_text}</b> отправлено в поддержку!",
        parse_mode="HTML",
        reply_markup=get_main_inline_keyboard(),
    )
    await state.clear()

# Отправка обращения в саппорт-группу с кнопкой "Ответить"
async def send_support_message_to_group(theme_text, user: types.User, question_text):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Ответить",
                    callback_data=f"support_reply_{user.id}"
                )
            ]
        ]
    )
    msg = (
        f"[ОБРАЩЕНИЕ]\n"
        f"Тема: {theme_text}\n"
        f"От: @{user.username or '[без username]'} (id: <code>{user.id}</code>)\n"
        f"Текст обращения:\n{question_text}"
    )
    await bot.send_message(SUPPORT_GROUP_ID, msg, parse_mode="HTML", reply_markup=kb)

# Получение нажатия кнопки "Ответить" в саппорт-группе
@dp.callback_query(F.data.regexp(r"^support_reply_(\d+)$"))
async def support_reply_callback(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[-1])
    # достаем тему и вопрос для будущей цитаты!
    theme = user_last_question.get(user_id, {}).get("theme", "")
    question = user_last_question.get(user_id, {}).get("text", "")
    await state.set_state(SupportStates.reply_to_user_id)
    await state.update_data(reply_to=user_id)
    await state.update_data(reply_theme=theme)
    await state.update_data(reply_question=question)
    await callback.message.reply(
        f"Отправьте сообщение для ответа пользователю <code>{user_id}</code> – ваш следующий текст уйдёт ему в личку.\n"
        f"Будет процитирована заявка:\n<b>{theme}</b>\n\"{question}\"",
        parse_mode="HTML"
    )
    await callback.answer()

# Ответ саппорта - Markdown quote оригинала
@dp.message(SupportStates.reply_to_user_id)
async def support_send_answer_to_user(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get('reply_to')
    theme = data.get('reply_theme', "")
    question = data.get('reply_question', "")
    support_text = message.text

    # Markdown quote блок (бот отправляет ТЕКСТ пользователя + ответ, как цитата)
    markdown_msg = (
        f"📝 Ваш запрос по теме: <b>{theme}</b>\n"
        f"> {question}\n\n"
        f"💬 Ответ службы поддержки:\n"
        f"{support_text}"
    )
    try:
        await bot.send_message(
            user_id,
            markdown_msg,
            parse_mode="HTML"
        )
        await message.reply("Ответ отправлен пользователю в ЛС (с цитатой вопроса)!")
    except Exception as e:
        await message.reply(f"Ошибка при попытке отправить пользователю: {e}")
    await state.clear()

@dp.callback_query()
async def fallback_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Некорректная команда или кнопка.", show_alert=True)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())