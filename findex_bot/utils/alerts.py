# findex_bot/utils/alerts.py
from __future__ import annotations

import json
import time
import uuid
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional, Iterable

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import findex_bot.runtime as runtime

logger = logging.getLogger(__name__)

# ----------------------------
# Redis keys
# ----------------------------
KEY_ALERTS_USER = "alerts:{user_id}"                 # json list
KEY_USERS_BY_TARGET = "alerts_users:{target_role}"   # set(user_id)
KEY_DELIVERED = "alerts_delivered:{user_id}:{alert_id}"  # set(ad_id) + TTL

DELIVERED_TTL_SECONDS = 7 * 24 * 3600  # 7 дней

# target_role = кого ловим (роль опубликованного объявления)
ROLE_SEEKER = "Соискатель"
ROLE_EMPLOYER = "Работодатель"

# ----------------------------
# Redis helper
# ----------------------------
def _get_redis():
    """
    Берём уже поднятый redis-клиент, если он есть в runtime.
    Ты можешь положить его туда при старте бота (см. патч bot.py ниже).
    """
    r = getattr(runtime, "REDIS", None)
    return r


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
    if not raw or raw == "-":
        return []
    parts = [p.strip() for p in raw.split(",")]
    parts = [_normalize(p) for p in parts if p.strip()]
    # удалим дубли, сохранив порядок
    seen = set()
    out = []
    for p in parts:
        if p and p not in seen:
            out.append(p)
            seen.add(p)
    return out

def _matches_keywords(value: str, keywords: list[str]) -> bool:
    """
    keywords пустой => wildcard True
    иначе True если ХОТЯ БЫ один keyword входит в value.
    """
    if not keywords:
        return True
    v = _normalize(value)
    if not v:
        return False
    return any(k in v for k in keywords if k)

def _alert_matches(ad_role: str, ad_position: str, ad_location: str, alert: dict) -> bool:
    """
    Совпадение:
    - alert.target_role должен совпасть с ролью опубликованного объявления
    - position_keywords (если есть) должны матчиться по ad_position
    - location_keywords (если есть) должны матчиться по ad_location
    - если оба списка непустые => AND (по факту просто обе проверки True)
    """
    if (alert.get("target_role") or "") != ad_role:
        return False
    if not alert.get("enabled", True):
        return False

    pos_kw = alert.get("position_keywords") or []
    loc_kw = alert.get("location_keywords") or []

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

def _safe_json_load(s: str | None) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None

async def get_user_alerts(user_id: int) -> list[dict]:
    r = _get_redis()
    if r is None:
        # fallback: память (на MVP тесте ок, но при рестарте пропадёт)
        store = getattr(runtime, "ALERTS_MEM", {}) or {}
        runtime.ALERTS_MEM = store
        return list(store.get(int(user_id), []))

    key = KEY_ALERTS_USER.format(user_id=int(user_id))
    raw = await r.get(key)
    data = _safe_json_load(raw)
    if not isinstance(data, list):
        return []
    return data

async def set_user_alerts(user_id: int, alerts: list[dict]) -> None:
    r = _get_redis()
    if r is None:
        store = getattr(runtime, "ALERTS_MEM", {}) or {}
        runtime.ALERTS_MEM = store
        store[int(user_id)] = list(alerts)
        return

    key = KEY_ALERTS_USER.format(user_id=int(user_id))
    await r.set(key, json.dumps(alerts, ensure_ascii=False))

async def _rebuild_user_target_index(user_id: int, alerts: list[dict]) -> None:
    """
    Поддерживаем индексы users_by_target_role:
    alerts_users:Соискатель  -> user_ids, которые ловят соискателей
    alerts_users:Работодатель -> user_ids, которые ловят вакансии
    """
    r = _get_redis()
    if r is None:
        return

    uid = int(user_id)

    # удалим юзера из обоих сетов, потом добавим куда надо
    await r.srem(KEY_USERS_BY_TARGET.format(target_role=ROLE_SEEKER), uid)
    await r.srem(KEY_USERS_BY_TARGET.format(target_role=ROLE_EMPLOYER), uid)

    # добавим туда, где есть хотя бы 1 enabled алерт
    targets = set()
    for a in alerts:
        if a.get("enabled", True) and a.get("target_role") in (ROLE_SEEKER, ROLE_EMPLOYER):
            targets.add(a.get("target_role"))
    for t in targets:
        await r.sadd(KEY_USERS_BY_TARGET.format(target_role=t), uid)

async def add_alert(user_id: int, target_role: str, position_raw: str, location_raw: str) -> dict:
    alerts = await get_user_alerts(user_id)

    a = Alert(
        id=uuid.uuid4().hex[:10],
        enabled=True,
        target_role=target_role,
        position_keywords=_split_keywords(position_raw),
        location_keywords=_split_keywords(location_raw),
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

def format_alert_line(a: dict) -> str:
    status = "🟢" if a.get("enabled", True) else "⚫️"
    target = a.get("target_role") or "?"
    pos = ", ".join(a.get("position_keywords") or []) or "—"
    loc = ", ".join(a.get("location_keywords") or []) or "—"
    return f"{status} <b>{target}</b> | 👤 {pos} | 📍 {loc} | <code>{a.get('id')}</code>"

def alerts_list_keyboard(alerts: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for a in alerts[:10]:  # чтобы не раздувать
        aid = a.get("id")
        if not aid:
            continue
        btn1 = InlineKeyboardButton(text=("🔕 Выкл" if a.get("enabled", True) else "🔔 Вкл"), callback_data=f"al_toggle:{aid}")
        btn2 = InlineKeyboardButton(text="🗑 Удалить", callback_data=f"al_del:{aid}")
        rows.append([btn1, btn2])
    rows.append([InlineKeyboardButton(text="➕ Создать уведомление", callback_data="al_new")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def alerts_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать уведомление", callback_data="al_new")],
            [InlineKeyboardButton(text="📋 Мои уведомления", callback_data="al_list")],
        ]
    )

def choose_target_keyboard() -> InlineKeyboardMarkup:
    # формулировки “понятные юзеру”
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Хочу резюме (соискателей)", callback_data="al_target:Соискатель")],
            [InlineKeyboardButton(text="💼 Хочу вакансии (работодателей)", callback_data="al_target:Работодатель")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="al_back")],
        ]
    )

async def _delivered_check_and_mark(user_id: int, alert_id: str, ad_id: str) -> bool:
    """
    True => уже отправляли
    False => не отправляли и мы пометили как отправленное
    """
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

async def notify_on_published(bot, *, ad_data: dict, url: str, ad_id: str) -> int:
    """
    Вызываем СТРОГО после публикации объявления в канал.
    ad_data: должен содержать role, position, location (и т.п.)
    Возвращает: сколько уведомлений отправили
    """
    ad_role = (ad_data.get("role") or "").strip()
    if ad_role not in (ROLE_SEEKER, ROLE_EMPLOYER):
        return 0

    ad_position = (ad_data.get("position") or "").strip()
    ad_location = (ad_data.get("location") or "").strip()

    r = _get_redis()

    # получаем список пользователей, которые вообще подписаны на этот target_role
    user_ids: list[int] = []
    if r is None:
        # fallback: в памяти не знаем всех -> просто пробежим по alerts_mem если он есть
        store = getattr(runtime, "ALERTS_MEM", {}) or {}
        for uid, alerts in store.items():
            if any(a.get("enabled", True) and a.get("target_role") == ad_role for a in (alerts or [])):
                user_ids.append(int(uid))
    else:
        key = KEY_USERS_BY_TARGET.format(target_role=ad_role)
        try:
            raw = await r.smembers(key)
            # redis может вернуть bytes
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

    # соберём текст уведомления
    title = "🔔 Появилось подходящее объявление"
    role_line = f"Тип: <b>{ad_role}</b>"
    pos_line = f"👤 Должность: <b>{ad_position or '—'}</b>"
    loc_line = f"📍 Локация: <b>{ad_location or '—'}</b>"

    text = f"{title}\n{role_line}\n{pos_line}\n{loc_line}"

    kb = None
    if url:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔗 Открыть объявление", url=url)]]
        )

    for uid in user_ids:
        try:
            alerts = await get_user_alerts(uid)
            if not alerts:
                continue

            for a in alerts:
                if not _alert_matches(ad_role, ad_position, ad_location, a):
                    continue

                # дедуп
                already = await _delivered_check_and_mark(uid, a.get("id", ""), ad_id)
                if already:
                    continue

                # отправляем
                try:
                    await bot.send_message(
                        chat_id=int(uid),
                        text=text + f"\n\n<code>Alert:</code> <code>{a.get('id')}</code>",
                        parse_mode="HTML",
                        reply_markup=kb,
                        disable_web_page_preview=True,
                    )
                    sent_count += 1
                except Exception:
                    # не валим весь цикл
                    continue

        except Exception:
            continue

    return sent_count
