"""add_smart_categorization_tables

Revision ID: 21f0d6a4c9b1
Revises: 1303c5d330aa
Create Date: 2026-05-23 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '21f0d6a4c9b1'
down_revision: Union[str, Sequence[str], None] = '1303c5d330aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'merchant_category_mappings',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('merchant_pattern', sa.String(), nullable=False),
        sa.Column('category_id', sa.String(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('usage_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'merchant_pattern', name='uq_merchant_category_user_pattern'),
    )
    op.create_index(op.f('ix_merchant_category_mappings_id'), 'merchant_category_mappings', ['id'], unique=False)

    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('categorization_method', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('categorization_confidence', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_column('categorization_confidence')
        batch_op.drop_column('categorization_method')

    op.drop_index(op.f('ix_merchant_category_mappings_id'), table_name='merchant_category_mappings')
    op.drop_table('merchant_category_mappings')
