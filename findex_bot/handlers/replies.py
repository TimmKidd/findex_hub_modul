# findex_bot/handlers/replies.py
from __future__ import annotations

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)
router = Router()

"""
ВАЖНО:
- В ЭТОМ ФАЙЛЕ НЕ ДОЛЖНО БЫТЬ SeekerForm / EmployerForm / vac_seeker / vac_employer.
- Этот файл отвечает ТОЛЬКО за "ответы/отклики" (replies).
- Если тут оставить дубли callback'ов вакансий — ломаются кнопки и логика.
"""

# ------------------------------------------------------
# FUTURE: ОТКЛИК НА ОБЪЯВЛЕНИЕ (пока заглушка)
# ------------------------------------------------------
@router.callback_query(F.data.startswith("reply_to:"))
async def reply_to_ad(callback: CallbackQuery):
    """
    callback_data пример: reply_to:<ad_id>
    """
    try:
        await callback.answer("Функция отклика пока выключена", show_alert=True)
    except Exception:
        pass


# ------------------------------------------------------
# FUTURE: ПОКАЗАТЬ КОНТАКТЫ (пока заглушка)
# ------------------------------------------------------
@router.callback_query(F.data.startswith("show_contacts:"))
async def show_contacts(callback: CallbackQuery):
    """
    callback_data пример: show_contacts:<ad_id>
    """
    try:
        await callback.answer("Контакты будут доступны позже", show_alert=True)
    except Exception:
        pass


# ------------------------------------------------------
# SAFETY: Если вдруг прилетело что-то непонятное именно сюда
# (но лучше пусть это ловят другие роутеры)
# ------------------------------------------------------
@router.callback_query(F.data.startswith("reply:") | F.data.startswith("fav:") | F.data.startswith("repost:"))
async def legacy_post_buttons(callback: CallbackQuery):
    """
    Если у тебя где-то остались старые callback_data вида reply:/fav:/repost:
    чтобы не было "крутилки" — просто отвечаем.
    """
    try:
        await callback.answer("⏳ Функция временно отключена", show_alert=True)
    except Exception:
        pass