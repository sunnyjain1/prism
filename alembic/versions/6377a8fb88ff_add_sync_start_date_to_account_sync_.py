"""add_sync_start_date_to_account_sync_configs

Revision ID: 6377a8fb88ff
Revises: 10318c40f09c
Create Date: 2026-03-10 15:49:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6377a8fb88ff'
down_revision: Union[str, Sequence[str], None] = '10318c40f09c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add sync_start_date column to account_sync_configs."""
    op.add_column(
        'account_sync_configs',
        sa.Column('sync_start_date', sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    """Remove sync_start_date column from account_sync_configs."""
    op.drop_column('account_sync_configs', 'sync_start_date')
