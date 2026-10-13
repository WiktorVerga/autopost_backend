"""login google

Revision ID: a1c4f7d2b9e3
Revises: e2f3828d48e0
Create Date: 2026-10-13 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c4f7d2b9e3'
down_revision: Union[str, Sequence[str], None] = 'e2f3828d48e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('google_sub', sa.String(length=255), nullable=True))
    op.create_unique_constraint('users_google_sub_key', 'users', ['google_sub'])
    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=False)
    op.drop_constraint('users_google_sub_key', 'users', type_='unique')
    op.drop_column('users', 'google_sub')
