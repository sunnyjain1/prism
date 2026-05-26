"""Add SMS transaction tables

Revision ID: a1b2c3d4e5f6
Revises: f2c3b7a9d4e1
Create Date: 2025-01-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f2c3b7a9d4e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sms_transactions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('raw_body', sa.String(), nullable=False),
        sa.Column('sender', sa.String(), nullable=True),
        sa.Column('sms_timestamp', sa.DateTime(), nullable=True),
        sa.Column('device_id', sa.String(), nullable=True),
        sa.Column('amount', sa.Float(), nullable=True),
        sa.Column('transaction_type', sa.String(), nullable=True),
        sa.Column('merchant', sa.String(), nullable=True),
        sa.Column('bank_name', sa.String(), nullable=True),
        sa.Column('masked_account', sa.String(), nullable=True),
        sa.Column('reference_number', sa.String(), nullable=True),
        sa.Column('available_balance', sa.Float(), nullable=True),
        sa.Column('upi_id', sa.String(), nullable=True),
        sa.Column('card_type', sa.String(), nullable=True),
        sa.Column('matched_account_id', sa.String(), nullable=True),
        sa.Column('suggested_category_id', sa.String(), nullable=True),
        sa.Column('confidence', sa.Float(), default=0.0),
        sa.Column('status', sa.String(), default='draft'),
        sa.Column('confirmed_transaction_id', sa.String(), nullable=True),
        sa.Column('dedup_hash', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['matched_account_id'], ['accounts.id']),
        sa.ForeignKeyConstraint(['suggested_category_id'], ['categories.id']),
        sa.ForeignKeyConstraint(['confirmed_transaction_id'], ['transactions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'dedup_hash', name='uq_sms_txn_dedup'),
    )
    op.create_index('ix_sms_transactions_user_id', 'sms_transactions', ['user_id'])
    op.create_index('ix_sms_transactions_status', 'sms_transactions', ['status'])
    op.create_index('ix_sms_transactions_dedup_hash', 'sms_transactions', ['dedup_hash'])

    op.create_table(
        'sms_parser_rules',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('bank_name', sa.String(), nullable=False),
        sa.Column('sender_pattern', sa.String(), nullable=False),
        sa.Column('body_pattern', sa.String(), nullable=False),
        sa.Column('transaction_type', sa.String(), nullable=False),
        sa.Column('priority', sa.Integer(), default=0),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('sms_parser_rules')
    op.drop_index('ix_sms_transactions_dedup_hash', 'sms_transactions')
    op.drop_index('ix_sms_transactions_status', 'sms_transactions')
    op.drop_index('ix_sms_transactions_user_id', 'sms_transactions')
    op.drop_table('sms_transactions')
