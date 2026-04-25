"""responds_statuses_v2

- переводим статусы responds на новый набор (NEW/IN_DIALOG/INVITED/...)
- обновляем CHECK constraint ck_responds_status
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "responds_statuses_v2"
down_revision = "da95b3649c64"
branch_labels = None
depends_on = None


OLD_TO_NEW = {
    "new": "NEW",
    "owner_replied": "IN_DIALOG",
    "owner_silent": "IN_DIALOG",
    "candidate_silent": "IN_DIALOG",
    "invited": "INVITED",
    "closed_by_owner": "CLOSED_BY_OWNER",
    "closed_by_candidate": "CLOSED_BY_CANDIDATE",
    "closed_system": "CLOSED_SYSTEM",
}

NEW_ALLOWED = (
    "NEW",
    "IN_DIALOG",
    "INVITED",
    "CLOSED_BY_OWNER",
    "CLOSED_BY_CANDIDATE",
    "CLOSED_SYSTEM",
)


def upgrade() -> None:
    # 1) снять старый CHECK (если есть)
    op.execute("ALTER TABLE responds DROP CONSTRAINT IF EXISTS ck_responds_status")

    # 2) привести данные к новым статусам
    for old, new in OLD_TO_NEW.items():
        op.execute(f"UPDATE responds SET status = '{new}' WHERE status = '{old}'")

    # 3) поставить новый CHECK constraint
    allowed_sql = ", ".join([f"'{s}'" for s in NEW_ALLOWED])
    op.execute(
        f"ALTER TABLE responds ADD CONSTRAINT ck_responds_status CHECK (status IN ({allowed_sql}))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE responds DROP CONSTRAINT IF EXISTS ck_responds_status")

    # приблизительный откат
    op.execute("UPDATE responds SET status='new' WHERE status='NEW'")
    op.execute("UPDATE responds SET status='owner_replied' WHERE status='IN_DIALOG'")
    op.execute("UPDATE responds SET status='invited' WHERE status='INVITED'")
    op.execute("UPDATE responds SET status='closed_by_owner' WHERE status='CLOSED_BY_OWNER'")
    op.execute("UPDATE responds SET status='closed_by_candidate' WHERE status='CLOSED_BY_CANDIDATE'")
    op.execute("UPDATE responds SET status='closed_system' WHERE status='CLOSED_SYSTEM'")

    old_allowed = (
        "new",
        "owner_replied",
        "owner_silent",
        "candidate_silent",
        "invited",
        "closed_by_owner",
        "closed_by_candidate",
        "closed_system",
    )
    allowed_sql = ", ".join([f"'{s}'" for s in old_allowed])
    op.execute(
        f"ALTER TABLE responds ADD CONSTRAINT ck_responds_status CHECK (status IN ({allowed_sql}))"
    )