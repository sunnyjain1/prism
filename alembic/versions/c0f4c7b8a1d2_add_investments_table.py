"""add investments table

Revision ID: c0f4c7b8a1d2
Revises: b4d7e2f19a03
Create Date: 2026-05-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0f4c7b8a1d2'
down_revision: Union[str, Sequence[str], None] = 'b4d7e2f19a03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'investments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('account_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('symbol', sa.String(), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=True),
        sa.Column('buy_price', sa.Float(), nullable=True),
        sa.Column('buy_date', sa.Date(), nullable=True),
        sa.Column('current_price', sa.Float(), nullable=True),
        sa.Column('current_value', sa.Float(), nullable=True),
        sa.Column('invested_amount', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(), nullable=True, server_default='INR'),
        sa.Column('maturity_date', sa.Date(), nullable=True),
        sa.Column('interest_rate', sa.Float(), nullable=True),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_updated', sa.DateTime(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_investments_user_id'), 'investments', ['user_id'], unique=False)
    op.create_index(op.f('ix_investments_type'), 'investments', ['type'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_investments_type'), table_name='investments')
    op.drop_index(op.f('ix_investments_user_id'), table_name='investments')
    op.drop_table('investments')
