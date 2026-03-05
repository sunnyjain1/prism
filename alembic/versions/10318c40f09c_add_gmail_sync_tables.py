"""add_gmail_sync_tables

Revision ID: 10318c40f09c
Revises: b4d7e2f19a03
Create Date: 2026-03-05 23:42:16.149517

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '10318c40f09c'
down_revision: Union[str, Sequence[str], None] = 'b4d7e2f19a03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Gmail sync tables."""
    op.create_table('user_gmail_tokens',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('encrypted_refresh_token', sa.String(), nullable=False),
    sa.Column('gmail_email', sa.String(), nullable=True),
    sa.Column('scopes', sa.String(), nullable=True),
    sa.Column('is_valid', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_index(op.f('ix_user_gmail_tokens_id'), 'user_gmail_tokens', ['id'], unique=False)

    op.create_table('account_sync_configs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('account_id', sa.String(), nullable=False),
    sa.Column('owner_id', sa.String(), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), nullable=False),
    sa.Column('gmail_search_query', sa.String(), nullable=False),
    sa.Column('importer_key', sa.String(), nullable=False),
    sa.Column('sync_interval_days', sa.Integer(), nullable=True),
    sa.Column('attachment_filename_pattern', sa.String(), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(), nullable=True),
    sa.Column('last_sync_status', sa.String(), nullable=True),
    sa.Column('last_sync_error', sa.String(), nullable=True),
    sa.Column('last_sync_txn_count', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('account_id')
    )
    op.create_index(op.f('ix_account_sync_configs_id'), 'account_sync_configs', ['id'], unique=False)


def downgrade() -> None:
    """Remove Gmail sync tables."""
    op.drop_index(op.f('ix_account_sync_configs_id'), table_name='account_sync_configs')
    op.drop_table('account_sync_configs')
    op.drop_index(op.f('ix_user_gmail_tokens_id'), table_name='user_gmail_tokens')
    op.drop_table('user_gmail_tokens')
