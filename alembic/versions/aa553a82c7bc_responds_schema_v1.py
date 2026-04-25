"""responds schema v1

Revision ID: aa553a82c7bc
Revises: bd5eac593026
Create Date: 2026-02-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# --- ВАЖНО: подставь revision, который сгенерировал alembic ---
revision = "aa553a82c7bc"
down_revision = "bd5eac593026"
branch_labels = None
depends_on = None


RESPOND_STATUSES = (
    "new",
    "owner_replied",
    "owner_silent",
    "candidate_silent",
    "closed_by_owner",
    "closed_by_candidate",
    "closed_system",
)

RESPOND_MODES = ("pro", "fast")


def upgrade() -> None:
    # ----------------------------
    # responds
    # ----------------------------
    op.create_table(
        "responds",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),

        sa.Column("ad_id", sa.BigInteger(), sa.ForeignKey("ads.id", ondelete="CASCADE"), nullable=False),

        # ✅ владелец объявления = author_user_id (как в ads)
        sa.Column("author_user_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_user_id", sa.BigInteger(), nullable=False),

        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),

        sa.Column("candidate_message", sa.Text(), nullable=False),
        sa.Column("contacts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("structured", postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.Column("ad_public_url", sa.Text(), nullable=True),
        sa.Column("ad_role", sa.Text(), nullable=True),
        sa.Column("ad_payload_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        # ids карточек у сторон (для edit одной карточки)
        sa.Column("author_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("author_message_id", sa.BigInteger(), nullable=True),
        sa.Column("candidate_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_message_id", sa.BigInteger(), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("last_author_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_candidate_activity_at", sa.DateTime(timezone=True), nullable=True),

        sa.CheckConstraint(
            "mode IN ('pro','fast')",
            name="ck_responds_mode",
        ),
        sa.CheckConstraint(
            "status IN (" + ",".join([f"'{x}'" for x in RESPOND_STATUSES]) + ")",
            name="ck_responds_status",
        ),
    )

    # ✅ 1 отклик на 1 объявление (навсегда)
    op.create_unique_constraint(
        "uq_responds_ad_candidate",
        "responds",
        ["ad_id", "candidate_user_id"],
    )

    op.create_index("ix_responds_ad_id", "responds", ["ad_id"])
    op.create_index("ix_responds_author_status", "responds", ["author_user_id", "status"])
    op.create_index("ix_responds_candidate_status", "responds", ["candidate_user_id", "status"])
    op.create_index("ix_responds_created_at", "responds", ["created_at"])

    # ----------------------------
    # respond_events (полноценная лента)
    # ----------------------------
    op.create_table(
        "respond_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("respond_id", sa.BigInteger(), sa.ForeignKey("responds.id", ondelete="CASCADE"), nullable=False),

        sa.Column("actor_role", sa.Text(), nullable=False),          # system|author|candidate
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),  # null только у system

        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),

        # для дедупа системных событий/пингов
        sa.Column("dedup_key", sa.Text(), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),

        sa.CheckConstraint(
            "actor_role IN ('system','author','candidate')",
            name="ck_revents_actor_role",
        ),
        sa.CheckConstraint(
            "(actor_role = 'system' AND actor_user_id IS NULL) OR (actor_role <> 'system' AND actor_user_id IS NOT NULL)",
            name="ck_revents_actor_user",
        ),
    )

    op.create_index("ix_revents_respond_id_created_at", "respond_events", ["respond_id", "created_at"])
    op.create_index("ix_revents_actor_created_at", "respond_events", ["actor_role", "actor_user_id", "created_at"])
    op.create_index("ix_revents_type_created_at", "respond_events", ["event_type", "created_at"])

    # ✅ уникальный dedup_key только если он не NULL
    op.create_index(
        "uq_revents_dedup_key_not_null",
        "respond_events",
        ["dedup_key"],
        unique=True,
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )

    # ----------------------------
    # respond_daily_limits (Postgres = истина)
    # ----------------------------
    op.create_table(
        "respond_daily_limits",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "day", name="pk_respond_daily_limits"),
    )

    op.create_index("ix_respond_daily_limits_day", "respond_daily_limits", ["day"])


def downgrade() -> None:
    op.drop_index("ix_respond_daily_limits_day", table_name="respond_daily_limits")
    op.drop_table("respond_daily_limits")

    op.drop_index("uq_revents_dedup_key_not_null", table_name="respond_events")
    op.drop_index("ix_revents_type_created_at", table_name="respond_events")
    op.drop_index("ix_revents_actor_created_at", table_name="respond_events")
    op.drop_index("ix_revents_respond_id_created_at", table_name="respond_events")
    op.drop_table("respond_events")

    op.drop_index("ix_responds_created_at", table_name="responds")
    op.drop_index("ix_responds_candidate_status", table_name="responds")
    op.drop_index("ix_responds_author_status", table_name="responds")
    op.drop_index("ix_responds_ad_id", table_name="responds")
    op.drop_constraint("uq_responds_ad_candidate", "responds", type_="unique")
    op.drop_table("responds")