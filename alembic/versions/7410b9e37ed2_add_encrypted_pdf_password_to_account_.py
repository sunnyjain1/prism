"""add encrypted_pdf_password to account_sync_configs

Revision ID: 7410b9e37ed2
Revises: 10318c40f09c
Create Date: 2026-03-06 23:45:34.724879

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7410b9e37ed2'
down_revision: Union[str, Sequence[str], None] = '10318c40f09c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('account_sync_configs', sa.Column('encrypted_pdf_password', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('account_sync_configs', 'encrypted_pdf_password')
    # ### end Alembic commands ###
