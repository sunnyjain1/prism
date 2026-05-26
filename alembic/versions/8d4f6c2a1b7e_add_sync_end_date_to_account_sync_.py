"""add_sync_end_date_to_account_sync_configs

Revision ID: 8d4f6c2a1b7e
Revises: 26c7dc11cfa1
Create Date: 2026-05-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d4f6c2a1b7e'
down_revision: Union[str, Sequence[str], None] = '26c7dc11cfa1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add sync_end_date column to account_sync_configs."""
    op.add_column(
        'account_sync_configs',
        sa.Column('sync_end_date', sa.Date(), nullable=True)
    )


def downgrade() -> None:
    """Remove sync_end_date column from account_sync_configs."""
    op.drop_column('account_sync_configs', 'sync_end_date')
