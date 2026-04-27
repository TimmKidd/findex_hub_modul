# findex_bot/handlers/system_admin.py
from __future__ import annotations

import os
import time
import socket
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    LinkPreviewOptions,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from sqlalchemy import text

import findex_bot.runtime as runtime
from findex_bot.db.db import get_sessionmaker

logger = logging.getLogger(__name__)
router = Router()

JOBS_LEADER_KEY = os.getenv("JOBS_LEADER_KEY", "jobs:leader:findexhub")
RES_LEADER_KEY = os.getenv("RES_WORKER_LEADER_KEY", "resurrection:leader:findexhub")
BOT_POLLING_LOCK_KEY = "findexhub:polling_lock"

AD_TTL_DAYS = int(os.getenv("AD_TTL_DAYS", "30"))
RESPOND_TTL_DAYS = int(os.getenv("RESPOND_TTL_DAYS", "30"))

RES_STAGE_30M_SEC = 30 * 60
RES_STAGE_4H_SEC = 4 * 60 * 60
RES_STAGE_12H_SEC = 12 * 60 * 60
RES_STAGE_36H_SEC = 36 * 60 * 60
RES_STAGE_38H_CLOSE_SEC = 38 * 60 * 60

CB_SYS_PING = "sys_ping"
CB_SYS_STATUS = "sys_status"
CB_SYS_JOBS = "sys_jobs"
CB_SYS_TOP = "sys_top"
CB_SYS_EVENTS = "sys_events"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _parse_int_set(raw: str | None) -> set[int]:
    out: set[int] = set()
    for part in str(raw or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except Exception:
            continue
    return out


def _admin_ids() -> set[int]:
    return _parse_int_set(os.getenv("ADMIN_ID"))


def _is_admin_user_id(user_id: int) -> bool:
    return int(user_id) in _admin_ids()


def _is_admin(message: Message) -> bool:
    uid = int(getattr(message.from_user, "id", 0) or 0)
    return _is_admin_user_id(uid)


def _is_admin_callback(callback: CallbackQuery) -> bool:
    uid = int(getattr(callback.from_user, "id", 0) or 0)
    return _is_admin_user_id(uid)


async def _deny_admin(message: Message) -> None:
    await message.answer(
        "⛔ Команда недоступна.",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def _guard_admin(message: Message) -> bool:
    if _is_admin(message):
        return True
    await _deny_admin(message)
    return False


async def _guard_admin_callback(callback: CallbackQuery) -> bool:
    if _is_admin_callback(callback):
        return True
    await callback.answer("⛔ Команда недоступна.", show_alert=True)
    return False


def _get_redis() -> Any:
    """
    system_admin.py работает внутри bot.py,
    поэтому здесь нормально использовать runtime.REDIS как основной Redis-клиент бота.
    """
    r = getattr(runtime, "REDIS", None)
    if r is not None:
        return r

    try:
        from redis.asyncio import Redis  # type: ignore
    except Exception:
        return None

    dsn = os.getenv("REDIS_DSN") or os.getenv("REDIS_URL")
    if dsn:
        r = Redis.from_url(dsn, decode_responses=True)
        runtime.REDIS = r
        return r

    host = os.getenv("REDIS_HOST", "redis")
    port = int(os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv("REDIS_DB", "0"))
    password = os.getenv("REDIS_PASSWORD") or None

    r = Redis(host=host, port=port, db=db, password=password, decode_responses=True)
    runtime.REDIS = r
    return r


def _fmt_ttl(value: int) -> str:
    if value == -2:
        return "нет ключа"
    if value == -1:
        return "без ttl"
    return str(value)


def _lock_health(ttl: int) -> str:
    if ttl <= 0:
        return "MISSING"
    if ttl <= 5:
        return "WARN"
    return "HEALTHY"


def _fmt_health(ttl: int) -> str:
    return f"{_lock_health(ttl)} • ttl={_fmt_ttl(ttl)}"


def _fmt_dt(value: Any) -> str:
    if not value:
        return "—"
    try:
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return str(value)
    except Exception:
        return str(value)


def _short(s: Any, n: int = 80) -> str:
    text_s = str(s or "")
    return text_s if len(text_s) <= n else text_s[: n - 1] + "…"


def system_help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏓 Пинг", callback_data=CB_SYS_PING)],
            [InlineKeyboardButton(text="🛠 Статус", callback_data=CB_SYS_STATUS)],
            [InlineKeyboardButton(text="⚙️ Задачи", callback_data=CB_SYS_JOBS)],
            [InlineKeyboardButton(text="📊 Сводка", callback_data=CB_SYS_TOP)],
            [InlineKeyboardButton(text="🧾 События", callback_data=CB_SYS_EVENTS)],
        ]
    )


async def _redis_info() -> dict[str, Any]:
    t0 = time.perf_counter()

    try:
        r = _get_redis()
        if r is None:
            raise RuntimeError("Redis client unavailable")

        pong = await r.ping()
        redis_ms = (time.perf_counter() - t0) * 1000

        jobs_leader = await r.get(JOBS_LEADER_KEY)
        res_leader = await r.get(RES_LEADER_KEY)
        bot_leader = await r.get(BOT_POLLING_LOCK_KEY)

        jobs_ttl = await r.ttl(JOBS_LEADER_KEY)
        res_ttl = await r.ttl(RES_LEADER_KEY)
        bot_ttl = await r.ttl(BOT_POLLING_LOCK_KEY)

        return {
            "ok": bool(pong),
            "redis_ms": round(redis_ms, 1),
            "jobs_leader": str(jobs_leader or "—"),
            "jobs_ttl": int(jobs_ttl),
            "jobs_health": _lock_health(int(jobs_ttl)),
            "res_leader": str(res_leader or "—"),
            "res_ttl": int(res_ttl),
            "res_health": _lock_health(int(res_ttl)),
            "bot_leader": str(bot_leader or "—"),
            "bot_ttl": int(bot_ttl),
            "bot_health": _lock_health(int(bot_ttl)),
            "error": "",
        }
    except Exception as e:
        redis_ms = (time.perf_counter() - t0) * 1000
        logger.exception("system_admin redis check failed")
        return {
            "ok": False,
            "redis_ms": round(redis_ms, 1),
            "jobs_leader": "—",
            "jobs_ttl": -2,
            "jobs_health": "MISSING",
            "res_leader": "—",
            "res_ttl": -2,
            "res_health": "MISSING",
            "bot_leader": "—",
            "bot_ttl": -2,
            "bot_health": "MISSING",
            "error": repr(e),
        }


async def _db_info() -> dict[str, Any]:
    t0 = time.perf_counter()

    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
            db_ms = (time.perf_counter() - t0) * 1000

            row = (
                await session.execute(text("""
                    SELECT
                        (SELECT COUNT(*) FROM ads) AS ads_total,
                        (SELECT COUNT(*) FROM ads WHERE status = 'published') AS ads_published,
                        (SELECT COUNT(*) FROM ads WHERE COALESCE((payload->>'expired_auto')::boolean, false) IS TRUE) AS ads_expired_auto,

                        (SELECT COUNT(*) FROM responds) AS responds_total,
                        (SELECT COUNT(*) FROM responds WHERE status = 'NEW') AS responds_new,
                        (SELECT COUNT(*) FROM responds WHERE status = 'INVITED') AS responds_invited,
                        (SELECT COUNT(*) FROM responds WHERE status = 'IN_DIALOG') AS responds_dialog,
                        (SELECT COUNT(*) FROM responds WHERE status = 'CLOSED_SYSTEM') AS responds_closed_system,

                        (SELECT COUNT(*) FROM respond_events) AS events_total,
                        (SELECT COUNT(*) FROM respond_events WHERE event_type = 'resurrection_stage') AS events_resurrection,
                        (SELECT COUNT(*) FROM respond_events WHERE event_type = 'resurrection_stage_handled') AS events_resurrection_handled,
                        (SELECT COUNT(*) FROM respond_events WHERE event_type = 'respond_closed_system') AS events_closed_system
                """))
            ).one()

        return {
            "ok": True,
            "db_ms": round(db_ms, 1),
            "ads_total": int(row.ads_total or 0),
            "ads_published": int(row.ads_published or 0),
            "ads_expired_auto": int(row.ads_expired_auto or 0),
            "responds_total": int(row.responds_total or 0),
            "responds_new": int(row.responds_new or 0),
            "responds_invited": int(row.responds_invited or 0),
            "responds_dialog": int(row.responds_dialog or 0),
            "responds_closed_system": int(row.responds_closed_system or 0),
            "events_total": int(row.events_total or 0),
            "events_resurrection": int(row.events_resurrection or 0),
            "events_resurrection_handled": int(row.events_resurrection_handled or 0),
            "events_closed_system": int(row.events_closed_system or 0),
            "error": "",
        }
    except Exception as e:
        db_ms = (time.perf_counter() - t0) * 1000
        logger.exception("system_admin db check failed")
        return {
            "ok": False,
            "db_ms": round(db_ms, 1),
            "ads_total": 0,
            "ads_published": 0,
            "ads_expired_auto": 0,
            "responds_total": 0,
            "responds_new": 0,
            "responds_invited": 0,
            "responds_dialog": 0,
            "responds_closed_system": 0,
            "events_total": 0,
            "events_resurrection": 0,
            "events_resurrection_handled": 0,
            "events_closed_system": 0,
            "error": repr(e),
        }


async def _jobs_snapshot() -> dict[str, Any]:
    now = _now_utc()

    try:
        async with get_sessionmaker()() as session:
            row = (
                await session.execute(
                    text("""
                        SELECT
                            (SELECT COUNT(*)
                             FROM respond_events e
                             WHERE e.actor_role = 'system'
                               AND e.event_type = 'resurrection_stage'
                               AND NOT EXISTS (
                                   SELECT 1
                                   FROM respond_events h
                                   WHERE h.dedup_key = ('res-handled:' || e.id::text)
                               )) AS resurrection_unhandled,

                            (SELECT COUNT(*)
                             FROM respond_events e
                             WHERE e.actor_role = 'system'
                               AND e.event_type = 'resurrection_stage'
                               AND e.created_at < NOW() - INTERVAL '10 minutes'
                               AND NOT EXISTS (
                                   SELECT 1
                                   FROM respond_events h
                                   WHERE h.dedup_key = ('res-handled:' || e.id::text)
                               )) AS resurrection_unhandled_old,

                            (SELECT COUNT(*)
                             FROM responds
                             WHERE status = 'INVITED'
                               AND COALESCE(invited_at, created_at) <= :cut30m) AS invited_30m_plus,

                            (SELECT COUNT(*)
                             FROM responds
                             WHERE status = 'INVITED'
                               AND COALESCE(invited_at, created_at) <= :cut4h) AS invited_4h_plus,

                            (SELECT COUNT(*)
                             FROM responds
                             WHERE status = 'INVITED'
                               AND COALESCE(invited_at, created_at) <= :cut12h) AS invited_12h_plus,

                            (SELECT COUNT(*)
                             FROM responds
                             WHERE status IN ('INVITED', 'IN_DIALOG')
                               AND COALESCE(
                                   invited_at,
                                   last_author_activity_at,
                                   last_candidate_activity_at,
                                   updated_at,
                                   created_at
                               ) <= :cut36h) AS res_36h_plus,

                            (SELECT COUNT(*)
                             FROM responds
                             WHERE status IN ('INVITED', 'IN_DIALOG')
                               AND COALESCE(
                                   invited_at,
                                   last_author_activity_at,
                                   last_candidate_activity_at,
                                   updated_at,
                                   created_at
                               ) <= :cut38h) AS res_38h_plus
                    """),
                    {
                        "cut30m": now - timedelta(seconds=RES_STAGE_30M_SEC),
                        "cut4h": now - timedelta(seconds=RES_STAGE_4H_SEC),
                        "cut12h": now - timedelta(seconds=RES_STAGE_12H_SEC),
                        "cut36h": now - timedelta(seconds=RES_STAGE_36H_SEC),
                        "cut38h": now - timedelta(seconds=RES_STAGE_38H_CLOSE_SEC),
                    },
                )
            ).one()

        resurrection_unhandled = int(row.resurrection_unhandled or 0)
        resurrection_unhandled_old = int(row.resurrection_unhandled_old or 0)

        return {
            "ok": True,
            "resurrection_unhandled": resurrection_unhandled,
            "resurrection_unhandled_old": resurrection_unhandled_old,
            "invited_30m_plus": int(row.invited_30m_plus or 0),
            "invited_4h_plus": int(row.invited_4h_plus or 0),
            "invited_12h_plus": int(row.invited_12h_plus or 0),
            "res_36h_plus": int(row.res_36h_plus or 0),
            "res_38h_plus": int(row.res_38h_plus or 0),
            "pipeline_stuck": resurrection_unhandled_old > 0,
            "error": "",
        }
    except Exception as e:
        logger.exception("system_admin jobs snapshot failed")
        return {
            "ok": False,
            "resurrection_unhandled": 0,
            "resurrection_unhandled_old": 0,
            "invited_30m_plus": 0,
            "invited_4h_plus": 0,
            "invited_12h_plus": 0,
            "res_36h_plus": 0,
            "res_38h_plus": 0,
            "pipeline_stuck": False,
            "error": repr(e),
        }


async def _recent_events(limit: int = 10) -> dict[str, Any]:
    try:
        async with get_sessionmaker()() as session:
            rows = (
                await session.execute(
                    text("""
                        SELECT
                            id,
                            respond_id,
                            event_type,
                            dedup_key,
                            payload,
                            created_at
                        FROM respond_events
                        WHERE actor_role = 'system'
                          AND event_type IN (
                              'resurrection_stage',
                              'resurrection_stage_handled',
                              'respond_closed_system'
                          )
                        ORDER BY created_at DESC
                        LIMIT :lim
                    """),
                    {"lim": limit},
                )
            ).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            payload = row.payload if isinstance(row.payload, dict) else {}
            items.append(
                {
                    "id": int(row.id),
                    "respond_id": int(row.respond_id),
                    "event_type": str(row.event_type or ""),
                    "dedup_key": str(row.dedup_key or ""),
                    "payload": dict(payload),
                    "created_at": row.created_at,
                }
            )

        return {"ok": True, "items": items, "error": ""}
    except Exception as e:
        logger.exception("system_admin recent events failed")
        return {"ok": False, "items": [], "error": repr(e)}


def _render_system_help_text() -> str:
    return (
        "⚙️ <b>Служебные команды</b>\n\n"
        "Нажми кнопку ниже — команда выполнится сразу.\n\n"
        "• <code>/пинг</code> — быстрая проверка бота, Redis и Postgres\n"
        "• <code>/статус</code> — общее состояние системы\n"
        "• <code>/задачи</code> — состояние фоновых процессов и pipeline\n"
        "• <code>/сводка</code> — краткая верхнеуровневая сводка\n"
        "• <code>/события</code> — последние системные события\n\n"
        "<b>Технические alias:</b>\n"
        "<code>/system_ping</code>\n"
        "<code>/system_status</code>\n"
        "<code>/system_jobs</code>\n"
        "<code>/system_top</code>\n"
        "<code>/system_events</code>"
    )


async def _render_system_ping_text() -> str:
    db = await _db_info()
    redis = await _redis_info()

    text_msg = (
        "🏓 <b>Пинг системы</b>\n\n"
        f"🖥️ Хост: <code>{_hostname()}</code>\n"
        f"🗄️ Postgres: <b>{'OK' if db['ok'] else 'ERR'}</b> • {db['db_ms']} ms\n"
        f"🧠 Redis: <b>{'OK' if redis['ok'] else 'ERR'}</b> • {redis['redis_ms']} ms\n"
        f"🤖 Bot polling: <code>{redis['bot_health']}</code> • ttl=<code>{_fmt_ttl(redis['bot_ttl'])}</code>\n"
        f"👷 Jobs: <code>{redis['jobs_health']}</code> • leader=<code>{redis['jobs_leader']}</code> • ttl=<code>{_fmt_ttl(redis['jobs_ttl'])}</code>\n"
        f"🧬 Resurrection: <code>{redis['res_health']}</code> • leader=<code>{redis['res_leader']}</code> • ttl=<code>{_fmt_ttl(redis['res_ttl'])}</code>\n"
    )

    if not db["ok"]:
        text_msg += f"\n\n⚠️ Ошибка БД: <code>{db['error']}</code>"
    if not redis["ok"]:
        text_msg += f"\n⚠️ Ошибка Redis: <code>{redis['error']}</code>"

    return text_msg


async def _render_system_status_text() -> str:
    db = await _db_info()
    redis = await _redis_info()

    text_msg = (
        "🛠️ <b>Состояние системы</b>\n\n"
        f"🕒 UTC: <code>{_now_utc().strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
        f"🖥️ Хост: <code>{_hostname()}</code>\n\n"

        f"<b>Инфраструктура</b>\n"
        f"• Postgres: <b>{'OK' if db['ok'] else 'ERR'}</b> • {db['db_ms']} ms\n"
        f"• Redis: <b>{'OK' if redis['ok'] else 'ERR'}</b> • {redis['redis_ms']} ms\n"
        f"• Bot polling: <code>{_fmt_health(redis['bot_ttl'])}</code>\n"
        f"• Jobs: <code>{redis['jobs_health']}</code> • leader=<code>{redis['jobs_leader']}</code> • ttl=<code>{_fmt_ttl(redis['jobs_ttl'])}</code>\n"
        f"• Resurrection: <code>{redis['res_health']}</code> • leader=<code>{redis['res_leader']}</code> • ttl=<code>{_fmt_ttl(redis['res_ttl'])}</code>\n\n"

        f"<b>TTL</b>\n"
        f"• Ads TTL: <code>{AD_TTL_DAYS}</code> дней\n"
        f"• Respond TTL: <code>{RESPOND_TTL_DAYS}</code> дней\n\n"

        f"<b>Объявления</b>\n"
        f"• всего: <code>{db['ads_total']}</code>\n"
        f"• опубликовано: <code>{db['ads_published']}</code>\n"
        f"• авто-закрыто: <code>{db['ads_expired_auto']}</code>\n\n"

        f"<b>Отклики</b>\n"
        f"• всего: <code>{db['responds_total']}</code>\n"
        f"• NEW: <code>{db['responds_new']}</code>\n"
        f"• INVITED: <code>{db['responds_invited']}</code>\n"
        f"• IN_DIALOG: <code>{db['responds_dialog']}</code>\n"
        f"• CLOSED_SYSTEM: <code>{db['responds_closed_system']}</code>\n\n"

        f"<b>События</b>\n"
        f"• всего: <code>{db['events_total']}</code>\n"
        f"• resurrection_stage: <code>{db['events_resurrection']}</code>\n"
        f"• resurrection_stage_handled: <code>{db['events_resurrection_handled']}</code>\n"
        f"• respond_closed_system: <code>{db['events_closed_system']}</code>\n"
    )

    if not db["ok"]:
        text_msg += f"\n⚠️ Ошибка БД: <code>{db['error']}</code>"
    if not redis["ok"]:
        text_msg += f"\n⚠️ Ошибка Redis: <code>{redis['error']}</code>"

    return text_msg


async def _render_system_jobs_text() -> str:
    redis = await _redis_info()
    jobs = await _jobs_snapshot()
    db = await _db_info()

    pipeline_line = (
        "⚠️ <b>PIPELINE ЗАВИС</b>\n"
        if jobs["pipeline_stuck"]
        else "✅ <b>PIPELINE В НОРМЕ</b>\n"
    )

    text_msg = (
        "⚙️ <b>Системные задачи</b>\n\n"
        f"{pipeline_line}\n"
        f"🕒 UTC: <code>{_now_utc().strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
        f"🖥️ Хост: <code>{_hostname()}</code>\n\n"

        f"<b>Локи</b>\n"
        f"• Bot polling: <code>{_fmt_health(redis['bot_ttl'])}</code>\n"
        f"• Jobs: <code>{redis['jobs_health']}</code> • leader=<code>{redis['jobs_leader']}</code> • ttl=<code>{_fmt_ttl(redis['jobs_ttl'])}</code>\n"
        f"• Resurrection: <code>{redis['res_health']}</code> • leader=<code>{redis['res_leader']}</code> • ttl=<code>{_fmt_ttl(redis['res_ttl'])}</code>\n\n"

        f"<b>TTL-конфиг</b>\n"
        f"• Ads TTL: <code>{AD_TTL_DAYS}</code> дней\n"
        f"• Respond TTL: <code>{RESPOND_TTL_DAYS}</code> дней\n\n"

        f"<b>Очереди / стадии</b>\n"
        f"• необработанные resurrection events: <code>{jobs['resurrection_unhandled']}</code>\n"
        f"• необработанные >10м: <code>{jobs['resurrection_unhandled_old']}</code>\n"
        f"• invited >=30м: <code>{jobs['invited_30m_plus']}</code>\n"
        f"• invited >=4ч: <code>{jobs['invited_4h_plus']}</code>\n"
        f"• invited >=12ч: <code>{jobs['invited_12h_plus']}</code>\n"
        f"• respond anchors >=36ч: <code>{jobs['res_36h_plus']}</code>\n"
        f"• respond anchors >=38ч: <code>{jobs['res_38h_plus']}</code>\n\n"

        f"<b>Итоги</b>\n"
        f"• auto-expired объявлений: <code>{db['ads_expired_auto']}</code>\n"
        f"• closed_system откликов: <code>{db['responds_closed_system']}</code>\n"
        f"• resurrection_stage событий: <code>{db['events_resurrection']}</code>\n"
        f"• resurrection_stage_handled: <code>{db['events_resurrection_handled']}</code>\n"
        f"• respond_closed_system событий: <code>{db['events_closed_system']}</code>\n"
    )

    if not redis["ok"]:
        text_msg += f"\n⚠️ Ошибка Redis: <code>{redis['error']}</code>"
    if not jobs["ok"]:
        text_msg += f"\n⚠️ Ошибка jobs snapshot: <code>{jobs['error']}</code>"
    if not db["ok"]:
        text_msg += f"\n⚠️ Ошибка БД: <code>{db['error']}</code>"

    return text_msg


async def _render_system_top_text() -> str:
    db = await _db_info()
    jobs = await _jobs_snapshot()

    top_header = "⚠️ <b>PIPELINE ЗАВИС</b>\n\n" if jobs["pipeline_stuck"] else ""

    text_msg = (
        "📊 <b>Системная сводка</b>\n\n"
        f"{top_header}"
        f"🖥️ Хост: <code>{_hostname()}</code>\n"
        f"🕒 UTC: <code>{_now_utc().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"

        f"<b>Объявления</b>\n"
        f"• опубликовано: <code>{db['ads_published']}</code>\n"
        f"• авто-закрыто: <code>{db['ads_expired_auto']}</code>\n\n"

        f"<b>Отклики</b>\n"
        f"• NEW: <code>{db['responds_new']}</code>\n"
        f"• INVITED: <code>{db['responds_invited']}</code>\n"
        f"• IN_DIALOG: <code>{db['responds_dialog']}</code>\n"
        f"• CLOSED_SYSTEM: <code>{db['responds_closed_system']}</code>\n\n"

        f"<b>Resurrection pipeline</b>\n"
        f"• необработанные события: <code>{jobs['resurrection_unhandled']}</code>\n"
        f"• необработанные >10м: <code>{jobs['resurrection_unhandled_old']}</code>\n"
        f"• invited >=30м: <code>{jobs['invited_30m_plus']}</code>\n"
        f"• invited >=4ч: <code>{jobs['invited_4h_plus']}</code>\n"
        f"• invited >=12ч: <code>{jobs['invited_12h_plus']}</code>\n"
        f"• anchors >=36ч: <code>{jobs['res_36h_plus']}</code>\n"
        f"• anchors >=38ч: <code>{jobs['res_38h_plus']}</code>\n"
    )

    if not db["ok"]:
        text_msg += f"\n\n⚠️ Ошибка БД: <code>{db['error']}</code>"
    if not jobs["ok"]:
        text_msg += f"\n⚠️ Ошибка jobs snapshot: <code>{jobs['error']}</code>"

    return text_msg


async def _render_system_events_text() -> str:
    data = await _recent_events(limit=10)

    if not data["ok"]:
        return (
            "🧾 <b>Системные события</b>\n\n"
            f"⚠️ Ошибка: <code>{data['error']}</code>"
        )

    items: list[dict[str, Any]] = data["items"]
    if not items:
        return (
            "🧾 <b>Системные события</b>\n\n"
            "Нет системных событий."
        )

    lines = ["🧾 <b>Системные события</b>\n"]

    for item in items:
        payload = item.get("payload") or {}
        stage = payload.get("stage")
        scenario = payload.get("scenario")
        result = payload.get("result")
        sent_count = payload.get("sent_count")

        extra_parts = []
        if stage:
            extra_parts.append(f"stage={stage}")
        if scenario:
            extra_parts.append(f"scenario={scenario}")
        if result:
            extra_parts.append(f"result={result}")
        if sent_count is not None:
            extra_parts.append(f"sent={sent_count}")

        extra = ", ".join(extra_parts) if extra_parts else _short(item.get("dedup_key") or "—", 60)

        lines.append(
            f"• <code>{item['created_at']}</code>\n"
            f"  #{item['id']} | отклик=<code>{item['respond_id']}</code>\n"
            f"  тип=<code>{item['event_type']}</code>\n"
            f"  {extra}"
        )

    return "\n\n".join(lines)


async def _send_system_text(message: Message, text_msg: str, *, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    await message.answer(
        text_msg,
        reply_markup=reply_markup,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def _send_system_text_from_callback(
    callback: CallbackQuery,
    text_msg: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if callback.message is None:
        return
    await callback.message.answer(
        text_msg,
        reply_markup=reply_markup,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.message(Command(commands=["system", "система"]))
async def system_help(message: Message) -> None:
    if not await _guard_admin(message):
        return

    await _send_system_text(
        message,
        _render_system_help_text(),
        reply_markup=system_help_kb(),
    )


@router.message(Command(commands=["system_ping", "пинг"]))
async def system_ping(message: Message) -> None:
    if not await _guard_admin(message):
        return

    await _send_system_text(message, await _render_system_ping_text())


@router.message(Command(commands=["system_status", "статус"]))
async def system_status(message: Message) -> None:
    if not await _guard_admin(message):
        return

    await _send_system_text(message, await _render_system_status_text())


@router.message(Command(commands=["system_jobs", "задачи"]))
async def system_jobs(message: Message) -> None:
    if not await _guard_admin(message):
        return

    await _send_system_text(message, await _render_system_jobs_text())


@router.message(Command(commands=["system_top", "сводка"]))
async def system_top(message: Message) -> None:
    if not await _guard_admin(message):
        return

    await _send_system_text(message, await _render_system_top_text())


@router.message(Command(commands=["system_events", "события"]))
async def system_events(message: Message) -> None:
    if not await _guard_admin(message):
        return

    await _send_system_text(message, await _render_system_events_text())


@router.callback_query(F.data == CB_SYS_PING)
async def system_ping_cb(callback: CallbackQuery) -> None:
    if not await _guard_admin_callback(callback):
        return
    await callback.answer()
    await _send_system_text_from_callback(callback, await _render_system_ping_text())


@router.callback_query(F.data == CB_SYS_STATUS)
async def system_status_cb(callback: CallbackQuery) -> None:
    if not await _guard_admin_callback(callback):
        return
    await callback.answer()
    await _send_system_text_from_callback(callback, await _render_system_status_text())


@router.callback_query(F.data == CB_SYS_JOBS)
async def system_jobs_cb(callback: CallbackQuery) -> None:
    if not await _guard_admin_callback(callback):
        return
    await callback.answer()
    await _send_system_text_from_callback(callback, await _render_system_jobs_text())


@router.callback_query(F.data == CB_SYS_TOP)
async def system_top_cb(callback: CallbackQuery) -> None:
    if not await _guard_admin_callback(callback):
        return
    await callback.answer()
    await _send_system_text_from_callback(callback, await _render_system_top_text())


@router.callback_query(F.data == CB_SYS_EVENTS)
async def system_events_cb(callback: CallbackQuery) -> None:
    if not await _guard_admin_callback(callback):
        return
    await callback.answer()
    await _send_system_text_from_callback(callback, await _render_system_events_text())