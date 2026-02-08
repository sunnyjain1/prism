"""Add missing notes column to transactions

Revision ID: e9a40d767154
Revises: a283feea8927
Create Date: 2026-02-08 15:17:03.767693

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9a40d767154'
down_revision: Union[str, Sequence[str], None] = 'a283feea8927'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('transactions')]
    if 'notes' not in columns:
        op.add_column('transactions', sa.Column('notes', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('transactions', 'notes')
