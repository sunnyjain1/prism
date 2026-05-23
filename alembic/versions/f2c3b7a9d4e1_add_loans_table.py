"""add loans table

Revision ID: f2c3b7a9d4e1
Revises: 1303c5d330aa
Create Date: 2026-05-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2c3b7a9d4e1'
down_revision: Union[str, Sequence[str], None] = '1303c5d330aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'loans',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('loan_type', sa.String(), nullable=False),
        sa.Column('principal_amount', sa.Float(), nullable=False),
        sa.Column('outstanding_amount', sa.Float(), nullable=False),
        sa.Column('interest_rate', sa.Float(), nullable=False),
        sa.Column('emi_amount', sa.Float(), nullable=True),
        sa.Column('tenure_months', sa.Integer(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('emi_day', sa.Integer(), nullable=True),
        sa.Column('lender', sa.String(), nullable=True),
        sa.Column('account_id', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_loans_user_id'), 'loans', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_loans_user_id'), table_name='loans')
    op.drop_table('loans')
