"""add invited_at to responds

Revision ID: c9d4e7a1b2f3
Revises: b7a1c9d4e210
Create Date: 2026-03-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c9d4e7a1b2f3"
down_revision = "b7a1c9d4e210"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    cols = _columns("responds")
    if "invited_at" not in cols:
        op.add_column("responds", sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    cols = _columns("responds")
    if "invited_at" in cols:
        op.drop_column("responds", "invited_at")
