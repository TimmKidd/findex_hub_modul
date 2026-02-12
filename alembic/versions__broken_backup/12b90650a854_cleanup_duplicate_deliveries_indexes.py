"""cleanup duplicate deliveries indexes

Revision ID: 12b90650a854
Revises: c4eec0e6bdc4
Create Date: 2026-01-26 22:10:31.076167

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '12b90650a854'
down_revision: Union[str, Sequence[str], None] = "c4eec0e6bdc4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
