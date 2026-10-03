"""add credit_reports, credit_accounts, credit_inquiries tables

The CreditReport/CreditAccount/CreditInquiry models shipped without a migration,
so every /credit-score call 500'd on Postgres. Idempotent: skips tables that a
`create_all`-built database (tests, SQLite dev) already has.

Revision ID: f3a4b5c6d7e8
Revises: e1f2a3b4c5d6
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa

revision = "f3a4b5c6d7e8"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("credit_reports"):
        op.create_table(
            "credit_reports",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("score", sa.Integer(), nullable=True),
            sa.Column("score_range_min", sa.Integer(), nullable=True),
            sa.Column("score_range_max", sa.Integer(), nullable=True),
            sa.Column("report_date", sa.Date(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("raw_data_json", sa.Text(), nullable=True),
            sa.Column("consent_reference", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_credit_reports_user_id", "credit_reports", ["user_id"])

    if not _has_table("credit_accounts"):
        op.create_table(
            "credit_accounts",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("report_id", sa.String(), sa.ForeignKey("credit_reports.id"), nullable=False),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("account_type", sa.String(), nullable=False),
            sa.Column("institution", sa.String(), nullable=False),
            # EncryptedString is stored as TEXT (Fernet ciphertext).
            sa.Column("account_number_masked", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("opened_date", sa.Date(), nullable=True),
            sa.Column("closed_date", sa.Date(), nullable=True),
            sa.Column("sanctioned_amount", sa.Float(), nullable=True),
            sa.Column("current_balance", sa.Float(), nullable=True),
            sa.Column("credit_limit", sa.Float(), nullable=True),
            sa.Column("emi_amount", sa.Float(), nullable=True),
            sa.Column("interest_rate", sa.Float(), nullable=True),
            sa.Column("payment_history", sa.JSON(), nullable=True),
            sa.Column("days_past_due", sa.Integer(), nullable=True),
            sa.Column("is_overdue", sa.Boolean(), nullable=True),
            sa.Column("last_payment_date", sa.Date(), nullable=True),
            sa.Column("ownership", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_credit_accounts_report_id", "credit_accounts", ["report_id"])
        op.create_index("ix_credit_accounts_user_id", "credit_accounts", ["user_id"])

    if not _has_table("credit_inquiries"):
        op.create_table(
            "credit_inquiries",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("report_id", sa.String(), sa.ForeignKey("credit_reports.id"), nullable=False),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("institution", sa.String(), nullable=False),
            sa.Column("inquiry_type", sa.String(), nullable=False),
            sa.Column("purpose", sa.String(), nullable=True),
            sa.Column("inquiry_date", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_credit_inquiries_report_id", "credit_inquiries", ["report_id"])
        op.create_index("ix_credit_inquiries_user_id", "credit_inquiries", ["user_id"])


def downgrade() -> None:
    for table in ("credit_inquiries", "credit_accounts", "credit_reports"):
        if _has_table(table):
            op.drop_table(table)
