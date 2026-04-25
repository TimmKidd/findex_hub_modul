# findex_bot/states/vacancies.py
from __future__ import annotations

from aiogram.fsm.state import StatesGroup, State


class EmployerForm(StatesGroup):
    title = State()
    salary = State()
    location = State()
    contacts = State()
    description = State()

    media_choice = State()
    media_wait = State()
    media_confirm = State()

    preview = State()


class SeekerForm(StatesGroup):
    title = State()
    schedule = State()
    salary = State()
    location = State()
    contacts = State()
    description = State()

    media_choice = State()
    media_wait = State()
    media_confirm = State()

    preview = State()
