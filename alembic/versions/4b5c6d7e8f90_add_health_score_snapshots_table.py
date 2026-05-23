"""add health score snapshots table

Revision ID: 4b5c6d7e8f90
Revises: 7b2c4d8e9f10
Create Date: 2026-05-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b5c6d7e8f90'
down_revision: Union[str, Sequence[str], None] = '7b2c4d8e9f10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    op.create_table(
        'health_score_snapshots',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('grade', sa.String(), nullable=False),
        sa.Column('components', sa.JSON(), nullable=True),
        sa.Column('recommendations', sa.JSON(), nullable=True),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'snapshot_date', name='uq_health_score_snapshot_user_date'),
    )
    op.create_index(op.f('ix_health_score_snapshots_snapshot_date'), 'health_score_snapshots', ['snapshot_date'], unique=False)
    op.create_index(op.f('ix_health_score_snapshots_user_id'), 'health_score_snapshots', ['user_id'], unique=False)



def downgrade() -> None:
    op.drop_index(op.f('ix_health_score_snapshots_user_id'), table_name='health_score_snapshots')
    op.drop_index(op.f('ix_health_score_snapshots_snapshot_date'), table_name='health_score_snapshots')
    op.drop_table('health_score_snapshots')
