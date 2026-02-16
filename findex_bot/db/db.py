# findex_bot/db/db.py
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


ENV_PATH = "/Users/tmkd/Desktop/tmkd/FindexHub/.env"

# ✅ ЕДИНСТВЕННАЯ КАНОНИЧНАЯ БАЗА
CANON_DB_NAME = "findex"


@dataclass(frozen=True)
class DBConfig:
    url: str


def _mask_db_url(url: str) -> str:
    """
    Маскируем пароль в URL: postgresql://user:***@host:port/db
    """
    if not url:
        return url
    # user:pass@ -> user:***@
    return re.sub(r":([^:@/]+)@", r":***@", url)


def _extract_db_name(url: str) -> str:
    """
    Получаем имя базы из DATABASE_URL.
    Учитываем драйвер postgresql+asyncpg://...
    """
    if not url:
        return ""
    safe = url.strip()

    # urlparse не знает про postgresql+asyncpg как "scheme" нормально для path,
    # поэтому заменяем на postgresql:// один раз.
    if safe.startswith("postgresql+asyncpg://"):
        safe = "postgresql://" + safe[len("postgresql+asyncpg://") :]

    p = urlparse(safe)
    return (p.path or "").lstrip("/")


def _load_db_url() -> str:
    # ✅ .env лежит строго тут (зафиксировано), и мы ПЕРЕЗАТИРАЕМ окружение
    # чтобы никакой supervisord/export не мог подсунуть findexhub.
    load_dotenv(ENV_PATH, override=True)

    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Check /Users/tmkd/Desktop/tmkd/FindexHub/.env "
            "(make sure it contains DATABASE_URL=...)"
        )

    # ✅ ЖЁСТКИЙ ПРЕДОХРАНИТЕЛЬ: только findex
    db_name = _extract_db_name(url)
    if db_name != CANON_DB_NAME:
        raise RuntimeError(
            "[DB GUARD] Refusing to start: DATABASE_URL points to "
            f"'{db_name}', expected '{CANON_DB_NAME}'. "
            f"URL={_mask_db_url(url)!r}. "
            "Fix DATABASE_URL in .env or your process environment."
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