"""drop duplicate deliveries ad_id index

Revision ID: 9e2b62c4b8d9
Revises: 12b90650a854
Create Date: 2026-01-27

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9e2b62c4b8d9"
down_revision: Union[str, Sequence[str], None] = "12b90650a854"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Безопасно: если индекса нет — просто ничего не сделает
    op.execute("DROP INDEX IF EXISTS public.ix_deliveries_ad;")


def downgrade() -> None:
    # Безопасно на любой версии Postgres: создаст только если индекса нет
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'i'
                  AND c.relname = 'ix_deliveries_ad'
                  AND n.nspname = 'public'
            ) THEN
                CREATE INDEX ix_deliveries_ad ON public.deliveries (ad_id);
            END IF;
        END $$;
        """
    )
