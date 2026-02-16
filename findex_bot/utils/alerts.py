# findex_bot/utils/alerts.py
from __future__ import annotations

import json
import time
import uuid
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import findex_bot.runtime as runtime

logger = logging.getLogger(__name__)

# ----------------------------
# Redis keys
# ----------------------------
KEY_ALERTS_USER = "alerts:{user_id}"                      # json list
KEY_USERS_BY_TARGET = "alerts_users:{target_role}"        # set(user_id)
KEY_DELIVERED = "alerts_delivered:{user_id}:{alert_id}"   # set(ad_id) + TTL

DELIVERED_TTL_SECONDS = 7 * 24 * 3600   # 7 дней
ALERT_TTL_SECONDS = 3 * 24 * 3600       # 3 дня

ROLE_SEEKER = "Соискатель"
ROLE_EMPLOYER = "Работодатель"


def _get_redis():
    return getattr(runtime, "REDIS", None)


# ----------------------------
# Normalize / match
# ----------------------------
_SPACE_RE = re.compile(r"\s+")
_JUNK_RE = re.compile(r"[^\w\s\-]+", flags=re.UNICODE)


def _normalize(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("ё", "е")
    s = _JUNK_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s)
    return s.strip()


def _split_keywords(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    parts = [_normalize(p) for p in parts if p.strip()]
    seen = set()
    out: list[str] = []
    for p in parts:
        if p and p not in seen:
            out.append(p)
            seen.add(p)
    return out


def _matches_keywords(value: str, keywords: list[str]) -> bool:
    # ⛔ по твоему ТЗ пустые фильтры запрещены
    if not keywords:
        return False
    v = _normalize(value)
    if not v:
        return False
    return any(k in v for k in keywords if k)


def _alert_matches(ad_role: str, ad_position: str, ad_location: str, alert: dict) -> bool:
    if (alert.get("target_role") or "") != ad_role:
        return False
    if not alert.get("enabled", True):
        return False

    pos_kw = alert.get("position_keywords") or []
    loc_kw = alert.get("location_keywords") or []

    # ⛔ теперь оба фильтра обязательны
    if not pos_kw or not loc_kw:
        return False

    if not _matches_keywords(ad_position, pos_kw):
        return False
    if not _matches_keywords(ad_location, loc_kw):
        return False

    return True


# ----------------------------
# Store
# ----------------------------
@dataclass
class Alert:
    id: str
    enabled: bool
    target_role: str
    position_keywords: list[str]
    location_keywords: list[str]
    created_at: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "enabled": bool(self.enabled),
            "target_role": self.target_role,
            "position_keywords": list(self.position_keywords or []),
            "location_keywords": list(self.location_keywords or []),
            "created_at": int(self.created_at),
        }


def _safe_json_load(raw: Any) -> Any:
    if raw is None:
        return None
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
        if not isinstance(raw, str):
            return None
        raw = raw.strip()
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


def _ensure_alert_shape(a: dict) -> dict:
    if not isinstance(a, dict):
        return {}
    a.setdefault("enabled", True)
    a.setdefault("position_keywords", [])
    a.setdefault("location_keywords", [])
    a.setdefault("created_at", int(time.time()))
    return a


async def get_user_alerts(user_id: int) -> list[dict]:
    r = _get_redis()
    if r is None:
        store = getattr(runtime, "ALERTS_MEM", {}) or {}
        runtime.ALERTS_MEM = store
        data = list(store.get(int(user_id), []))
        return [_ensure_alert_shape(a) for a in data if isinstance(a, dict)]

    key = KEY_ALERTS_USER.format(user_id=int(user_id))
    raw = await r.get(key)
    data = _safe_json_load(raw)
    if not isinstance(data, list):
        return []
    out = []
    for a in data:
        if isinstance(a, dict):
            out.append(_ensure_alert_shape(a))
    return out


async def set_user_alerts(user_id: int, alerts: list[dict]) -> None:
    clean = []
    for a in alerts or []:
        if isinstance(a, dict):
            clean.append(_ensure_alert_shape(a))

    r = _get_redis()
    if r is None:
        store = getattr(runtime, "ALERTS_MEM", {}) or {}
        runtime.ALERTS_MEM = store
        store[int(user_id)] = list(clean)
        return

    key = KEY_ALERTS_USER.format(user_id=int(user_id))
    await r.set(key, json.dumps(clean, ensure_ascii=False))


async def _rebuild_user_target_index(user_id: int, alerts: list[dict]) -> None:
    r = _get_redis()
    if r is None:
        return

    uid = int(user_id)

    await r.srem(KEY_USERS_BY_TARGET.format(target_role=ROLE_SEEKER), uid)
    await r.srem(KEY_USERS_BY_TARGET.format(target_role=ROLE_EMPLOYER), uid)

    targets = set()
    for a in alerts or []:
        if a.get("enabled", True) and a.get("target_role") in (ROLE_SEEKER, ROLE_EMPLOYER):
            targets.add(a.get("target_role"))
    for t in targets:
        await r.sadd(KEY_USERS_BY_TARGET.format(target_role=t), uid)


async def add_alert(user_id: int, target_role: str, position_raw: str, location_raw: str) -> dict:
    pos = _split_keywords(position_raw)
    loc = _split_keywords(location_raw)
    if not pos or not loc:
        raise ValueError("position and location are required")

    alerts = await get_user_alerts(user_id)

    a = Alert(
        id=uuid.uuid4().hex[:10],
        enabled=True,
        target_role=target_role,
        position_keywords=pos,
        location_keywords=loc,
        created_at=int(time.time()),
    )

    alerts.append(a.to_dict())
    await set_user_alerts(user_id, alerts)
    await _rebuild_user_target_index(user_id, alerts)
    return a.to_dict()


async def toggle_alert(user_id: int, alert_id: str) -> Optional[dict]:
    alerts = await get_user_alerts(user_id)
    changed = None
    for a in alerts:
        if a.get("id") == alert_id:
            a["enabled"] = not bool(a.get("enabled", True))
            changed = a
            break
    if changed is None:
        return None
    await set_user_alerts(user_id, alerts)
    await _rebuild_user_target_index(user_id, alerts)
    return changed


async def delete_alert(user_id: int, alert_id: str) -> bool:
    alerts = await get_user_alerts(user_id)
    new_list = [a for a in alerts if a.get("id") != alert_id]
    if len(new_list) == len(alerts):
        return False
    await set_user_alerts(user_id, new_list)
    await _rebuild_user_target_index(user_id, new_list)
    return True


# ----------------------------
# Render (канон: 3 якоря + TTL “истекает через”)
# ----------------------------
def _ttl_human_left(seconds_left: int) -> str:
    # строго одна строка: Xд Yч
    if seconds_left <= 0:
        return "0д 0ч"
    days = seconds_left // 86400
    hours = (seconds_left % 86400) // 3600
    return f"{days}д {hours}ч"


def format_alert_line(a: dict) -> str:
    enabled = a.get("enabled", True)
    status = "🟢" if enabled else "🔴"

    target = (a.get("target_role") or "?").strip()
    pos = ", ".join(a.get("position_keywords") or [])
    loc = ", ".join(a.get("location_keywords") or [])

    created_at = int(a.get("created_at") or int(time.time()))
    left = (created_at + ALERT_TTL_SECONDS) - int(time.time())
    ttl_txt = _ttl_human_left(left)

    # 3 якоря обязательны
    if not pos or not loc or target not in (ROLE_SEEKER, ROLE_EMPLOYER):
        return f"{status} <b>{target or '?'}</b> | 👤 (ошибка) | 📍 (ошибка) | ⏳ истекает через {ttl_txt}"

    # роль с эмодзи всегда (у обоих)
    return f"{status} <b>{target}</b> | 👤 {pos} | 📍 {loc} | ⏳ истекает через {ttl_txt}"


def alert_card_keyboard(alert: dict, *, show_create: bool = True, show_back: bool = True) -> InlineKeyboardMarkup:
    aid = str(alert.get("id") or "")
    enabled = bool(alert.get("enabled", True))

    rows = [
        [
            InlineKeyboardButton(text=("🔕 Выкл" if enabled else "🔔 Вкл"), callback_data=f"al_toggle:{aid}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"al_del:{aid}"),
        ]
    ]
    if show_create:
        rows.append([InlineKeyboardButton(text="➕ Создать уведомление", callback_data="al_new")])
    if show_back:
        rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="al_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def alerts_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать уведомление", callback_data="al_new")],
            [InlineKeyboardButton(text="📋 Мои уведомления", callback_data="al_list")],
        ]
    )


def choose_target_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Хочу резюме (соискателей)", callback_data=f"al_target:{ROLE_SEEKER}")],
            [InlineKeyboardButton(text="💼 Хочу вакансии (работодателей)", callback_data=f"al_target:{ROLE_EMPLOYER}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="al_back")],
        ]
    )


# ----------------------------
# Delivered dedup
# ----------------------------
async def _delivered_check_and_mark(user_id: int, alert_id: str, ad_id: str) -> bool:
    r = _get_redis()
    if r is None:
        mem = getattr(runtime, "ALERTS_DELIVERED_MEM", {}) or {}
        runtime.ALERTS_DELIVERED_MEM = mem
        key = (int(user_id), str(alert_id))
        s = mem.get(key, set())
        if ad_id in s:
            return True
        s.add(ad_id)
        mem[key] = s
        return False

    key = KEY_DELIVERED.format(user_id=int(user_id), alert_id=str(alert_id))
    if await r.sismember(key, ad_id):
        return True
    await r.sadd(key, ad_id)
    await r.expire(key, DELIVERED_TTL_SECONDS)
    return False


def _map_role_to_target_role(role_raw: str) -> str:
    r = (role_raw or "").strip().lower()
    if r in ("соискатель", "seek", "seeker", "resume"):
        return ROLE_SEEKER
    if r in ("работодатель", "emp", "employer", "vacancy"):
        return ROLE_EMPLOYER
    if role_raw in (ROLE_SEEKER, ROLE_EMPLOYER):
        return role_raw
    return ""


async def notify_on_published(bot, *, ad_data: dict, url: str, ad_id: str) -> int:
    ad_role = _map_role_to_target_role(str(ad_data.get("role") or ""))
    if ad_role not in (ROLE_SEEKER, ROLE_EMPLOYER):
        return 0

    ad_position = (ad_data.get("position") or "").strip()
    ad_location = (ad_data.get("location") or "").strip()

    r = _get_redis()

    user_ids: list[int] = []
    if r is None:
        store = getattr(runtime, "ALERTS_MEM", {}) or {}
        for uid, alerts in store.items():
            if any(a.get("enabled", True) and a.get("target_role") == ad_role for a in (alerts or [])):
                user_ids.append(int(uid))
    else:
        key = KEY_USERS_BY_TARGET.format(target_role=ad_role)
        try:
            raw = await r.smembers(key)
            for x in raw or []:
                try:
                    user_ids.append(int(x))
                except Exception:
                    try:
                        user_ids.append(int(x.decode("utf-8")))
                    except Exception:
                        continue
        except Exception:
            logger.exception("alerts: smembers failed")
            return 0

    if not user_ids:
        return 0

    sent_count = 0

    # уведомление (минимально, без мусора)
    text = (
        "🔔 <b>Подходящее объявление</b>\n"
        f"🟢 <b>{ad_role}</b>\n"
        f"👤 <b>{ad_position}</b>\n"
        f"📍 <b>{ad_location}</b>"
    )

    kb = None
    if url:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Открыть объявление", url=url)]])

    for uid in user_ids:
        try:
            alerts = await get_user_alerts(uid)
            if not alerts:
                continue

            for a in alerts:
                if not _alert_matches(ad_role, ad_position, ad_location, a):
                    continue

                already = await _delivered_check_and_mark(uid, a.get("id", ""), ad_id)
                if already:
                    continue

                try:
                    await bot.send_message(
                        chat_id=int(uid),
                        text=text,
                        parse_mode="HTML",
                        reply_markup=kb,
                        disable_web_page_preview=True,
                    )
                    sent_count += 1
                except Exception:
                    continue

        except Exception:
            continue

    return sent_count