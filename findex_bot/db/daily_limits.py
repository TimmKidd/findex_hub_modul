# findex_bot/db/daily_limits.py
from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS daily_pub_limits (
    user_id    BIGINT NOT NULL,
    day_utc    DATE   NOT NULL,
    cnt        INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, day_utc)
);
"""

UPSERT_INC_SQL = """
INSERT INTO daily_pub_limits (user_id, day_utc, cnt)
VALUES (:user_id, :day_utc, 1)
ON CONFLICT (user_id, day_utc)
DO UPDATE SET
    cnt = daily_pub_limits.cnt + 1,
    updated_at = NOW()
RETURNING cnt;
"""

GET_SQL = """
SELECT cnt
FROM daily_pub_limits
WHERE user_id = :user_id AND day_utc = :day_utc
LIMIT 1;
"""


def utc_today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


async def ensure_table(session: AsyncSession) -> None:
    # Таблица создаётся лениво. Commit делает вызывающая сторона.
    await session.execute(text(TABLE_SQL))


async def get_count(session: AsyncSession, user_id: int, day_utc: Optional[datetime.date] = None) -> int:
    day = day_utc or utc_today()
    await ensure_table(session)
    res = await session.execute(text(GET_SQL), {"user_id": int(user_id), "day_utc": day})
    row = res.first()
    if not row:
        return 0
    try:
        return int(row[0] or 0)
    except Exception:
        return 0


async def inc_and_get(session: AsyncSession, user_id: int, day_utc: Optional[datetime.date] = None) -> int:
    day = day_utc or utc_today()
    await ensure_table(session)
    res = await session.execute(text(UPSERT_INC_SQL), {"user_id": int(user_id), "day_utc": day})
    row = res.first()
    if not row:
        return 0
    try:
        return int(row[0] or 0)
    except Exception:
        return 0