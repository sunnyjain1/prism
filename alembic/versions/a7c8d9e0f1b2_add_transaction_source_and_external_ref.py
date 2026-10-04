"""add transactions.source and transactions.external_ref (+ backfill refs)

external_ref holds the bank reference (UPI RRN / IMPS / NEFT UTR) so the same payment
arriving via manual entry, SMS, Gmail statement and AA is recognised as one. Existing
rows get their reference backfilled from the description (bank narrations carry it).

Revision ID: a7c8d9e0f1b2
Revises: f3a4b5c6d7e8
Create Date: 2026-10-04
"""
from alembic import op
import sqlalchemy as sa

revision = "a7c8d9e0f1b2"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def _columns() -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("transactions")}


def upgrade() -> None:
    columns = _columns()
    if "source" not in columns:
        op.add_column("transactions", sa.Column("source", sa.String(), nullable=True))
    if "external_ref" not in columns:
        op.add_column("transactions", sa.Column("external_ref", sa.String(), nullable=True))
        op.create_index("ix_transactions_external_ref", "transactions", ["external_ref"])
    op.create_index(
        "ix_transactions_owner_external_ref", "transactions", ["owner_id", "external_ref"],
        if_not_exists=True,
    )

    # Backfill from descriptions. Imported lazily so the migration has no hard
    # dependency on app modules beyond the pure extraction helper.
    from services.transaction_identity import extract_bank_reference

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, description FROM transactions WHERE external_ref IS NULL AND description IS NOT NULL"
    )).fetchall()
    updates = [
        {"ref": ref, "id": row_id}
        for row_id, description in rows
        if (ref := extract_bank_reference(description))
    ]
    if updates:
        bind.execute(sa.text("UPDATE transactions SET external_ref = :ref WHERE id = :id"), updates)


def downgrade() -> None:
    op.drop_index("ix_transactions_owner_external_ref", table_name="transactions", if_exists=True)
    columns = _columns()
    if "external_ref" in columns:
        op.drop_index("ix_transactions_external_ref", table_name="transactions", if_exists=True)
        op.drop_column("transactions", "external_ref")
    if "source" in columns:
        op.drop_column("transactions", "source")
