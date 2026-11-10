"""descrizione dei template

Revision ID: 9e4d2f7a3c18
Revises: 7c2e9a4b1d6f
Create Date: 2026-11-03 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9e4d2f7a3c18'
down_revision: Union[str, Sequence[str], None] = '7c2e9a4b1d6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('templates', sa.Column('description', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('templates', 'description')
