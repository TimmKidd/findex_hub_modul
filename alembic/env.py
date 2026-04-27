# alembic/env.py
from __future__ import annotations

import os
import asyncio
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# 1) Подгружаем .env из корня проекта
try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # .../FindexHub
ENV_PATH = PROJECT_ROOT / ".env"
if load_dotenv is not None:
    load_dotenv(ENV_PATH)

# 2) Alembic Config
config = context.config

# 3) Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 4) Metadata (ВАЖНО для autogenerate)
from findex_bot.db.models import Base  # noqa: E402

target_metadata = Base.metadata


def _get_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(f"DATABASE_URL is not set (expected in {ENV_PATH}).")
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode (async)."""
    connectable: AsyncEngine = create_async_engine(
        _get_url(),
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
