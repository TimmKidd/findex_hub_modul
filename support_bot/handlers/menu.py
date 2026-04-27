from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

# ⚠️ если у тебя уже есть клавиатура/логика — просто перенеси её сюда в show_categories()

def categories_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Проблемы с публикацией/размещением объявления")],
            [KeyboardButton(text="Проблемы с поиском и фильтрами (soon)")],
            [KeyboardButton(text="Вопрос по работе с личными сообщениями")],
            [KeyboardButton(text="Ошибка в получении уведомлений")],
            [KeyboardButton(text="Вопрос по управлению профилем (soon)")],
            [KeyboardButton(text="Проблемы отображения/поиска моих объявлений")],
            [KeyboardButton(text="Ошибка или баг в работе бота")],
            [KeyboardButton(text="Вопросы по функциям сервиса")],
            [KeyboardButton(text="Хочу предложить новую функцию")],
            [KeyboardButton(text="Другое")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выбери категорию…",
    )

async def show_categories(message: Message):
    await message.answer(
        "Выбери тему обращения:",
        reply_markup=categories_kb()
    )
