from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple


_PHONE_CLEAN_RE = re.compile(r"[^\d+]+")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_URL_RE = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)
_TG_USERNAME_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{4,32}(?!\w)")
_SOCIAL_HINT_RE = re.compile(
    r"\b(vk|vkontakte|instagram|inst|ig|facebook|fb|tiktok|discord|skype|whatsapp|wa|telegram|tg|signal|viber)\b",
    re.IGNORECASE,
)


@dataclass
class ContactsResult:
    ok: bool
    normalized: str
    hint: str = ""


def _normalize_phone(raw: str) -> str | None:
    s = raw.strip()
    if not s:
        return None

    s = _PHONE_CLEAN_RE.sub("", s)

    if s.count("+") > 1:
        return None

    digits = re.sub(r"\D", "", s)

    if len(digits) < 6:
        return None

    if len(digits) == 11 and digits[0] in ("7", "8"):
        return "+7" + digits[1:]

    if s.startswith("+") and len(digits) >= 8:
        return "+" + digits

    if len(digits) >= 8:
        return digits

    return None


def _extract_phone_candidates(text: str) -> List[str]:
    return re.findall(r"(?:\+?\d[\d\s().-]{5,}\d)", text)


def normalize_contacts(text: str) -> ContactsResult:
    raw = (text or "").strip()
    if not raw:
        return ContactsResult(
            ok=False,
            normalized="",
            hint=(
                "Контакты пустые.\n\n"
                "Примеры:\n"
                "• +7 999 111-22-33\n"
                "• @username\n"
                "• email@example.com\n"
                "• https://t.me/username\n"
                "• FB: john.smith"
            ),
        )

    has_email = bool(_EMAIL_RE.search(raw))
    has_url = bool(_URL_RE.search(raw))
    has_tg = bool(_TG_USERNAME_RE.search(raw))
    has_social = bool(_SOCIAL_HINT_RE.search(raw))

    phones_src = _extract_phone_candidates(raw)
    normalized_phones: List[Tuple[str, str]] = []

    for p in phones_src:
        np = _normalize_phone(p)
        if np:
            normalized_phones.append((p, np))

    normalized = raw
    for src, np in normalized_phones:
        normalized = normalized.replace(src, np)

    has_phone = bool(normalized_phones)

    if has_email or has_url or has_tg or has_social or has_phone:
        return ContactsResult(ok=True, normalized=normalized)

    if len(raw) >= 4 and any(ch in raw for ch in (":", "/", ".", " ")):
        return ContactsResult(ok=True, normalized=normalized)

    return ContactsResult(
        ok=False,
        normalized=raw,
        hint=(
            "Не похоже на контакт 😅\n\n"
            "Можно указать ЛЮБОЙ способ связи:\n"
            "• +7 999 111-22-33\n"
            "• @username\n"
            "• email@example.com\n"
            "• ссылка (t.me / vk / instagram / facebook)\n"
            "• текстом: \"FB: john.smith\""
        ),
    )
