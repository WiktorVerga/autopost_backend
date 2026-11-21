"""template collegati a post_types, post collegati al template

templates.base_template (base su file) e templates.base_version lasciano il posto a
templates.type_id, foreign key verso la versione del tipo di post (post_types) da cui il template
è generato: la versione della base è quella del tipo (Template.base_version).
posts.template_id lega ogni post generato al template, e da lì al tipo di post.

I template esistenti, generati dalle basi su file, vengono eliminati: i programmi attivi che li
usavano tornano inactive, perché un programma attivo deve avere un template
(ck_program_active_needs_template).

Revision ID: d1f4a7c2b9e6
Revises: a6d3f9c1e8b2
Create Date: 2026-11-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd1f4a7c2b9e6'
down_revision: Union[str, Sequence[str], None] = 'a6d3f9c1e8b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE programs SET status = 'inactive' WHERE status = 'active' AND template_id IS NOT NULL")
    # programs.template_id va a NULL (ON DELETE SET NULL)
    op.execute("DELETE FROM templates")

    op.drop_column('templates', 'base_template')
    op.drop_column('templates', 'base_version')
    op.add_column('templates', sa.Column('type_id', sa.Integer(), nullable=False))
    op.create_index(op.f('ix_templates_type_id'), 'templates', ['type_id'])
    op.create_foreign_key(
        'templates_type_id_fkey', 'templates', 'post_types', ['type_id'], ['id'], ondelete='RESTRICT'
    )

    # i post esistenti restano senza template (NULL)
    op.add_column('posts', sa.Column('template_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_posts_template_id'), 'posts', ['template_id'])
    op.create_foreign_key(
        'posts_template_id_fkey', 'posts', 'templates', ['template_id'], ['id'], ondelete='RESTRICT'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('posts_template_id_fkey', 'posts', type_='foreignkey')
    op.drop_index(op.f('ix_posts_template_id'), table_name='posts')
    op.drop_column('posts', 'template_id')

    # i template generati dai tipi di post non hanno una base su file a cui tornare
    op.execute("UPDATE programs SET status = 'inactive' WHERE status = 'active' AND template_id IS NOT NULL")
    op.execute("DELETE FROM templates")
    op.drop_constraint('templates_type_id_fkey', 'templates', type_='foreignkey')
    op.drop_index(op.f('ix_templates_type_id'), table_name='templates')
    op.drop_column('templates', 'type_id')
    op.add_column(
        'templates',
        sa.Column(
            'base_template',
            sa.Enum('plain', name='base_template', native_enum=False, length=50),
            nullable=False,
        ),
    )
    op.add_column('templates', sa.Column('base_version', sa.Integer(), nullable=False))
