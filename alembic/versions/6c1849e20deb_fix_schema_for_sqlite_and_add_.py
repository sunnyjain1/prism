"""Fix schema for SQLite and add CategorizationRule

Revision ID: 6c1849e20deb
Revises: ac97ab409e8e
Create Date: 2026-03-10 21:44:04.495176

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6c1849e20deb'
down_revision: Union[str, Sequence[str], None] = 'ac97ab409e8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add CategorizationRule if it doesn't exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    
    if 'categorization_rules' not in tables:
        op.create_table('categorization_rules',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('pattern', sa.String(), nullable=False),
            sa.Column('category_id', sa.String(), sa.ForeignKey('categories.id'), nullable=False),
            sa.Column('priority', sa.Integer(), default=0),
            sa.Column('owner_id', sa.String(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('is_regex', sa.Boolean(), default=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_categorization_rules_id'), 'categorization_rules', ['id'], unique=False)

    # 2. Fix Accounts (Add unique constraint correctly using batch mode for SQLite)
    existing_uqs = [uq['name'] for uq in inspector.get_unique_constraints('accounts')]
    if 'uq_account_name_owner' not in existing_uqs:
        with op.batch_alter_table('accounts', schema=None) as batch_op:
            batch_op.create_unique_constraint('uq_account_name_owner', ['name', 'owner_id'])

    # 3. Fix Account Sync Configs (Drop unused column)
    with op.batch_alter_table('account_sync_configs', schema=None) as batch_op:
        # Check if column exists first to avoid error if it's already gone
        columns = [c['name'] for c in inspector.get_columns('account_sync_configs')]
        if 'subject_match_pattern' in columns:
            batch_op.drop_column('subject_match_pattern')
        
    # 4. Miscellaneous: Ensure notes is a String (minor)
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.alter_column('notes',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.alter_column('notes',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)

    with op.batch_alter_table('account_sync_configs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subject_match_pattern', sa.VARCHAR(), nullable=True))

    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.drop_constraint('uq_account_name_owner', type_='unique')

    op.drop_table('categorization_rules')
