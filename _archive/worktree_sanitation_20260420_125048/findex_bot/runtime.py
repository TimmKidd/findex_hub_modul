# findex_bot/runtime.py
from __future__ import annotations

import datetime
from typing import Any

# ======================================================
# ЕДИНЫЙ ИСТОЧНИК ПРАВДЫ ДЛЯ runtime/handlers
# ======================================================

# ------------------ CONFIG ------------------
# сюда bot.py кладёт Config()
CONFIG = None  # type: ignore


# ------------------ ADS STORAGE ------------------
ADS_PENDING: dict[str, dict] = {}      # ожидает модерации
ADS_REJECTED: dict[str, dict] = {}     # отклонено
PUBLISHED_POSTS: dict[str, dict] = {}  # опубликовано


# ------------------ PREVIEW LOCKS ------------------
# режимы (используем одинаково везде)
PREVIEW_MODE_MODERATION = "moderation"
PREVIEW_MODE_PUBLISHED = "published"

# ✅ Хранилище залоченных превью:
# dict[(chat_id, message_id)] = "moderation" | "published"
PUBLISHED_PREVIEW_MESSAGES: dict[tuple[int, int], str] = {}

# ✅ Жёсткий юзер-лок (если решишь использовать):
# set[user_id]
LOCKED_PREVIEW_USERS: set[int] = set()


def _ensure_preview_storage() -> dict[tuple[int, int], str]:
    """
    Гарантируем единый тип хранилища.
    Если где-то старый код оставил set[(chat_id,msg_id)] — конвертируем в dict с mode=moderation.
    """
    global PUBLISHED_PREVIEW_MESSAGES
    if isinstance(PUBLISHED_PREVIEW_MESSAGES, set):
        converted: dict[tuple[int, int], str] = {}
        for item in PUBLISHED_PREVIEW_MESSAGES:
            try:
                chat_id, msg_id = item
                converted[(int(chat_id), int(msg_id))] = PREVIEW_MODE_MODERATION
            except Exception:
                continue
        PUBLISHED_PREVIEW_MESSAGES = converted
    if not isinstance(PUBLISHED_PREVIEW_MESSAGES, dict):
        PUBLISHED_PREVIEW_MESSAGES = {}
    return PUBLISHED_PREVIEW_MESSAGES


def lock_preview(chat_id: int, message_id: int, mode: str) -> None:
    store = _ensure_preview_storage()
    store[(int(chat_id), int(message_id))] = str(mode)


def get_preview_mode(chat_id: int, message_id: int) -> str | None:
    store = _ensure_preview_storage()
    return store.get((int(chat_id), int(message_id)))


# ------------------ LIMITS ------------------
USER_PUB_COUNTER: dict[int, dict[str, int]] = {}

# блокировки
BLOCKED_USERS: set[int] = set()

# кто безлимит/модер
UNLIMITED_USERS: set[int] = {80675147, 7107629211}
MODERATORS: set[int] = set(UNLIMITED_USERS)


def _today_str() -> str:
    return datetime.date.today().isoformat()


def can_publish_today(user_id: int) -> bool:
    if user_id in UNLIMITED_USERS:
        return True

    today = _today_str()
    data = USER_PUB_COUNTER.get(user_id)
    if not data or data.get("date") != today:
        return True

    return int(data.get("count", 0)) < 3


def record_published(user_id: int) -> int | str:
    if user_id in UNLIMITED_USERS:
        return "∞"

    today = _today_str()
    data = USER_PUB_COUNTER.get(user_id)

    if not data or data.get("date") != today:
        USER_PUB_COUNTER[user_id] = {"date": today, "count": 0}
        data = USER_PUB_COUNTER[user_id]

    data["count"] = int(data.get("count", 0)) + 1
    return max(0, 3 - data["count"])


def get_remaining_today(user_id: int) -> int | str:
    if user_id in UNLIMITED_USERS:
        return "∞"

    today = _today_str()
    data = USER_PUB_COUNTER.get(user_id)
    if not data or data.get("date") != today:
        return 3

    return max(0, 3 - int(data.get("count", 0)))


def is_blocked(user_id: int) -> bool:
    return user_id in BLOCKED_USERS


def has_pending_moderation(user_id: int) -> bool:
    """
    Ищем ожидания модерации у пользователя.
    В твоём payload в forms.py используется author_id / user_chat_id.
    Поэтому ищем оба.
    """
    for _k, v in (ADS_PENDING or {}).items():
        if not isinstance(v, dict):
            continue
        uid = v.get("author_id") or v.get("user_id") or v.get("from_user_id") or v.get("user_chat_id")
        try:
            if int(uid) == int(user_id):
                return True
        except Exception:
            continue
    return False


def _safe_user_id_from_any(v: Any) -> int | None:
    if isinstance(v, dict):
        uid = v.get("author_id") or v.get("user_id") or v.get("from_user_id") or v.get("user_chat_id")
        try:
            return int(uid)
        except Exception:
            return None
    return None