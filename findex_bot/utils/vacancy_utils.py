# findex_bot/utils/vacancy_utils.py
from __future__ import annotations

import re
from typing import Any


def _p(ad_or_payload: Any) -> dict:
    if ad_or_payload is None:
        return {}
    if isinstance(ad_or_payload, dict):
        return dict(ad_or_payload)
    payload = getattr(ad_or_payload, "payload", None)
    return dict(payload) if isinstance(payload, dict) else {}


def make_hashtag(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "", text)
    return f"#{cleaned}" if cleaned else ""


def get_ad_text(ad_or_payload: Any) -> str:
    """
    Предпросмотр/публикация: строго как на скрине.

    Заголовок:
      Работодатель / Соискатель

    Далее строки (одной колонкой):
      👤 Должность: ...
      🕒 График: ... (только seeker)
      💲 Зарплата: ...
      📍 Локация: ...
      📞 Контакты: ...
      📝 О себе/Описание:
      <текст>

    В конце:
      #FindexHub #<должность> #<локация>
    """
    payload = _p(ad_or_payload)
    role = (payload.get("role") or getattr(ad_or_payload, "role", None) or "employer").strip()

    title = (payload.get("title") or "").strip()
    salary = (payload.get("salary") or "").strip()
    location = (payload.get("location") or "").strip()
    contacts = (payload.get("contacts") or "").strip()
    description = (payload.get("description") or "").strip()
    schedule = (payload.get("schedule") or "").strip()

    tags = f"#FindexHub {make_hashtag(title)} {make_hashtag(location)}".strip()

    if role == "seeker":
        return (
            "Соискатель\n\n"
            f"👤 Должность: {title}\n"
            f"🕒 График: {schedule}\n"
            f"💲 Зарплата: {salary}\n"
            f"📍 Локация: {location}\n"
            f"📞 Контакты: {contacts}\n"
            "📝 О себе:\n"
            f"{description}\n\n"
            f"{tags}"
        )

    return (
        "Работодатель\n\n"
        f"👤 Должность: {title}\n"
        f"💲 Зарплата: {salary}\n"
        f"📍 Локация: {location}\n"
        f"📞 Контакты: {contacts}\n"
        "📝 Описание:\n"
        f"{description}\n\n"
        f"{tags}"
    )


# ------------------------------------------------------------
# ✅ Совместимость: form_handlers.py ожидает contains_bad_words()
# ------------------------------------------------------------
def contains_bad_words(text: str) -> bool:
    """
    Возвращает True если в тексте обнаружены запрещённые слова.
    Сейчас это совместимость, чтобы бот не падал на импорте.

    1) Если в runtime есть BAD_WORDS (список слов) — используем его.
    2) Если нет — считаем, что плохих слов нет (False).
    """
    try:
        import findex_bot.runtime as runtime  # локальный импорт, чтобы избежать циклов
        bad = getattr(runtime, "BAD_WORDS", None)
        if not bad:
            return False
        t = (text or "").lower()
        return any(str(w).lower() in t for w in bad)
    except Exception:
        return False
