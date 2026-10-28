"""one post per idea

Revision ID: c3e8f1a6d2b7
Revises: f90d4f37571a
Create Date: 2026-10-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e8f1a6d2b7'
down_revision: Union[str, Sequence[str], None] = 'f90d4f37571a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # i post falliti senza contenuto sono quelli che il vincolo vuole evitare: non hanno nulla da
    # riprendere (le slide vanno via a cascata)
    op.execute("DELETE FROM posts WHERE status = 'failed' AND content IS NULL")
    op.drop_index('uq_post_program_idea_published', table_name='posts', postgresql_where=sa.text("status = 'published'"))
    op.create_unique_constraint('uq_post_program_idea', 'posts', ['program_id', 'idea_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_post_program_idea', 'posts', type_='unique')
    op.create_index('uq_post_program_idea_published', 'posts', ['program_id', 'idea_id'], unique=True, postgresql_where=sa.text("status = 'published'"))
