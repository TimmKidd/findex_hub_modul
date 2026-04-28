# findex_bot/utils/vacancy_utils.py
from __future__ import annotations

import html
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


def resolve_ad_role(ad_or_payload: Any) -> str:
    payload = _p(ad_or_payload)

    role = str(payload.get("role") or payload.get("ad_role") or "").strip().lower()

    if role == "seeker":
        return "seeker"

    if role == "employer":
        return "employer"

    raise ValueError("Ad role is missing or invalid")


def get_ad_text(ad_or_payload: Any, *, include_contacts: bool = True) -> str:
    payload = _p(ad_or_payload)
    role = resolve_ad_role(ad_or_payload)

    title = (payload.get("title") or "").strip()
    salary = (payload.get("salary") or "").strip()
    location = (payload.get("location") or "").strip()
    contacts = (payload.get("contacts") or "").strip()

    about = (payload.get("about") or "").strip()
    description = (payload.get("description") or "").strip()
    seeker_text = about or description

    schedule = (payload.get("schedule") or "").strip()

    tags = f"#FindexHub {make_hashtag(title)} {make_hashtag(location)}".strip()

    if role == "seeker":
        lines = [
            "Соискатель",
            "",
            f"👤 Должность: {title}",
            f"🕒 График: {schedule}",
            f"💲 Зарплата: {salary}",
            f"📍 Локация: {location}",
        ]
        if include_contacts:
            lines.append(f"📞 Контакты: {contacts}")
        lines.extend([
            "📝 О себе:",
            f"{seeker_text}",
            "",
            f"{tags}",
        ])
        return "\n".join(lines)

    lines = [
        "Работодатель",
        "",
        f"👤 Должность: {title}",
        f"💲 Зарплата: {salary}",
        f"📍 Локация: {location}",
    ]
    if include_contacts:
        lines.append(f"📞 Контакты: {contacts}")
    lines.extend([
        "📝 Описание:",
        f"{description}",
        "",
        f"{tags}",
    ])
    return "\n".join(lines)


def _clean_inline_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\r", "\n")
    text = re.sub(r"\s*\n+\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _display_or_fallback(value: Any, fallback: str) -> str:
    text = _clean_inline_text(value)
    return text if text else fallback


def _bool_payload(payload: dict, *keys: str) -> bool:
    for key in keys:
        val = payload.get(key)
        if isinstance(val, bool):
            if val:
                return True
        elif isinstance(val, (int, float)):
            if int(val) == 1:
                return True
        elif isinstance(val, str):
            if val.strip().lower() in {"1", "true", "yes", "y", "on"}:
                return True
    return False


def is_ad_shareable(ad_or_payload: Any) -> tuple[bool, str | None]:
    if ad_or_payload is None:
        return False, "⚠️ Вакансия не найдена или уже недоступна."

    payload = _p(ad_or_payload)
    status = str(getattr(ad_or_payload, "status", "") or payload.get("status") or "").strip().lower()

    if status != "published":
        return False, "⚠️ Поделиться можно только опубликованным объявлением."

    if _bool_payload(payload, "deleted", "is_deleted", "removed", "is_removed"):
        return False, "⚠️ Вакансия не найдена или уже недоступна."

    if _bool_payload(payload, "archived", "is_archived"):
        return False, "⚠️ Объявление архивировано и недоступно для share."

    if _bool_payload(payload, "hidden", "is_hidden", "unpublished", "is_unpublished"):
        return False, "⚠️ Объявление сейчас недоступно для share."

    if "is_active" in payload and payload.get("is_active") is False:
        return False, "⚠️ Объявление сейчас недоступно для share."

    return True, None


def _share_channel_url() -> str | None:
    try:
        import findex_bot.runtime as runtime
        uname = str(getattr(runtime, "CHANNEL_USERNAME", "") or "").strip().lstrip("@")
        if uname:
            return f"https://t.me/{uname}"
    except Exception:
        pass
    return None


def _h(value: Any) -> str:
    return html.escape(str(value or ""), quote=False)


def build_share_card(ad_or_payload: Any, bot_username: str) -> str:
    ad_text = get_ad_text(ad_or_payload, include_contacts=True)

    payload = _p(ad_or_payload)
    ad_id = int(getattr(ad_or_payload, "id", 0) or payload.get("id") or 0)
    username = str(bot_username or "").strip().lstrip("@")

    deep_link = f"https://t.me/{username}?start=resp_{ad_id}" if username and ad_id else "https://t.me"

    cta_line = f'<a href="{html.escape(deep_link, quote=True)}">📩 Откликнуться за 30 секунд</a>'

    return f"{html.escape(ad_text)}\n\n{cta_line}"


def contains_bad_words(text: str) -> bool:
    try:
        import findex_bot.runtime as runtime
        bad = getattr(runtime, "BAD_WORDS", None)
        if not bad:
            return False
        t = (text or "").lower()
        return any(str(w).lower() in t for w in bad)
    except Exception:
        return False
