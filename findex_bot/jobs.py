# findex_bot/jobs.py
from __future__ import annotations

import os
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None  # type: ignore

import findex_bot.runtime as runtime
from findex_bot.db.db import get_sessionmaker
from findex_bot.db.repo import RespondRepo

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
LEADER_KEY = os.getenv("JOBS_LEADER_KEY", "jobs:leader:findexhub")
LEADER_TTL_SEC = int(os.getenv("JOBS_LEADER_TTL_SEC", "25"))
LEADER_RENEW_EVERY_SEC = int(os.getenv("JOBS_LEADER_RENEW_SEC", "10"))

TICK_SEC = int(os.getenv("JOBS_TICK_SEC", "10"))
BATCH_SIZE = int(os.getenv("JOBS_BATCH_SIZE", "200"))

# TTL
RESPOND_TTL_DAYS = int(os.getenv("RESPOND_TTL_DAYS", "30"))
AD_TTL_DAYS = int(os.getenv("AD_TTL_DAYS", "30"))

# Resurrection stages
RES_STAGE_30M_SEC = 30 * 60
RES_STAGE_4H_SEC = 4 * 60 * 60
RES_STAGE_12H_SEC = 12 * 60 * 60
RES_STAGE_36H_SEC = 36 * 60 * 60
RES_STAGE_38H_CLOSE_SEC = 38 * 60 * 60

VALID_RES_STAGES = {"30m", "4h", "12h", "36h", "38h_close"}
VALID_RES_SCENARIOS = {
    "candidate_after_invite",
    "author_after_candidate",
    "candidate_after_author",
    "dialog_silence",
}

# ----------------------------
# Statuses
# ----------------------------
S_INVITED = "INVITED"
S_IN_DIALOG = "IN_DIALOG"
S_CLOSED_BY_OWNER = "CLOSED_BY_OWNER"
S_CLOSED_BY_CANDIDATE = "CLOSED_BY_CANDIDATE"
S_CLOSED_SYSTEM = "CLOSED_SYSTEM"


# ----------------------------
# Redis leader lock
# ----------------------------
def _get_redis() -> Any:
    """
    ВАЖНО:
    jobs.py работает как отдельный процесс и использует свой собственный Redis client.
    Он не должен трогать runtime.REDIS, чтобы не смешивать ответственность с bot.py.
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


# ----------------------------
# DB helpers
# ----------------------------
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_valid_resurrection_payload(*, scenario: str, side: str, stage: str) -> bool:
    if scenario not in VALID_RES_SCENARIOS:
        return False
    if stage not in VALID_RES_STAGES:
        return False

    valid_sides = {"author", "candidate", "both"}
    if side not in valid_sides:
        return False

    if scenario == "candidate_after_invite" and side != "candidate":
        return False
    if scenario == "author_after_candidate" and side != "author":
        return False
    if scenario == "candidate_after_author" and side != "candidate":
        return False
    if scenario == "dialog_silence" and side != "both":
        return False

    return True


# ----------------------------
# Core jobs
# ----------------------------
async def job_autoclose_expired(session: AsyncSession) -> int:
    ttl_border = _now_utc() - timedelta(days=RESPOND_TTL_DAYS)

    q = text("""
        UPDATE responds
        SET status = :closed_system,
            closed_at = NOW()
        WHERE status NOT IN (:cbo, :cbc, :cs)
          AND created_at < :border
        RETURNING id
    """)
    res = await session.execute(q, {
        "border": ttl_border,
        "closed_system": S_CLOSED_SYSTEM,
        "cbo": S_CLOSED_BY_OWNER,
        "cbc": S_CLOSED_BY_CANDIDATE,
        "cs": S_CLOSED_SYSTEM,
    })
    rows = res.fetchall()
    await session.commit()
    return len(rows)


async def job_expire_ads(session: AsyncSession) -> int:
    """
    Автоматически помечает старые published объявления как expired в payload,
    не ломая текущую схему статусов ads.
    """
    border = _now_utc() - timedelta(days=AD_TTL_DAYS)

    q = text("""
        UPDATE ads
        SET payload = COALESCE(payload, '{}'::jsonb) || jsonb_build_object(
            'expired_auto', true,
            'expired_auto_at', NOW()::text
        )
        WHERE status = 'published'
          AND created_at < :border
          AND COALESCE((payload->>'expired_auto')::boolean, false) IS NOT TRUE
        RETURNING id
    """)
    res = await session.execute(q, {"border": border})
    rows = res.fetchall()
    await session.commit()
    return len(rows)


# ----------------------------
# Resurrection stages
# ----------------------------
def _pick_resurrection_stage(delta_sec: float) -> str | None:
    if delta_sec >= RES_STAGE_38H_CLOSE_SEC:
        return "38h_close"
    if delta_sec >= RES_STAGE_36H_SEC:
        return "36h"
    if delta_sec >= RES_STAGE_12H_SEC:
        return "12h"
    if delta_sec >= RES_STAGE_4H_SEC:
        return "4h"
    if delta_sec >= RES_STAGE_30M_SEC:
        return "30m"
    return None


async def job_resurrection_stages(session: AsyncSession) -> int:
    repo = RespondRepo(session)

    q = text("""
        SELECT
            id,
            status,
            invited_at,
            created_at,
            updated_at,
            last_author_activity_at,
            last_candidate_activity_at,
            author_user_id,
            candidate_user_id
        FROM responds
        WHERE status IN (:invited, :dialog)
        ORDER BY created_at ASC
        LIMIT :lim
    """)
    res = await session.execute(q, {
        "invited": S_INVITED,
        "dialog": S_IN_DIALOG,
        "lim": BATCH_SIZE,
    })
    rows = res.fetchall()

    now = _now_utc()
    n = 0

    for row in rows:
        respond_id = int(row.id)
        status = str(row.status or "")

        invited_at = row.invited_at
        created_at = row.created_at
        updated_at = row.updated_at
        last_author_activity_at = row.last_author_activity_at
        last_candidate_activity_at = row.last_candidate_activity_at

        if status == S_INVITED:
            anchor = invited_at or last_author_activity_at or updated_at or created_at
            scenario = "candidate_after_invite"
            side = "candidate"
        else:
            la = last_author_activity_at
            lc = last_candidate_activity_at

            if la and lc:
                if la >= lc:
                    anchor = la
                    scenario = "candidate_after_author"
                    side = "candidate"
                else:
                    anchor = lc
                    scenario = "author_after_candidate"
                    side = "author"
            else:
                anchor = la or lc or updated_at or created_at
                scenario = "dialog_silence"
                side = "both"

        if not anchor:
            continue

        delta_sec = (now - anchor).total_seconds()
        stage = _pick_resurrection_stage(delta_sec)
        if not stage:
            continue

        if not _is_valid_resurrection_payload(
            scenario=str(scenario),
            side=str(side),
            stage=str(stage),
        ):
            logger.error(
                "skip invalid resurrection payload respond_id=%s status=%s scenario=%s side=%s stage=%s",
                respond_id,
                status,
                scenario,
                side,
                stage,
            )
            continue

        dedup_key = f"resurrect:{respond_id}:{scenario}:{side}:{stage}"

        inserted = await repo.add_event_once(
            respond_id=respond_id,
            actor_role="system",
            actor_user_id=None,
            event_type="resurrection_stage",
            payload={
                "scenario": scenario,
                "side": side,
                "stage": stage,
                "anchor_at": anchor.isoformat() if hasattr(anchor, "isoformat") else None,
            },
            dedup_key=dedup_key,
        )
        if inserted:
            n += 1

    return n


# ----------------------------
# Main loop
# ----------------------------
async def _leader_loop(token: str) -> None:
    redis = _get_redis()

    while True:
        became = await _try_become_leader(redis, token)
        if became:
            logger.info("✅ JOBS leader acquired")
            break
        await asyncio.sleep(2)

    async def _renewer() -> None:
        while True:
            ok = await _renew_leader(redis, token)
            if not ok:
                logger.warning("⚠️ Lost leader lock, exiting worker")
                os._exit(2)
            await asyncio.sleep(LEADER_RENEW_EVERY_SEC)

    renew_task = asyncio.create_task(_renewer())

    try:
        async with get_sessionmaker()() as session:
            repo = RespondRepo(session)
            await repo.ensure_dedup_unique_index()

        while True:
            total = 0

            async with get_sessionmaker()() as session:
                try:
                    total += await job_autoclose_expired(session)
                except Exception:
                    logger.exception("job_autoclose_expired failed")

            async with get_sessionmaker()() as session:
                try:
                    total += await job_expire_ads(session)
                except Exception:
                    logger.exception("job_expire_ads failed")

            async with get_sessionmaker()() as session:
                try:
                    total += await job_resurrection_stages(session)
                except Exception:
                    logger.exception("job_resurrection_stages failed")

            if total:
                logger.info("✅ jobs tick done: %s actions", total)

            await asyncio.sleep(TICK_SEC)

    finally:
        renew_task.cancel()
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
        format="%(asctime)s | %(levelname)s | jobs | %(message)s",
    )

    token = f"{os.getpid()}:{os.urandom(6).hex()}"
    logger.info("Starting jobs worker token=%s", token)

    await _leader_loop(token)


if __name__ == "__main__":
    asyncio.run(main())