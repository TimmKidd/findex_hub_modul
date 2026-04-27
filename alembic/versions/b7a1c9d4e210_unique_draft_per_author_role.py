"""unique draft per author role

Revision ID: b7a1c9d4e210
Revises: b7c1d9e2f3a4
Create Date: 2026-03-28 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "b7a1c9d4e210"
down_revision = "b7c1d9e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_ads_one_draft_per_author_role
        ON ads (author_user_id, role)
        WHERE status = 'draft'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ux_ads_one_draft_per_author_role
        """
    )
