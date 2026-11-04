"""template dei programmi

Revision ID: b2f6c9d4e1a7
Revises: 9e4d2f7a3c18
Create Date: 2026-11-04 10:00:00.000000

Ogni programma ha al più un template (programs.template_id); un template può servire più
programmi. Un programma attivo deve averne uno: i programmi attivi già esistenti non ne hanno,
quindi vengono disattivati prima di aggiungere il vincolo.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2f6c9d4e1a7'
down_revision: Union[str, Sequence[str], None] = '9e4d2f7a3c18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('programs', sa.Column('template_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_programs_template_id'), 'programs', ['template_id'], unique=False)
    op.create_foreign_key(
        'programs_template_id_fkey', 'programs', 'templates', ['template_id'], ['id'], ondelete='SET NULL'
    )
    # nessun programma ha ancora un template: quelli attivi violerebbero il vincolo
    op.execute("UPDATE programs SET is_active = false, next_run = NULL WHERE is_active")
    op.create_check_constraint(
        'ck_program_active_needs_template', 'programs', 'NOT is_active OR template_id IS NOT NULL'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_program_active_needs_template', 'programs', type_='check')
    op.drop_constraint('programs_template_id_fkey', 'programs', type_='foreignkey')
    op.drop_index(op.f('ix_programs_template_id'), table_name='programs')
    op.drop_column('programs', 'template_id')
