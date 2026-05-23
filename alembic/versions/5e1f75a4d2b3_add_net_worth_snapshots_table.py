"""add net worth snapshots table

Revision ID: 5e1f75a4d2b3
Revises: 1303c5d330aa
Create Date: 2026-05-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e1f75a4d2b3'
down_revision: Union[str, Sequence[str], None] = '1303c5d330aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    op.create_table(
        'net_worth_snapshots',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('total_assets', sa.Float(), nullable=False),
        sa.Column('total_liabilities', sa.Float(), nullable=False),
        sa.Column('net_worth', sa.Float(), nullable=False),
        sa.Column('breakdown', sa.JSON(), nullable=True),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_net_worth_snapshots_user_id'), 'net_worth_snapshots', ['user_id'], unique=False)
    op.create_index(op.f('ix_net_worth_snapshots_snapshot_date'), 'net_worth_snapshots', ['snapshot_date'], unique=False)



def downgrade() -> None:
    op.drop_index(op.f('ix_net_worth_snapshots_snapshot_date'), table_name='net_worth_snapshots')
    op.drop_index(op.f('ix_net_worth_snapshots_user_id'), table_name='net_worth_snapshots')
    op.drop_table('net_worth_snapshots')
