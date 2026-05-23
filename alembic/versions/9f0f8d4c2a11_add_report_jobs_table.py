"""add report jobs table

Revision ID: 9f0f8d4c2a11
Revises: 13ad759ab09b
Create Date: 2026-05-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f0f8d4c2a11'
down_revision: Union[str, Sequence[str], None] = '13ad759ab09b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'report_jobs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('report_type', sa.String(), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('format', sa.String(), nullable=False, server_default='pdf'),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('file_path', sa.String(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_report_jobs_user_id'), 'report_jobs', ['user_id'], unique=False)

    op.create_table(
        'email_report_preferences',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('report_type', sa.String(), nullable=False),
        sa.Column('frequency', sa.String(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'report_type', name='uq_email_report_pref_user_type'),
    )
    op.create_index(op.f('ix_email_report_preferences_user_id'), 'email_report_preferences', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_email_report_preferences_user_id'), table_name='email_report_preferences')
    op.drop_table('email_report_preferences')
    op.drop_index(op.f('ix_report_jobs_user_id'), table_name='report_jobs')
    op.drop_table('report_jobs')
