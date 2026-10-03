"""add aa_consents table and user phone_number

Revision ID: c1a2b3d4e5f6
Revises: b7e2f1c8a9d3
Create Date: 2026-06-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'b7e2f1c8a9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('phone_number', sa.String(), nullable=True))

    op.create_table(
        'aa_consents',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('consent_handle', sa.String(), nullable=True),
        sa.Column('consent_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('fi_types_json', sa.Text(), nullable=True, server_default='[]'),
        sa.Column('consent_url', sa.String(), nullable=True),
        sa.Column('data_session_id', sa.String(), nullable=True),
        sa.Column('last_fetched_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_aa_consents_user_id'), 'aa_consents', ['user_id'], unique=False)
    op.create_index(op.f('ix_aa_consents_consent_handle'), 'aa_consents', ['consent_handle'], unique=False)
    op.create_index(op.f('ix_aa_consents_consent_id'), 'aa_consents', ['consent_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_aa_consents_consent_id'), table_name='aa_consents')
    op.drop_index(op.f('ix_aa_consents_consent_handle'), table_name='aa_consents')
    op.drop_index(op.f('ix_aa_consents_user_id'), table_name='aa_consents')
    op.drop_table('aa_consents')
    op.drop_column('users', 'phone_number')
