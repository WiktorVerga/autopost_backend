"""templates generati da una definizione JSON

I template non sono più file HTML caricati dagli utenti: il client invia una definizione JSON e il
server ne genera il template Jinja2 da un HTML di base. Le righe esistenti (HTML caricati, senza
definizione) non sono convertibili: la tabella viene ricreata.

Revision ID: 7c2e9a4b1d6f
Revises: 5d73de73cc6b
Create Date: 2026-11-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7c2e9a4b1d6f'
down_revision: Union[str, Sequence[str], None] = '5d73de73cc6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index(op.f('ix_templates_user_id'), table_name='templates')
    op.drop_table('templates')
    sa.Enum(name='template_format').drop(op.get_bind(), checkfirst=True)

    op.create_table('templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('base_template', sa.Enum('plain', name='base_template', native_enum=False, length=50), nullable=False),
    sa.Column('base_version', sa.Integer(), nullable=False),
    sa.Column('definition_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('jinja_content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_templates_user_id'), 'templates', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_templates_user_id'), table_name='templates')
    op.drop_table('templates')

    op.create_table('templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('format', sa.Enum('carousel', 'reel', name='template_format'), nullable=False),
    sa.Column('html_content', sa.Text(), nullable=False),
    sa.Column('variables', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('width', sa.Integer(), server_default=sa.text('1080'), nullable=False),
    sa.Column('height', sa.Integer(), server_default=sa.text('1350'), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_templates_user_id'), 'templates', ['user_id'], unique=False)
