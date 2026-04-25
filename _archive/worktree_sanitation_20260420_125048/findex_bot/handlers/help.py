# findex_bot/handlers/help.py
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()

@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "ℹ️ <b>Помощь</b>\n\n"
        "Команды:\n"
        "• /start — выбор роли\n"
        "• /menu — главное меню\n"
        "• /diagnostics — диагностика публикации\n\n"
        "Если нужно связаться с поддержкой — открой /menu и нажми 🆘 Support.",
        parse_mode="HTML",
    )
