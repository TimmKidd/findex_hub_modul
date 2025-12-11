from aiogram.fsm.state import StatesGroup, State

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

