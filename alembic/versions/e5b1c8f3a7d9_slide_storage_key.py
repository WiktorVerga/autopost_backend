"""slide su S3: storage_key al posto di local_path e public_url

Revision ID: e5b1c8f3a7d9
Revises: d4a9e2c7b1f8
Create Date: 2026-10-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5b1c8f3a7d9'
down_revision: Union[str, Sequence[str], None] = 'd4a9e2c7b1f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # le slide ora stanno su S3: nel DB resta solo la chiave dell'oggetto
    op.add_column('slides', sa.Column('storage_key', sa.String(length=500), nullable=True))
    # le slide esistenti ricevono la chiave che avrebbero con il nuovo schema, ma l'oggetto su S3
    # non c'è finché il post non viene renderizzato di nuovo
    op.execute(
        "UPDATE slides SET storage_key = 'posts/' || post_id || '/slide-' || (position + 1) || '.jpg'"
    )
    op.alter_column('slides', 'storage_key', nullable=False)
    op.drop_column('slides', 'public_url')
    op.drop_column('slides', 'local_path')


def downgrade() -> None:
    """Downgrade schema."""
    # i file locali non esistono più: le slide tornano con percorso vuoto e senza URL
    op.add_column(
        'slides',
        sa.Column('local_path', sa.String(length=500), nullable=False, server_default=''),
    )
    op.alter_column('slides', 'local_path', server_default=None)
    op.add_column('slides', sa.Column('public_url', sa.String(length=1000), nullable=True))
    op.drop_column('slides', 'storage_key')
