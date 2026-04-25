"""add candidate profiles

Revision ID: b7c1d9e2f3a4
Revises: add_unique_respond_ad_candidate
Create Date: 2026-03-20 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7c1d9e2f3a4"
down_revision = "add_unique_respond_ad_candidate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_profiles",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("telegram_first_name", sa.Text(), nullable=True),
        sa.Column("telegram_last_name", sa.Text(), nullable=True),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("citizenship", sa.Text(), nullable=False),
        sa.Column("experience", sa.Text(), nullable=False),
        sa.Column("resume_link", sa.Text(), nullable=True),
        sa.Column("resume_file_id", sa.Text(), nullable=True),
        sa.Column("resume_file_name", sa.Text(), nullable=True),
        sa.Column("has_resume", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("user_id"),
        sa.CheckConstraint("age >= 14 AND age <= 80", name="ck_candidate_profiles_age"),
    )

    op.create_index("ix_candidate_profiles_username", "candidate_profiles", ["username"], unique=False)
    op.create_index("ix_candidate_profiles_citizenship", "candidate_profiles", ["citizenship"], unique=False)
    op.create_index("ix_candidate_profiles_age", "candidate_profiles", ["age"], unique=False)
    op.create_index("ix_candidate_profiles_has_resume", "candidate_profiles", ["has_resume"], unique=False)
    op.create_index("ix_candidate_profiles_last_responded_at", "candidate_profiles", ["last_responded_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_candidate_profiles_last_responded_at", table_name="candidate_profiles")
    op.drop_index("ix_candidate_profiles_has_resume", table_name="candidate_profiles")
    op.drop_index("ix_candidate_profiles_age", table_name="candidate_profiles")
    op.drop_index("ix_candidate_profiles_citizenship", table_name="candidate_profiles")
    op.drop_index("ix_candidate_profiles_username", table_name="candidate_profiles")
    op.drop_table("candidate_profiles")