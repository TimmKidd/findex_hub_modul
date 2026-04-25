"""add unique constraint responds ad candidate

Revision ID: add_unique_respond_ad_candidate
Revises: 8f3c1b2d9a10
Create Date: 2026-03-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "add_unique_respond_ad_candidate"
down_revision = "8f3c1b2d9a10"
branch_labels = None
depends_on = None


def _constraint_exists(table_name: str, constraint_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for c in inspector.get_unique_constraints(table_name):
        if c.get("name") == constraint_name:
            return True
    return False


def upgrade() -> None:
    if _constraint_exists("responds", "uq_responds_ad_candidate"):
        return

    op.create_unique_constraint(
        "uq_responds_ad_candidate",
        "responds",
        ["ad_id", "candidate_user_id"],
    )


def downgrade() -> None:
    if not _constraint_exists("responds", "uq_responds_ad_candidate"):
        return

    op.drop_constraint(
        "uq_responds_ad_candidate",
        "responds",
        type_="unique",
    )
