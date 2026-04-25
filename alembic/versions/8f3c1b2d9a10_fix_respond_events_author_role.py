"""fix respond_events actor_role owner->author

Revision ID: 8f3c1b2d9a10
Revises: responds_statuses_v2
Create Date: 2026-03-09
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "8f3c1b2d9a10"
down_revision = "responds_statuses_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Снимаем старые constraints, если они есть
    op.execute("ALTER TABLE respond_events DROP CONSTRAINT IF EXISTS ck_revents_actor_role")
    op.execute("ALTER TABLE respond_events DROP CONSTRAINT IF EXISTS ck_revents_actor_user")
    op.execute("ALTER TABLE respond_events DROP CONSTRAINT IF EXISTS ck_respond_events_actor_role")
    op.execute("ALTER TABLE respond_events DROP CONSTRAINT IF EXISTS ck_respond_events_actor_user_id")

    # 2) Переводим старые данные owner -> author
    op.execute("UPDATE respond_events SET actor_role = 'author' WHERE actor_role = 'owner'")

    # 3) Ставим канонический CHECK на actor_role
    op.execute("""
        ALTER TABLE respond_events
        ADD CONSTRAINT ck_respond_events_actor_role
        CHECK (actor_role IN ('system','author','candidate'))
    """)

    # 4) Ставим канонический CHECK на actor_user_id
    op.execute("""
        ALTER TABLE respond_events
        ADD CONSTRAINT ck_respond_events_actor_user_id
        CHECK (
            (actor_role = 'system' AND actor_user_id IS NULL)
            OR
            (actor_role IN ('author','candidate') AND actor_user_id IS NOT NULL)
        )
    """)


def downgrade() -> None:
    # Откат только по структуре + author -> owner для совместимости со старой схемой
    op.execute("ALTER TABLE respond_events DROP CONSTRAINT IF EXISTS ck_respond_events_actor_role")
    op.execute("ALTER TABLE respond_events DROP CONSTRAINT IF EXISTS ck_respond_events_actor_user_id")
    op.execute("ALTER TABLE respond_events DROP CONSTRAINT IF EXISTS ck_revents_actor_role")
    op.execute("ALTER TABLE respond_events DROP CONSTRAINT IF EXISTS ck_revents_actor_user")

    op.execute("UPDATE respond_events SET actor_role = 'owner' WHERE actor_role = 'author'")

    op.execute("""
        ALTER TABLE respond_events
        ADD CONSTRAINT ck_revents_actor_role
        CHECK (actor_role IN ('system','owner','candidate'))
    """)

    op.execute("""
        ALTER TABLE respond_events
        ADD CONSTRAINT ck_revents_actor_user
        CHECK (
            (actor_role = 'system' AND actor_user_id IS NULL)
            OR
            (actor_role IN ('owner','candidate') AND actor_user_id IS NOT NULL)
        )
    """)
