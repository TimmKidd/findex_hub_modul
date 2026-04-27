# findex_bot/db/models.py
from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import (
    BigInteger,
    Integer,
    Text,
    Date,
    DateTime,
    ForeignKey,
    func,
    Index,
    CheckConstraint,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, relationship


class Base(DeclarativeBase):
    pass


# ----------------------------
# Ads
# ----------------------------
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

    __table_args__ = (
        CheckConstraint("role IN ('employer','seeker')", name="ck_ads_role"),
        CheckConstraint("status IN ('draft','pending','published','rejected')", name="ck_ads_status"),
        Index("ix_ads_author_role_status", "author_user_id", "role", "status"),
        Index("ix_ads_status_created_at", "status", "created_at"),
    )


# ----------------------------
# Candidate profiles
# ----------------------------
class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_last_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    citizenship: Mapped[str] = mapped_column(Text, nullable=False)
    experience: Mapped[str] = mapped_column(Text, nullable=False)

    resume_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_file_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    has_resume: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))

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
    last_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("age >= 14 AND age <= 80", name="ck_candidate_profiles_age"),
        Index("ix_candidate_profiles_username", "username"),
        Index("ix_candidate_profiles_citizenship", "citizenship"),
        Index("ix_candidate_profiles_age", "age"),
        Index("ix_candidate_profiles_has_resume", "has_resume"),
        Index("ix_candidate_profiles_last_responded_at", "last_responded_at"),
    )


# ----------------------------
# Responds feature models
# ----------------------------
class Respond(Base):
    __tablename__ = "responds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    ad_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ads.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ✅ владелец объявления = author_user_id (как в ads)
    author_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    candidate_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # pro | fast (в текущей UX-логике используем pro как "анкета", fast можно оставить под будущее)
    mode: Mapped[str] = mapped_column(Text, nullable=False)

    # ✅ NEW | IN_DIALOG | INVITED | CLOSED_BY_OWNER | CLOSED_BY_CANDIDATE | CLOSED_SYSTEM
    status: Mapped[str] = mapped_column(Text, nullable=False)

    # историческое поле (может использоваться как заголовок/первичное сообщение)
    candidate_message: Mapped[str] = mapped_column(Text, nullable=False)

    # контакты: jsonb
    contacts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # structured payload:
    # - thread: list сообщений (переписка)
    # - collapsed: {"author": bool, "candidate": bool}
    # - candidate_username: str
    # - candidate_profile: {"name","age","citizenship","experience","resume_link","resume_file_id","resume_file_name"}
    # - resurrection_messages: list[{chat_id, message_id, side, stage, created_at}]
    # - cand_invite_notice: {chat_id, message_id}
    structured: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # мета объявления на момент отклика
    ad_public_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    ad_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    ad_payload_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ids карточек у сторон (для edit одной карточки)
    author_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    author_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    candidate_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    candidate_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

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

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # активности (обновляем только на сообщения)
    last_author_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_candidate_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # NEW / viewed-notified / invited / pings
    owner_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ping12_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ping36_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ping_owner24_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # relationships
    events: Mapped[list["RespondEvent"]] = relationship(
        "RespondEvent",
        back_populates="respond",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("mode IN ('pro','fast')", name="ck_responds_mode"),
        CheckConstraint(
            "status IN ('NEW','IN_DIALOG','INVITED','CLOSED_BY_OWNER','CLOSED_BY_CANDIDATE','CLOSED_SYSTEM')",
            name="ck_responds_status",
        ),

        # ✅ железно: 1 отклик на объявление от кандидата
        UniqueConstraint("ad_id", "candidate_user_id", name="uq_responds_ad_candidate"),

        # базовые индексы
        Index("ix_responds_ad_id", "ad_id"),
        Index("ix_responds_author_user_id", "author_user_id"),
        Index("ix_responds_candidate_user_id", "candidate_user_id"),
        Index("ix_responds_status_created_at", "status", "created_at"),

        # индексы под jobs / resurrection_worker
        Index("ix_responds_invited_at", "invited_at"),
        Index("ix_responds_ping12_sent_at", "ping12_sent_at"),
        Index("ix_responds_ping36_sent_at", "ping36_sent_at"),
        Index("ix_responds_ping_owner24_sent_at", "ping_owner24_sent_at"),

        # частые выборки по активности
        Index("ix_responds_last_activity", "last_author_activity_at", "last_candidate_activity_at"),
    )


class RespondEvent(Base):
    __tablename__ = "respond_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    respond_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("responds.id", ondelete="CASCADE"),
        nullable=False,
    )

    # system | author | candidate
    actor_role: Mapped[str] = mapped_column(Text, nullable=False)

    # null только у system
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    event_type: Mapped[str] = mapped_column(Text, nullable=False)

    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    # ✅ для транзакционного дедупа (см repo.add_event)
    dedup_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    respond: Mapped["Respond"] = relationship("Respond", back_populates="events")

    __table_args__ = (
        CheckConstraint("actor_role IN ('system','author','candidate')", name="ck_respond_events_actor_role"),
        CheckConstraint(
            "(actor_role = 'system' AND actor_user_id IS NULL) OR "
            "(actor_role IN ('author','candidate') AND actor_user_id IS NOT NULL)",
            name="ck_respond_events_actor_user_id",
        ),

        Index("ix_respond_events_respond_id", "respond_id"),
        Index("ix_respond_events_created_at", "created_at"),

        # ✅ partial UNIQUE на dedup_key (для ON CONFLICT DO NOTHING)
        Index(
            "ux_respond_events_dedup_key",
            "dedup_key",
            unique=True,
            postgresql_where=text("dedup_key IS NOT NULL"),
        ),
    )


class RespondDailyLimit(Base):
    __tablename__ = "respond_daily_limits"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)

    count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_respond_daily_limits_day", "day"),
    )