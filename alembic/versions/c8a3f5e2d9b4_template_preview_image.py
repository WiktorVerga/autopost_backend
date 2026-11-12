"""anteprima dei template

Revision ID: c8a3f5e2d9b4
Revises: b2f6c9d4e1a7
Create Date: 2026-11-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c8a3f5e2d9b4'
down_revision: Union[str, Sequence[str], None] = 'b2f6c9d4e1a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # data URL JPEG in base64; i template già esistenti restano senza anteprima (NULL)
    op.add_column('templates', sa.Column('preview_image', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('templates', 'preview_image')
