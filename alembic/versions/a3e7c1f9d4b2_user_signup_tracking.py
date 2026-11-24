"""tracciamento registrazione utenti: users.signup_method e users.created_at

signup_method dice come è stato creato l'account. Per gli utenti esistenti si deduce da
password_hash: chi ne ha una si è registrato con la password (e magari ha collegato Google in
seguito), chi non ce l'ha è entrato solo con Google.

created_at resta null per gli utenti esistenti, perché la loro data di registrazione non è nota;
i nuovi utenti la ricevono dal default del database.

Revision ID: a3e7c1f9d4b2
Revises: d1f4a7c2b9e6
Create Date: 2026-11-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a3e7c1f9d4b2'
down_revision: Union[str, Sequence[str], None] = 'd1f4a7c2b9e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False: il tipo viene creato ed eliminato esplicitamente qui sotto
signup_method = postgresql.ENUM('password', 'google', name='signup_method', create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    signup_method.create(op.get_bind())
    op.add_column('users', sa.Column('signup_method', signup_method, nullable=True))
    op.execute(
        "UPDATE users SET signup_method = "
        "CASE WHEN password_hash IS NULL THEN 'google' ELSE 'password' END::signup_method"
    )
    op.alter_column('users', 'signup_method', nullable=False)

    op.add_column(
        'users',
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )
    # default aggiunto dopo la colonna, così le righe esistenti restano null
    op.alter_column('users', 'created_at', server_default=sa.func.now())


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'created_at')
    op.drop_column('users', 'signup_method')
    signup_method.drop(op.get_bind())
