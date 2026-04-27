from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

router = Router()

CB_CREATE_TICKET = "support:create_ticket"

def create_ticket_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Создать обращение", callback_data=CB_CREATE_TICKET)]
    ])

START_TEXT = (
    "👋 Это официальный саппорт FindexHub\n"
    "Все обращения обрабатываются через форму\n"
    "Менеджер свяжется с вами при необходимости\n\n"
    "Нажми кнопку ниже, чтобы создать обращение."
)

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(START_TEXT, reply_markup=create_ticket_kb())

@router.callback_query(F.data == CB_CREATE_TICKET)
async def cb_create_ticket(callback: CallbackQuery):
    # ✅ тут показываем твоё ТЕКУЩЕЕ меню категорий (второй экран)
    # ВАЖНО: ниже я вызываю функцию show_categories(...)
    # Ты просто подставишь свою реальную функцию/код, который сейчас рисует меню.
    from support_bot.handlers.menu import show_categories  # подстрой импорт под свою структуру

    await callback.answer()
    await show_categories(callback.message)
