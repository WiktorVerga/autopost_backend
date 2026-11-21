"""tabella post_types

Le basi dei tipi di post (HTML annotato, regole modificabili dall'utente, schema di generazione
e valori di default delle variabili CSS per l'anteprima) passano dai file in public/ al DB. Una riga per ogni versione di un tipo.

Revision ID: a6d3f9c1e8b2
Revises: f3b7d1a9c2e5
Create Date: 2026-11-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a6d3f9c1e8b2'
down_revision: Union[str, Sequence[str], None] = 'f3b7d1a9c2e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('post_types',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Enum('carousel', 'single-post', 'motion-graphic-reel', name='post_type_name', native_enum=False, length=50), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('base_html', sa.Text(), nullable=False),
    sa.Column('editable_rules_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('generation_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('default_css_vars',postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name', 'version', name='uq_post_types_name_version')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('post_types')
