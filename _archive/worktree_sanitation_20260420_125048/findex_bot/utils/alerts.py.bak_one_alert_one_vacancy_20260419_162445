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
# UI / UX CONFIG
# ----------------------------
TEMP_ALERT_SECONDS = 4

# ----------------------------
# Redis keys
# ----------------------------
KEY_ALERTS_USER = "alerts:{user_id}"                      # json list
KEY_USERS_BY_TARGET = "alerts_users:{target_role}"        # set(user_id)
KEY_DELIVERED = "alerts_delivered:{user_id}:{alert_id}"   # set(ad_id) + TTL
KEY_BOT_BLOCKED = "alerts_bot_blocked_users"              # set(user_id)

DELIVERED_TTL_SECONDS = 7 * 24 * 3600   # 7 дней
ALERT_TTL_SECONDS = 30 * 24 * 3600      # 30 дней

ROLE_SEEKER = "Соискатель"
ROLE_EMPLOYER = "Работодатель"

# ----------------------------
# Plans / limits (архитектурно заложено сейчас,
# в UI пока не показываем тарифы)
# ----------------------------
PLAN_FREE = "free"
PLAN_PRO = "pro"
PLAN_BUSINESS = "business"

PLAN_SPECS = {
    PLAN_FREE: {
        ROLE_SEEKER: {
            "max_alerts": 1,
            "ttl_days": 30,
            "advanced_filters": False,
            "delivery_priority": "normal",
        },
        ROLE_EMPLOYER: {
            "max_alerts": 2,
            "ttl_days": 30,
            "advanced_filters": False,
            "delivery_priority": "normal",
        },
    },
    PLAN_PRO: {
        ROLE_SEEKER: {
            "max_alerts": 999999,
            "ttl_days": 30,
            "advanced_filters": True,
            "delivery_priority": "priority",
        },
        ROLE_EMPLOYER: {
            "max_alerts": 999999,
            "ttl_days": 30,
            "advanced_filters": True,
            "delivery_priority": "priority",
        },
    },
    PLAN_BUSINESS: {
        ROLE_SEEKER: {
            "max_alerts": 999999,
            "ttl_days": 30,
            "advanced_filters": True,
            "delivery_priority": "priority",
        },
        ROLE_EMPLOYER: {
            "max_alerts": 999999,
            "ttl_days": 30,
            "advanced_filters": True,
            "delivery_priority": "priority",
        },
    },
}

LIMIT_REACHED_TEXT = (
    "⚠️ Лимит уведомлений достигнут.\n\n"
    "Удали старое уведомление, чтобы создать новое."
)


def _get_redis():
    return getattr(runtime, "REDIS", None)


def _diag_mod():
    from findex_bot.handlers import diagnostics as diag  # type: ignore
    return diag


# ----------------------------
# Plans helpers
# ----------------------------
def get_user_plan_code(user_id: int) -> str:
    # Пока всем даём Free.
    # Позже здесь можно читать тариф из БД/платёжного слоя.
    return PLAN_FREE


def get_plan_spec(user_id: int, target_role: str) -> dict[str, Any]:
    plan_code = get_user_plan_code(user_id)
    plan = PLAN_SPECS.get(plan_code, PLAN_SPECS[PLAN_FREE])
    return dict(plan.get(target_role, plan.get(ROLE_SEEKER, {})))


def get_max_alerts(user_id: int, target_role: str) -> int:
    spec = get_plan_spec(user_id, target_role)
    return int(spec.get("max_alerts", 1))


def get_ttl_days(user_id: int, target_role: str) -> int:
    spec = get_plan_spec(user_id, target_role)
    return int(spec.get("ttl_days", 30))


def active_alerts_for_role(alerts: list[dict], target_role: str) -> list[dict]:
    now_ts = int(time.time())
    out: list[dict] = []
    for a in alerts or []:
        if not isinstance(a, dict):
            continue
        if a.get("target_role") != target_role:
            continue
        if _is_alert_expired(a, now_ts):
            continue
        if not a.get("enabled", True):
            continue
        out.append(a)
    return out


def can_create_alert(user_id: int, target_role: str, alerts: list[dict]) -> bool:
    limit = get_max_alerts(user_id, target_role)
    active = active_alerts_for_role(alerts, target_role)
    return len(active) < limit


def limits_text(target_role: str, user_id: int | None = None) -> str:
    uid = int(user_id or 0)
    limit = get_max_alerts(uid, target_role) if uid else (
        1 if target_role == ROLE_SEEKER else 2
    )
    ttl_days = get_ttl_days(uid, target_role) if uid else 30

    if target_role == ROLE_SEEKER:
        return f"👤 Лимит: {limit} уведомление на {ttl_days} дней"
    if target_role == ROLE_EMPLOYER:
        return f"💼 Лимит: {limit} уведомления на {ttl_days} дней"
    return f"🔔 Лимит: {limit} уведомлений на {ttl_days} дней"


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
    if not keywords:
        return False
    v = _normalize(value)
    if not v:
        return False
    return any(k in v for k in keywords if k)


def _tokens(s: str) -> set[str]:
    v = _normalize(s)
    if not v:
        return set()
    return {t for t in v.split() if len(t) >= 3}


def _matches_location_bidirectional(value: str, keywords: list[str]) -> bool:
    if not keywords:
        return False

    v_norm = _normalize(value)
    if not v_norm:
        return False

    v_tokens = _tokens(v_norm)

    for k in keywords:
        k_norm = _normalize(k)
        if not k_norm:
            continue

        if k_norm in v_norm:
            return True
        if v_norm in k_norm:
            return True
        if v_tokens and (_tokens(k_norm) & v_tokens):
            return True

    return False


def _is_alert_expired(a: dict, now_ts: int | None = None) -> bool:
    now_ts = int(now_ts or time.time())
    expires_at = int(a.get("expires_at") or 0)
    created_at = int(a.get("created_at") or 0)

    if expires_at > 0:
        return now_ts >= expires_at

    if created_at <= 0:
        return False

    return now_ts >= (created_at + ALERT_TTL_SECONDS)


def _alert_matches(ad_role: str, ad_position: str, ad_location: str, alert: dict) -> bool:
    if (alert.get("target_role") or "") != ad_role:
        return False
    if not alert.get("enabled", True):
        return False
    if _is_alert_expired(alert):
        return False

    pos_kw = alert.get("position_keywords") or []
    loc_kw = alert.get("location_keywords") or []

    if not pos_kw or not loc_kw:
        return False

    if not _matches_keywords(ad_position, pos_kw):
        return False

    if not _matches_location_bidirectional(ad_location, loc_kw):
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
    expires_at: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "enabled": bool(self.enabled),
            "target_role": self.target_role,
            "position_keywords": list(self.position_keywords or []),
            "location_keywords": list(self.location_keywords or []),
            "created_at": int(self.created_at),
            "expires_at": int(self.expires_at),
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
    created_at = int(a.get("created_at") or int(time.time()))
    a["created_at"] = created_at

    target_role = str(a.get("target_role") or "")
    ttl_days = get_ttl_days(0, target_role) if target_role else 30
    a.setdefault("expires_at", int(created_at + ttl_days * 24 * 3600))
    return a


async def get_user_alerts(user_id: int) -> list[dict]:
    r = _get_redis()
    now_ts = int(time.time())

    if r is None:
        store = getattr(runtime, "ALERTS_MEM", {}) or {}
        runtime.ALERTS_MEM = store

        data = list(store.get(int(user_id), []))
        out: list[dict] = []
        changed = False

        for a in data:
            if not isinstance(a, dict):
                changed = True
                continue
            a = _ensure_alert_shape(a)
            if _is_alert_expired(a, now_ts):
                changed = True
                continue
            out.append(a)

        if changed:
            store[int(user_id)] = list(out)

        return out

    key = KEY_ALERTS_USER.format(user_id=int(user_id))
    raw = await r.get(key)
    data = _safe_json_load(raw)

    if not isinstance(data, list):
        return []

    out: list[dict] = []
    changed = False

    for a in data:
        if not isinstance(a, dict):
            changed = True
            continue
        a = _ensure_alert_shape(a)
        if _is_alert_expired(a, now_ts):
            changed = True
            continue
        out.append(a)

    if changed:
        await set_user_alerts(user_id, out)
        await _rebuild_user_target_index(user_id, out)

    return out


async def set_user_alerts(user_id: int, alerts: list[dict]) -> None:
    clean: list[dict] = []
    now_ts = int(time.time())

    for a in alerts or []:
        if isinstance(a, dict):
            a = _ensure_alert_shape(a)
            if _is_alert_expired(a, now_ts):
                continue
            clean.append(a)

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
    now_ts = int(time.time())

    for a in alerts or []:
        if _is_alert_expired(a, now_ts):
            continue
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

    if not can_create_alert(user_id, target_role, alerts):
        raise RuntimeError(LIMIT_REACHED_TEXT)

    now_ts = int(time.time())
    ttl_days = get_ttl_days(user_id, target_role)

    a = Alert(
        id=uuid.uuid4().hex[:10],
        enabled=True,
        target_role=target_role,
        position_keywords=pos,
        location_keywords=loc,
        created_at=now_ts,
        expires_at=now_ts + ttl_days * 24 * 3600,
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
# Render
# ----------------------------
def _ttl_human_left(seconds_left: int) -> str:
    if seconds_left <= 0:
        return "0д 0ч"
    days = seconds_left // 86400
    hours = (seconds_left % 86400) // 3600
    return f"{days}д {hours}ч"


def _title_words(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s
    return " ".join(w[:1].upper() + w[1:] for w in s.split())


def format_alert_line(a: dict) -> str:
    enabled = a.get("enabled", True)
    status = "🟢" if enabled else "🔴"

    target = (a.get("target_role") or "?").strip()
    pos = ", ".join(_title_words(x) for x in (a.get("position_keywords") or []))
    loc = ", ".join(_title_words(x) for x in (a.get("location_keywords") or []))

    now_ts = int(time.time())
    expires_at = int(a.get("expires_at") or (int(a.get("created_at") or now_ts) + ALERT_TTL_SECONDS))
    left = expires_at - now_ts
    ttl_txt = _ttl_human_left(left)

    if not pos or not loc or target not in (ROLE_SEEKER, ROLE_EMPLOYER):
        return f"{status} <b>{target or '?'}</b> | 👤 (ошибка) | 📍 (ошибка) | ⏳ истекает через {ttl_txt}"

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
    """
    Возвращает True если УЖЕ доставляли (значит, слать НЕ надо),
    иначе помечает доставку и возвращает False.
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

    try:
        added = await r.sadd(key, ad_id)
        await r.expire(key, DELIVERED_TTL_SECONDS)
        return added == 0
    except Exception:
        logger.exception("alerts: delivered SADD failed")
        return False


# ----------------------------
# Bot blocked cache
# ----------------------------
async def _is_bot_blocked_user(user_id: int) -> bool:
    r = _get_redis()
    uid = int(user_id)

    if r is None:
        blocked = getattr(runtime, "ALERTS_BOT_BLOCKED_MEM", set()) or set()
        runtime.ALERTS_BOT_BLOCKED_MEM = blocked
        return uid in blocked

    try:
        return bool(await r.sismember(KEY_BOT_BLOCKED, uid))
    except Exception:
        logger.exception("alerts: sismember bot-blocked failed user_id=%s", uid)
        return False


async def _mark_bot_blocked_user(user_id: int) -> None:
    r = _get_redis()
    uid = int(user_id)

    if r is None:
        blocked = getattr(runtime, "ALERTS_BOT_BLOCKED_MEM", set()) or set()
        runtime.ALERTS_BOT_BLOCKED_MEM = blocked
        blocked.add(uid)
        return

    try:
        await r.sadd(KEY_BOT_BLOCKED, uid)
    except Exception:
        logger.exception("alerts: sadd bot-blocked failed user_id=%s", uid)


def _looks_like_bot_blocked_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return (
        "bot was blocked by the user" in s
        or "forbidden: bot was blocked by the user" in s
        or "user is deactivated" in s
    )


# ----------------------------
# Access gates
# ----------------------------
async def _is_project_blocked_user(user_id: int) -> bool:
    try:
        return bool(runtime.is_blocked(int(user_id)))
    except Exception:
        return False


async def _is_channel_subscribed(bot, user_id: int) -> tuple[bool, str, str]:
    """
    Толерантный адаптер под diagnostics._check_subscription():
    - (ok_sub, sub_line)
    - (ok_sub, sub_line, subscribe_url)
    - dict
    """
    diag = _diag_mod()

    ok_sub = False
    sub_line = "Подписка: нет (не подписан)"
    subscribe_url = ""

    try:
        res = await diag._check_subscription(bot, user_id)
    except Exception:
        logger.exception("alerts: _check_subscription failed user_id=%s", user_id)
        return False, sub_line, subscribe_url

    try:
        if isinstance(res, dict):
            ok_sub = bool(res.get("ok_sub", res.get("ok", res.get("subscribed", False))))
            sub_line = str(res.get("sub_line", res.get("text", sub_line)) or sub_line)
            subscribe_url = str(res.get("subscribe_url", res.get("url", "")) or "")
        elif isinstance(res, (list, tuple)):
            if len(res) >= 3:
                ok_sub = bool(res[0])
                sub_line = str(res[1] or sub_line)
                subscribe_url = str(res[2] or "")
            elif len(res) == 2:
                ok_sub = bool(res[0])
                sub_line = str(res[1] or sub_line)
            elif len(res) == 1:
                ok_sub = bool(res[0])
    except Exception:
        logger.exception("alerts: parse _check_subscription failed user_id=%s", user_id)

    return bool(ok_sub), str(sub_line), str(subscribe_url)


# ----------------------------
# Role mapping
# ----------------------------
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
        logger.warning("alerts: invalid role for ad_id=%s raw_role=%r", ad_id, ad_data.get("role"))
        return 0

    ad_position = (ad_data.get("position") or "").strip()
    ad_location = (ad_data.get("location") or "").strip()

    r = _get_redis()

    user_ids: list[int] = []
    if r is None:
        store = getattr(runtime, "ALERTS_MEM", {}) or {}
        for uid, alerts in store.items():
            if any(
                isinstance(a, dict)
                and a.get("enabled", True)
                and not _is_alert_expired(_ensure_alert_shape(a))
                and a.get("target_role") == ad_role
                for a in (alerts or [])
            ):
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
            logger.exception("alerts: smembers failed role=%s", ad_role)
            return 0

    if not user_ids:
        return 0

    sent_count = 0

    text = (
        "🔔 <b>Подходящее объявление</b>\n"
        f"🟢 <b>{ad_role}</b>\n"
        f"👤 <b>{ad_position}</b>\n"
        f"📍 <b>{ad_location}</b>"
    )

    kb = None
    if url:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔗 Открыть объявление", url=url)]]
        )

    for uid in user_ids:
        try:
            if await _is_project_blocked_user(uid):
                logger.info("alerts: skip user=%s ad_id=%s reason=project_blocked", uid, ad_id)
                continue

            if await _is_bot_blocked_user(uid):
                logger.info("alerts: skip user=%s ad_id=%s reason=bot_blocked_cached", uid, ad_id)
                continue

            ok_sub, _sub_line, _subscribe_url = await _is_channel_subscribed(bot, uid)
            if not ok_sub:
                logger.info("alerts: skip user=%s ad_id=%s reason=not_subscribed", uid, ad_id)
                continue

            alerts = await get_user_alerts(uid)
            if not alerts:
                continue

            for a in alerts:
                if not _alert_matches(ad_role, ad_position, ad_location, a):
                    continue

                alert_id = str(a.get("id") or "")
                if not alert_id:
                    continue

                already = await _delivered_check_and_mark(uid, alert_id, ad_id)
                if already:
                    logger.info(
                        "alerts: skip user=%s alert_id=%s ad_id=%s reason=dedup",
                        uid,
                        alert_id,
                        ad_id,
                    )
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
                    logger.info(
                        "alerts: sent user=%s alert_id=%s ad_id=%s",
                        uid,
                        alert_id,
                        ad_id,
                    )
                except Exception as exc:
                    if _looks_like_bot_blocked_error(exc):
                        await _mark_bot_blocked_user(uid)
                        logger.warning(
                            "alerts: mark bot-blocked user=%s alert_id=%s ad_id=%s",
                            uid,
                            alert_id,
                            ad_id,
                        )
                    else:
                        logger.exception(
                            "alerts: send failed user=%s alert_id=%s ad_id=%s",
                            uid,
                            alert_id,
                            ad_id,
                        )

        except Exception:
            logger.exception("alerts: pipeline failed user=%s ad_id=%s", uid, ad_id)
            continue

    return sent_count