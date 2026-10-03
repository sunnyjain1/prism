"""add discovery tables and extend aggregated_assets

Revision ID: b7e2f1c8a9d3
Revises: 8d4f6c2a1b7e
Create Date: 2026-06-09 00:00:00.000000

Adds:
- discovery_sessions: tracks multi-phase financial discovery progress
- discovery_audit_logs: analytics/auditing for discovery and sync events
- aggregated_assets: new columns source_type, quantity_unit, ownership_percent
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e2f1c8a9d3'
down_revision: Union[str, Sequence[str], None] = '8d4f6c2a1b7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'discovery_sessions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='queued'),
        sa.Column('job_id', sa.String(), nullable=True),
        sa.Column('phases_json', sa.Text(), nullable=True, server_default='{}'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_discovery_sessions_user_id'), 'discovery_sessions', ['user_id'], unique=False)

    op.create_table(
        'discovery_audit_logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=True),
        sa.Column('entity_id', sa.String(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_discovery_audit_logs_user_id'), 'discovery_audit_logs', ['user_id'], unique=False
    )
    op.create_index(
        op.f('ix_discovery_audit_logs_event_type'), 'discovery_audit_logs', ['event_type'], unique=False
    )

    # Extend aggregated_assets
    op.add_column('aggregated_assets', sa.Column('source_type', sa.String(), nullable=True, server_default='auto'))
    op.add_column('aggregated_assets', sa.Column('quantity_unit', sa.String(), nullable=True))
    op.add_column('aggregated_assets', sa.Column('ownership_percent', sa.Float(), nullable=True, server_default='100.0'))


def downgrade() -> None:
    op.drop_column('aggregated_assets', 'ownership_percent')
    op.drop_column('aggregated_assets', 'quantity_unit')
    op.drop_column('aggregated_assets', 'source_type')

    op.drop_index(op.f('ix_discovery_audit_logs_event_type'), table_name='discovery_audit_logs')
    op.drop_index(op.f('ix_discovery_audit_logs_user_id'), table_name='discovery_audit_logs')
    op.drop_table('discovery_audit_logs')

    op.drop_index(op.f('ix_discovery_sessions_user_id'), table_name='discovery_sessions')
    op.drop_table('discovery_sessions')
