"""post status publishing

Revision ID: d4a9e2c7b1f8
Revises: c3e8f1a6d2b7
Create Date: 2026-10-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4a9e2c7b1f8'
down_revision: Union[str, Sequence[str], None] = 'c3e8f1a6d2b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE post_status ADD VALUE IF NOT EXISTS 'publishing' AFTER 'generated'")


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL non permette di togliere un valore da un enum: si riportano solo i post a generated
    op.execute("UPDATE posts SET status = 'generated' WHERE status = 'publishing'")
