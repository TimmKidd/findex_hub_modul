# findex_bot/db/models.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Text, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped


class Base(DeclarativeBase):
    pass


class Ad(Base):
    __tablename__ = "ads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    author_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)         # employer | seeker
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)    # ЕДИНЫЙ ИСТОЧНИК ИСТИНЫ
    status: Mapped[str] = mapped_column(Text, nullable=False)       # draft | pending | published | rejected
    public_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
