"""stato dei programmi

Revision ID: f3b7d1a9c2e5
Revises: c8a3f5e2d9b4
Create Date: 2026-11-06 19:00:00.000000

programs.is_active diventa programs.status (active / inactive / archived): un programma
archiviato non può essere attivo per costruzione. I vincoli che richiedono raccolta e template
ai programmi attivi vengono riscritti su status.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3b7d1a9c2e5'
down_revision: Union[str, Sequence[str], None] = 'c8a3f5e2d9b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False: il tipo viene creato ed eliminato esplicitamente qui sotto
program_status = postgresql.ENUM(
    'active', 'inactive', 'archived', name='program_status', create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    program_status.create(op.get_bind())
    op.add_column(
        'programs',
        sa.Column('status', program_status, server_default='inactive', nullable=False),
    )
    op.execute("UPDATE programs SET status = 'active' WHERE is_active")
    op.create_index(op.f('ix_programs_status'), 'programs', ['status'], unique=False)

    op.drop_constraint('ck_program_active_needs_collection', 'programs', type_='check')
    op.drop_constraint('ck_program_active_needs_template', 'programs', type_='check')
    op.drop_column('programs', 'is_active')
    op.create_check_constraint(
        'ck_program_active_needs_collection',
        'programs',
        "status <> 'active' OR idea_collection_id IS NOT NULL",
    )
    op.create_check_constraint(
        'ck_program_active_needs_template', 'programs', "status <> 'active' OR template_id IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # gli archiviati tornano semplicemente non attivi
    op.add_column(
        'programs',
        sa.Column('is_active', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute("UPDATE programs SET is_active = (status = 'active')")
    op.alter_column('programs', 'is_active', server_default=None)

    op.drop_constraint('ck_program_active_needs_collection', 'programs', type_='check')
    op.drop_constraint('ck_program_active_needs_template', 'programs', type_='check')
    op.drop_index(op.f('ix_programs_status'), table_name='programs')
    op.drop_column('programs', 'status')
    program_status.drop(op.get_bind())
    op.create_check_constraint(
        'ck_program_active_needs_collection', 'programs', 'NOT is_active OR idea_collection_id IS NOT NULL'
    )
    op.create_check_constraint(
        'ck_program_active_needs_template', 'programs', 'NOT is_active OR template_id IS NOT NULL'
    )
