"""add soft delete columns to accounts

Revision ID: b4d7e2f19a03
Revises: 1cfc96a9c528
Create Date: 2026-02-22 15:28:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4d7e2f19a03'
down_revision: Union[str, Sequence[str], None] = '1cfc96a9c528'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('accounts', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('0')))
    op.add_column('accounts', sa.Column('deleted_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('accounts', 'deleted_at')
    op.drop_column('accounts', 'is_deleted')
