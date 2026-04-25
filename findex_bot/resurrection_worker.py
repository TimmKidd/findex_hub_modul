# findex_bot/resurrection_worker.py
from __future__ import annotations

import os
import asyncio
import logging
import contextlib
import html
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None  # type: ignore

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions

import findex_bot.runtime as runtime
from findex_bot.db.db import get_sessionmaker
from findex_bot.db.repo import RespondRepo
from findex_bot.db.models import Respond, Ad

logger = logging.getLogger(__name__)

# ----------------------------
# ENV bootstrap
# ----------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
if load_dotenv and os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)

# ----------------------------
# Settings
# ----------------------------
LEADER_KEY = os.getenv("RES_WORKER_LEADER_KEY", "resurrection:leader:findexhub")
LEADER_TTL_SEC = int(os.getenv("RES_WORKER_LEADER_TTL_SEC", "25"))
LEADER_RENEW_EVERY_SEC = int(os.getenv("RES_WORKER_LEADER_RENEW_SEC", "10"))

TICK_SEC = int(os.getenv("RES_WORKER_TICK_SEC", "10"))
BATCH_SIZE = int(os.getenv("RES_WORKER_BATCH_SIZE", "100"))

CB_RESUME = "respond_resume"
CB_NOOP = "resp_noop"

S_CLOSED_BY_OWNER = "CLOSED_BY_OWNER"
S_CLOSED_BY_CANDIDATE = "CLOSED_BY_CANDIDATE"
S_CLOSED_SYSTEM = "CLOSED_SYSTEM"
CLOSED_SET = {S_CLOSED_BY_OWNER, S_CLOSED_BY_CANDIDATE, S_CLOSED_SYSTEM}

_ME_USERNAME_CACHE: Optional[str] = None


# ----------------------------
# Helpers
# ----------------------------
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _h(v: Any) -> str:
    return html.escape(str(v or ""), quote=False)


def _get_redis() -> Any:
    """
    ВАЖНО:
    resurrection_worker.py — отдельный процесс.
    Он использует свой собственный Redis client и не должен трогать runtime.REDIS.
    """
    from redis.asyncio import Redis  # type: ignore

    dsn = os.getenv("REDIS_DSN") or os.getenv("REDIS_URL")
    if dsn:
        return Redis.from_url(dsn, decode_responses=True)

    host = os.getenv("REDIS_HOST", "redis")
    port = int(os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv("REDIS_DB", "0"))
    password = os.getenv("REDIS_PASSWORD") or None

    return Redis(host=host, port=port, db=db, password=password, decode_responses=True)


async def _try_become_leader(redis: Any, token: str) -> bool:
    return bool(await redis.set(LEADER_KEY, token, nx=True, ex=LEADER_TTL_SEC))


async def _renew_leader(redis: Any, token: str) -> bool:
    lua = r"""
    local key = KEYS[1]
    local token = ARGV[1]
    local ttl = tonumber(ARGV[2])
    local v = redis.call("GET", key)
    if not v then return 0 end
    if v ~= token then return 0 end
    redis.call("EXPIRE", key, ttl)
    return 1
    """
    try:
        res = await redis.eval(lua, 1, LEADER_KEY, token, str(LEADER_TTL_SEC))
    except TypeError:
        res = await redis.eval(lua, keys=[LEADER_KEY], args=[token, LEADER_TTL_SEC])
    return bool(int(res or 0))


def _bot_token() -> str:
    candidates = [
        getattr(runtime, "BOT_TOKEN", None),
        getattr(runtime, "TOKEN", None),
        os.getenv("BOT_TOKEN"),
        os.getenv("TELEGRAM_BOT_TOKEN"),
        os.getenv("TG_BOT_TOKEN"),
    ]
    for token in candidates:
        token = str(token or "").strip()
        if token:
            return token
    raise RuntimeError("Bot token not found. Set BOT_TOKEN / TELEGRAM_BOT_TOKEN")


def _resume_kb(respond_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Вернуться к отклику", callback_data=f"{CB_RESUME}:{int(respond_id)}")]
        ]
    )


def _closed_stub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔒 Отклик закрыт", callback_data=CB_NOOP)]
        ]
    )


def _channel_post_url_from_ad(ad: Ad | None, respond: Respond | None = None) -> Optional[str]:
    if respond is not None:
        try:
            u = str(getattr(respond, "ad_public_url", "") or "").strip()
            if u:
                return u
        except Exception:
            pass

        snap = getattr(respond, "ad_payload_snapshot", None)
        if isinstance(snap, dict):
            try:
                u2 = str(snap.get("public_url") or "").strip()
                if u2:
                    return u2
            except Exception:
                pass

    if ad is None:
        return None

    try:
        u = str(getattr(ad, "public_url", "") or "").strip()
        if u:
            return u
    except Exception:
        pass

    payload = getattr(ad, "payload", None)
    if isinstance(payload, dict):
        try:
            u2 = str(payload.get("public_url") or "").strip()
            if u2:
                return u2
        except Exception:
            pass

    username = (getattr(runtime, "CHANNEL_USERNAME", "") or "").strip().lstrip("@")
    if not username:
        return None

    payload = getattr(ad, "payload", None) or {}
    candidates = [
        payload.get("main_message_id"),
        payload.get("main_channel_message_id"),
        payload.get("channel_message_id"),
        payload.get("published_message_id"),
        payload.get("published_post_id"),
        payload.get("channel_post_id"),
    ]

    msg_id = None
    for v in candidates:
        try:
            if v is None:
                continue
            iv = int(v)
            if iv > 0:
                msg_id = iv
                break
        except Exception:
            continue

    if not msg_id:
        return None

    return f"https://t.me/{username}/{msg_id}"


async def _deeplink_url(bot: Bot, ad_id: int) -> Optional[str]:
    global _ME_USERNAME_CACHE

    username = (getattr(runtime, "BOT_USERNAME", "") or "").strip().lstrip("@")
    if not username:
        if _ME_USERNAME_CACHE:
            username = _ME_USERNAME_CACHE
        else:
            try:
                me = await bot.get_me()
                username = (getattr(me, "username", "") or "").strip().lstrip("@")
                if username:
                    _ME_USERNAME_CACHE = username
            except Exception:
                username = ""

    if not username:
        return None

    return f"https://t.me/{username}?start=resp_{int(ad_id)}"


def _ad_field_from_sources(ad: Ad | None, respond: Respond | None, key: str) -> str:
    if respond is not None:
        snap = getattr(respond, "ad_payload_snapshot", None)
        if isinstance(snap, dict):
            try:
                v = str(snap.get(key) or "").strip()
                if v:
                    return v
            except Exception:
                pass

    if ad is not None:
        payload = getattr(ad, "payload", None)
        if isinstance(payload, dict):
            try:
                v = str(payload.get(key) or "").strip()
                if v:
                    return v
            except Exception:
                pass

    return ""


async def _build_38h_close_text(bot: Bot, respond: Respond, ad: Ad | None) -> str:
    rid = int(getattr(respond, "id", 0) or 0)
    ad_id = int(getattr(respond, "ad_id", 0) or 0)

    vacancy_url = _channel_post_url_from_ad(ad, respond)
    deep_url = await _deeplink_url(bot, ad_id)

    title = _ad_field_from_sources(ad, respond, "title")
    location = _ad_field_from_sources(ad, respond, "location")
    salary = _ad_field_from_sources(ad, respond, "salary")

    bits = [x for x in (title, location, salary) if x]
    compact = " • ".join(_h(x) for x in bits) if bits else "—"

    vacancy_label = f"вакансии №{ad_id}"
    if vacancy_url:
        vacancy_part = f'<a href="{_h(vacancy_url)}">{_h(vacancy_label)}</a>'
    else:
        vacancy_part = _h(vacancy_label)

    if deep_url:
        new_respond_part = f'<a href="{_h(deep_url)}">новый отклик</a>'
    else:
        new_respond_part = "новый отклик"

    return (
        f"🔒 Отклик #{rid} по {vacancy_part}\n"
        f"{compact} — закрыт автоматически из-за долгой тишины.\n\n"
        f"Чтобы возобновить общение, потребуется {new_respond_part} "
        f"на вакансию, если она ещё актуальна."
    )


def _build_stage_text(respond_id: int, scenario: str, stage: str) -> str:
    rid = f"#{int(respond_id)}"

    if stage in {"30m", "4h", "12h"}:
        if scenario == "candidate_after_invite":
            return (
                f"👀 Работодатель уже пригласил тебя по отклику {rid}. "
                "Если вакансия ещё актуальна для тебя — вернись в диалог."
            )

        if scenario == "author_after_candidate":
            return (
                f"📩 Кандидат ждёт ответа по отклику {rid}. "
                "Если вакансия ещё актуальна для тебя — вернись в диалог."
            )

        if scenario in {"candidate_after_author", "dialog_silence"}:
            return (
                f"💬 Ваш диалог по отклику {rid} затих. "
                "Если вакансия ещё актуальна — можно быстро вернуться в переписку."
            )

    if stage == "36h":
        return (
            f"⏳ Диалог по отклику {rid} закроется через 2 часа из-за тишины. "
            "Если ты ещё заинтересован — открой карточку и ответь."
        )

    return ""


def _targets_for_stage(respond: Respond, scenario: str) -> list[tuple[str, int]]:
    if scenario == "candidate_after_invite":
        return [("candidate", int(respond.candidate_user_id))]

    if scenario == "author_after_candidate":
        return [("author", int(respond.author_user_id))]

    if scenario == "candidate_after_author":
        return [("candidate", int(respond.candidate_user_id))]

    if scenario == "dialog_silence":
        return [
            ("author", int(respond.author_user_id)),
            ("candidate", int(respond.candidate_user_id)),
        ]

    return []


async def _load_unhandled_resurrection_events(session: AsyncSession) -> list[dict[str, Any]]:
    q = text("""
        SELECT
            e.id,
            e.respond_id,
            e.payload,
            e.created_at
        FROM respond_events e
        WHERE e.actor_role = 'system'
          AND e.event_type = 'resurrection_stage'
          AND NOT EXISTS (
              SELECT 1
              FROM respond_events h
              WHERE h.dedup_key = ('res-handled:' || e.id::text)
          )
        ORDER BY e.created_at ASC
        LIMIT :lim
    """)
    res = await session.execute(q, {"lim": BATCH_SIZE})
    rows = res.fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        items.append({
            "event_id": int(row.id),
            "respond_id": int(row.respond_id),
            "payload": dict(payload),
            "created_at": row.created_at,
        })
    return items


async def _delete_tg_messages(bot: Bot, items: list[dict[str, Any]]) -> None:
    for item in items:
        chat_id = _safe_int(item.get("chat_id"))
        message_id = _safe_int(item.get("message_id"))
        if not chat_id or not message_id:
            continue
        with contextlib.suppress(Exception):
            await bot.delete_message(chat_id=chat_id, message_id=message_id)


async def _send_stage_message(
    bot: Bot,
    repo: RespondRepo,
    *,
    respond: Respond,
    ad: Ad | None,
    side: str,
    user_id: int,
    scenario: str,
    stage: str,
) -> bool:
    if stage == "38h_close":
        text = await _build_38h_close_text(bot, respond, ad)
    else:
        text = _build_stage_text(int(respond.id), scenario, stage)

    if not text:
        return False

    kb = _closed_stub_kb() if stage == "38h_close" else _resume_kb(int(respond.id))

    try:
        msg = await bot.send_message(
            chat_id=int(user_id),
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=False),
        )
    except Exception:
        logger.exception(
            "resurrection send failed respond_id=%s side=%s user_id=%s stage=%s scenario=%s",
            getattr(respond, "id", None),
            side,
            user_id,
            stage,
            scenario,
        )
        return False

    try:
        await repo.append_resurrection_message(
            respond_id=int(respond.id),
            chat_id=int(user_id),
            message_id=int(msg.message_id),
            side=str(side),
            stage=str(stage),
            scenario=str(scenario),
        )
    except Exception:
        logger.exception(
            "append_resurrection_message failed respond_id=%s side=%s stage=%s scenario=%s",
            getattr(respond, "id", None),
            side,
            stage,
            scenario,
        )

    return True


async def _refresh_closed_cards(bot: Bot, respond_id: int) -> None:
    """
    После системного закрытия обновляет карточки у обеих сторон.
    """
    async with get_sessionmaker()() as session:
        respond = await session.get(Respond, int(respond_id))
        if not respond:
            return

        ad = await session.get(Ad, int(getattr(respond, "ad_id", 0) or 0))
        if not ad:
            return

        try:
            from findex_bot.handlers.responds import _text_for, _kb_for  # type: ignore
        except Exception:
            logger.exception("failed to import responds card helpers")
            return

        with contextlib.suppress(Exception):
            if getattr(respond, "author_chat_id", None) and getattr(respond, "author_message_id", None):
                await bot.edit_message_text(
                    chat_id=int(respond.author_chat_id),
                    message_id=int(respond.author_message_id),
                    text=_text_for(ad, respond, view="author"),
                    reply_markup=_kb_for(respond, view="author"),
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )

        with contextlib.suppress(Exception):
            if getattr(respond, "candidate_chat_id", None) and getattr(respond, "candidate_message_id", None):
                await bot.edit_message_text(
                    chat_id=int(respond.candidate_chat_id),
                    message_id=int(respond.candidate_message_id),
                    text=_text_for(ad, respond, view="candidate"),
                    reply_markup=_kb_for(respond, view="candidate"),
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )


async def _close_respond_system(repo: RespondRepo, respond_id: int) -> None:
    respond = await repo.get_by_id(int(respond_id))
    if not respond:
        return

    if str(getattr(respond, "status", "")) in CLOSED_SET:
        return

    await repo.set_status(int(respond_id), S_CLOSED_SYSTEM, closed_at=_now_utc())

    with contextlib.suppress(Exception):
        await repo.add_event(
            respond_id=int(respond_id),
            actor_role="system",
            actor_user_id=None,
            event_type="respond_closed_system",
            payload={"reason": "resurrection_38h_close"},
            dedup_key=f"close-system:{int(respond_id)}:38h",
        )


async def _process_stage_event(bot: Bot, session: AsyncSession, item: dict[str, Any]) -> bool:
    repo = RespondRepo(session)

    event_id = int(item["event_id"])
    respond_id = int(item["respond_id"])
    payload = dict(item.get("payload") or {})

    scenario = str(payload.get("scenario") or "").strip()
    stage = str(payload.get("stage") or "").strip()

    if not scenario or not stage:
        logger.warning("skip malformed resurrection event event_id=%s respond_id=%s", event_id, respond_id)
        return False

    respond = await repo.get_by_id(int(respond_id))
    if not respond:
        with contextlib.suppress(Exception):
            await repo.add_event(
                respond_id=int(respond_id),
                actor_role="system",
                actor_user_id=None,
                event_type="resurrection_stage_handled",
                payload={"result": "respond_not_found", "event_id": event_id},
                dedup_key=f"res-handled:{event_id}",
            )
        return False

    if str(getattr(respond, "status", "")) in CLOSED_SET:
        with contextlib.suppress(Exception):
            await repo.add_event(
                respond_id=int(respond_id),
                actor_role="system",
                actor_user_id=None,
                event_type="resurrection_stage_handled",
                payload={"result": "already_closed", "event_id": event_id},
                dedup_key=f"res-handled:{event_id}",
            )
        return False

    ad = await session.get(Ad, int(getattr(respond, "ad_id", 0) or 0))

    targets = _targets_for_stage(respond, scenario)
    if not targets:
        with contextlib.suppress(Exception):
            await repo.add_event(
                respond_id=int(respond_id),
                actor_role="system",
                actor_user_id=None,
                event_type="resurrection_stage_handled",
                payload={"result": "no_targets", "event_id": event_id},
                dedup_key=f"res-handled:{event_id}",
            )
        return False

    if stage == "36h":
        for side, _user_id in targets:
            old_items = await repo.clear_resurrection_messages(
                respond_id=int(respond.id),
                side=str(side),
                scenario=str(scenario),
            )
            await _delete_tg_messages(bot, old_items)

    if stage == "38h_close":
        # Вариант A:
        # 1) чистим старые resurrection-сообщения,
        # 2) переводим отклик в CLOSED_SYSTEM,
        # 3) обновляем штатные карточки через responds.py,
        # 4) НЕ шлём отдельный системный текст пользователям.
        for side, _user_id in targets:
            old_items = await repo.clear_resurrection_messages(
                respond_id=int(respond.id),
                side=str(side),
                scenario=str(scenario),
            )
            await _delete_tg_messages(bot, old_items)

        await _close_respond_system(repo, int(respond.id))
        respond = await repo.get_by_id(int(respond.id))
        if not respond:
            return False

        with contextlib.suppress(Exception):
            await _refresh_closed_cards(bot, int(respond.id))

        with contextlib.suppress(Exception):
            await repo.add_event(
                respond_id=int(respond.id),
                actor_role="system",
                actor_user_id=None,
                event_type="resurrection_stage_handled",
                payload={
                    "event_id": event_id,
                    "scenario": scenario,
                    "stage": stage,
                    "sent_count": 0,
                    "result": "closed_without_notice",
                },
                dedup_key=f"res-handled:{event_id}",
            )

        return True

    sent_count = 0
    for side, user_id in targets:
        ok = await _send_stage_message(
            bot,
            repo,
            respond=respond,
            ad=ad,
            side=side,
            user_id=user_id,
            scenario=scenario,
            stage=stage,
        )
        if ok:
            sent_count += 1

    with contextlib.suppress(Exception):
        await repo.add_event(
            respond_id=int(respond.id),
            actor_role="system",
            actor_user_id=None,
            event_type="resurrection_stage_handled",
            payload={
                "event_id": event_id,
                "scenario": scenario,
                "stage": stage,
                "sent_count": sent_count,
            },
            dedup_key=f"res-handled:{event_id}",
        )

    return sent_count > 0


async def worker_tick(bot: Bot, session: AsyncSession) -> int:
    items = await _load_unhandled_resurrection_events(session)
    if not items:
        return 0

    n = 0
    for item in items:
        try:
            ok = await _process_stage_event(bot, session, item)
            if ok:
                n += 1
        except Exception:
            logger.exception(
                "resurrection worker failed event_id=%s respond_id=%s",
                item.get("event_id"),
                item.get("respond_id"),
            )
    return n


async def _leader_loop(token: str) -> None:
    redis = _get_redis()

    while True:
        became = await _try_become_leader(redis, token)
        if became:
            logger.info("✅ RESURRECTION worker leader acquired")
            break
        await asyncio.sleep(2)

    async def _renewer() -> None:
        while True:
            ok = await _renew_leader(redis, token)
            if not ok:
                logger.warning("⚠️ Resurrection worker lost leader lock, exiting")
                os._exit(2)
            await asyncio.sleep(LEADER_RENEW_EVERY_SEC)

    renew_task = asyncio.create_task(_renewer())

    bot = Bot(
        token=_bot_token(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    try:
        while True:
            total = 0
            async with get_sessionmaker()() as session:
                total += await worker_tick(bot, session)

            if total:
                logger.info("✅ resurrection tick done: %s handled events", total)

            await asyncio.sleep(TICK_SEC)

    finally:
        renew_task.cancel()
        with contextlib.suppress(Exception):
            await bot.session.close()
        try:
            if hasattr(redis, "aclose"):
                await redis.aclose()
            else:
                res = redis.close()
                if asyncio.iscoroutine(res):
                    await res
        except Exception:
            pass


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | resurrection_worker | %(message)s",
    )

    token = f"{os.getpid()}:{os.urandom(6).hex()}"
    logger.info("Starting resurrection worker token=%s", token)

    await _leader_loop(token)


if __name__ == "__main__":
    asyncio.run(main())