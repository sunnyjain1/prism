"""add user_import_profiles table

Revision ID: e1f2a3b4c5d6
Revises: d2b3c4e5f6a7
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa

revision = "e1f2a3b4c5d6"
down_revision = "d2b3c4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_import_profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_user_import_profiles_user_id", "user_import_profiles", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_import_profiles_user_id", table_name="user_import_profiles")
    op.drop_table("user_import_profiles")
