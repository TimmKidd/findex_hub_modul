# findex_bot/utils/validators.py
from __future__ import annotations

import re
from typing import Iterable

# -----------------------------
# Настройки
# -----------------------------
MAX_DESCRIPTION_LEN = 2000

# ВНИМАНИЕ: это базовый словарь (корни/формы) для старта.
# Ты потом утвердишь/поправишь список — я подстрою regex точнее.
PROFANITY_WORDS: list[str] = [
    # самые частые корни/формы (рус.)
    "бля", "бляд", "блять",
    "еб", "ёб", "еби", "еба", "ёба", "ебл", "ёбл",
    "пизд", "пезд",
    "хуй", "хуе", "хуё", "хуя", "хуи",
    "мудак", "мудил", "мудо",
    "сука", "суч", "сук",
    "гандон", "презерватив",  # часто в матерном контексте
    "шлюх", "простит",        # спорно, но часто используется как мат
    "ебан", "ёбан",
    "пида", "пидор", "пидр",  # оскорбительная лексика
    "залуп",
    "дроч",
    "сра", "срал", "срать",
    "говн",
]

# Собираем единый regex: ищем по подстроке (но с границами слов там, где возможно)
# Чтобы ловить "бля", "блять", "ебаный" и т.п.
_PROF_RE = re.compile(
    r"(" + r"|".join(re.escape(w) for w in PROFANITY_WORDS) + r")",
    flags=re.IGNORECASE,
)


# -----------------------------
# Нормализация регистра
# -----------------------------
_UPPER_TOKEN_RE = re.compile(r"^[A-ZА-ЯЁ0-9]+$")           # SMM, QA, 2/2 (2/2 не пройдет из-за /)
_MIXED_TOKEN_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9]+$")    # токен без пробелов/знаков
_WORD_SPLIT_RE = re.compile(r"(\s+)")


def normalize_title(text: str) -> str:
    """
    Делает 'бариста' -> 'Бариста', 'старший бариста' -> 'Старший Бариста',
    но НЕ ломает токены типа 'SMM', 'iOS', 'QA', 'C++' (C++ останется как есть из-за '+').
    """
    text = (text or "").strip()
    if not text:
        return text

    parts = _WORD_SPLIT_RE.split(text)
    out: list[str] = []

    for part in parts:
        if part.isspace() or part == "":
            out.append(part)
            continue

        token = part

        # если токен весь uppercase/цифры — оставляем
        if _UPPER_TOKEN_RE.match(token):
            out.append(token)
            continue

        # если токен "смешанный" (буквы+цифры) без знаков — капитализируем только первую букву
        # iOS -> iOS (оставим как есть, потому что первая буква "i" маленькая и это нормально)
        if _MIXED_TOKEN_RE.match(token):
            # если выглядит как iOS / eBay / YouTube — не трогаем
            if any(ch.isupper() for ch in token[1:]):
                out.append(token)
                continue
            out.append(token[:1].upper() + token[1:].lower())
            continue

        # если токен со знаками (C++, DevOps/ML и т.п.) — не трогаем
        out.append(token)

    return "".join(out).strip()


def normalize_sentence(text: str) -> str:
    """
    Делает только первую букву текста заглавной.
    Не превращает каждое слово в Title Case.
    """
    text = (text or "").strip()
    if not text:
        return text
    first = text[0].upper()
    return first + text[1:]


# -----------------------------
# Валидаторы
# -----------------------------
def validate_required(val: str, field: str = "Поле") -> str | None:
    if not (val or "").strip():
        return f"❌ {field}: поле обязательно. Введи значение."
    return None


def validate_description(val: str) -> str | None:
    v = (val or "").strip()
    if len(v) > MAX_DESCRIPTION_LEN:
        return f"❌ Слишком длинно. Максимум {MAX_DESCRIPTION_LEN} символов."
    return None


def validate_salary(val: str) -> str | None:
    """
    Лёгкая проверка: запретим совсем мусор.
    Разрешаем цифры/пробелы/знаки/слова типа 'от', 'до', 'по договоренности'.
    """
    v = (val or "").strip()
    if not v:
        return "❌ Зарплата: поле обязательно."
    # запрет на полностью буквенную белиберду без цифр и без слов-исключений
    lowered = v.lower()
    allowed_words = ("по договор", "договор", "обсуж", "по итог", "оклад", "ставка", "смена", "час")
    has_digits = any(ch.isdigit() for ch in v)
    if not has_digits and not any(w in lowered for w in allowed_words):
        return "❌ Зарплата: укажи сумму (цифрами) или понятный формат (например: «по договорённости»)."
    return None


def validate_location_letters_only(val: str) -> str | None:
    """
    В локации запрещены цифры.
    """
    v = (val or "").strip()
    if any(ch.isdigit() for ch in v):
        return "❌ Локация: цифры запрещены. Пиши только буквами."
    return None


def validate_contacts(val: str) -> str | None:
    """
    Контакты могут быть любыми (любая соцсеть/сайт/телефон),
    но запретим слишком коротко и совсем мусор.
    """
    v = (val or "").strip()
    if len(v) < 3:
        return "❌ Контакты: слишком коротко. Укажи нормальный способ связи."
    return None


def validate_no_profanity(val: str) -> str | None:
    v = (val or "").strip()
    if not v:
        return None
    if _PROF_RE.search(v):
        return "❌ Мат запрещён. Перепиши без мата."
    return None
