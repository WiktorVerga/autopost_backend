"""segnalazioni di bug dagli utenti: tabella reports

Revision ID: c5d8a2f6e9b1
Revises: b9c2e4f7a1d3
Create Date: 2026-11-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c5d8a2f6e9b1'
down_revision: Union[str, Sequence[str], None] = 'b9c2e4f7a1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False: i tipi vengono creati ed eliminati esplicitamente qui sotto
report_category = postgresql.ENUM(
    'missing_feature',
    'feature_error',
    'unclear_feature',
    'broken_feature',
    'improvement_suggestion',
    name='report_category',
    create_type=False,
)
report_status = postgresql.ENUM(
    'open', 'in_progress', 'resolved', 'dismissed', name='report_status', create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    report_category.create(op.get_bind())
    report_status.create(op.get_bind())
    op.create_table(
        'reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('category', report_category, nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', report_status, server_default='open', nullable=False),
        sa.Column('page_url', sa.String(length=500), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_reports_user_id'), 'reports', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_reports_user_id'), table_name='reports')
    op.drop_table('reports')
    report_status.drop(op.get_bind())
    report_category.drop(op.get_bind())
