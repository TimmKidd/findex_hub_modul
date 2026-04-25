# findex_bot/db/db.py
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def _resolve_env_path() -> str:
    env_path = (os.getenv("ENV_PATH") or "").strip()
    if env_path:
        return env_path

    project_root = Path(__file__).resolve().parents[2]
    return str(project_root / ".env")


ENV_PATH = _resolve_env_path()


@dataclass(frozen=True)
class DBConfig:
    url: str


def _mask_db_url(url: str) -> str:
    if not url:
        return url
    return re.sub(r":([^:@/]+)@", r":***@", url)


def _extract_db_name(url: str) -> str:
    if not url:
        return ""

    safe = url.strip()
    if safe.startswith("postgresql+asyncpg://"):
        safe = "postgresql://" + safe[len("postgresql+asyncpg://") :]

    p = urlparse(safe)
    return (p.path or "").lstrip("/")


def _load_db_url() -> str:
    # ВАЖНО:
    # В Docker / Compose переменные окружения уже должны быть переданы снаружи.
    # Поэтому .env можно подгружать только как fallback, но НЕ перетирать уже существующие env.
    load_dotenv(ENV_PATH, override=False)

    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError(
            f"DATABASE_URL is not set. Checked env file: {ENV_PATH!r}. "
            "Make sure it contains DATABASE_URL=..."
        )

    expected_db_name = (os.getenv("EXPECTED_DB_NAME") or "").strip()
    if expected_db_name:
        db_name = _extract_db_name(url)
        if db_name != expected_db_name:
            raise RuntimeError(
                "[DB GUARD] Refusing to start: DATABASE_URL points to "
                f"'{db_name}', expected '{expected_db_name}'. "
                f"URL={_mask_db_url(url)!r}. "
                "Fix DATABASE_URL / EXPECTED_DB_NAME in your environment."
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
    from sqlalchemy import text

    sm = get_sessionmaker()
    async with sm() as s:
        await s.execute(text("select 1"))
