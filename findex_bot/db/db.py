# findex_bot/db/db.py
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


ENV_PATH = "/Users/tmkd/Desktop/tmkd/FindexHub/.env"


@dataclass(frozen=True)
class DBConfig:
    url: str


def _load_db_url() -> str:
    # .env лежит строго тут (зафиксировано)
    load_dotenv(ENV_PATH, override=False)

    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Check /Users/tmkd/Desktop/tmkd/FindexHub/.env "
            "(and make sure it contains DATABASE_URL=...)"
        )
    return url


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        url = _load_db_url()
        _engine = create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
        )
        _sessionmaker = async_sessionmaker(
            bind=_engine,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def ping_db() -> None:
    # быстрый тест соединения из кода
    from sqlalchemy import text

    sm = get_sessionmaker()
    async with sm() as s:
        await s.execute(text("select 1"))
