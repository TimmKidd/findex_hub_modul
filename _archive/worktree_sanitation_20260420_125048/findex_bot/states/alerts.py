# findex_bot/states/alerts.py
from aiogram.fsm.state import StatesGroup, State


class AlertsForm(StatesGroup):
    choosing_target = State()   # кого ловим
    position = State()          # ключевые слова по должности
    location = State()          # ключевые слова по локации
