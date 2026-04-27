"""rename responds owner->author

Revision ID: da95b3649c64
Revises: aa553a82c7bc
Create Date: 2026-03-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "da95b3649c64"
down_revision = "aa553a82c7bc"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    cols = _columns("responds")

    # legacy-case: старая база ещё с owner_user_id
    if "owner_user_id" in cols and "author_user_id" not in cols:
        op.alter_column("responds", "owner_user_id", new_column_name="author_user_id")
        return

    # эталонный и правильный сценарий
    if "author_user_id" in cols:
        return

    raise RuntimeError(
        "Migration da95b3649c64: expected 'author_user_id' "
        "or legacy 'owner_user_id' in table 'responds', but found neither."
    )


def downgrade() -> None:
    cols = _columns("responds")

    if "author_user_id" in cols and "owner_user_id" not in cols:
        op.alter_column("responds", "author_user_id", new_column_name="owner_user_id")
        return

    if "owner_user_id" in cols:
        return

    raise RuntimeError(
        "Downgrade da95b3649c64: neither 'author_user_id' nor legacy "
        "'owner_user_id' exists in table 'responds'."
    )
