"""richieste di invito alla beta: tabella beta_requests

Revision ID: b9c2e4f7a1d3
Revises: a3e7c1f9d4b2
Create Date: 2026-11-23 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9c2e4f7a1d3'
down_revision: Union[str, Sequence[str], None] = 'a3e7c1f9d4b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'beta_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('instagram_handle', sa.String(length=30), nullable=False),
        sa.Column('company', sa.String(length=120), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('beta_requests')
