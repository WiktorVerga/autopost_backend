"""rimozione hashtags dai post

Revision ID: f90d4f37571a
Revises: b7d2e5a9c1f4
Create Date: 2026-10-15 12:23:24.704547

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f90d4f37571a'
down_revision: Union[str, Sequence[str], None] = 'b7d2e5a9c1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # gli hashtag ora fanno parte della caption
    op.drop_column('posts', 'hashtags')


def downgrade() -> None:
    """Downgrade schema."""
    # i post esistenti tornano con una lista vuota: gli hashtag restano nella caption
    op.add_column(
        'posts',
        sa.Column(
            'hashtags',
            postgresql.ARRAY(sa.String(length=100)),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
