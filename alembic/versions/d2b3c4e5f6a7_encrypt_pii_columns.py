"""encrypt identifier PII columns at rest

Backfills existing plaintext values in the columns now typed as EncryptedString so
they match what the ORM writes going forward. Idempotent: a value that already
decrypts cleanly is left untouched, so re-running (or running after some rows were
written post-deploy) is safe.

Columns encrypted:
    users.full_name, users.phone_number
    sms_transactions.raw_body, sms_transactions.masked_account, sms_transactions.upi_id
    aggregated_assets.identifier
    credit_accounts.account_number_masked

Revision ID: d2b3c4e5f6a7
Revises: c1a2b3d4e5f6
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa
from cryptography.fernet import InvalidToken

from core.encryption import _get_pii_fernet, encrypt_pii


# revision identifiers, used by Alembic.
revision = "d2b3c4e5f6a7"
down_revision = "c1a2b3d4e5f6"
branch_labels = None
depends_on = None


# (table, primary key, [columns]) — all PII columns now backed by EncryptedString.
_TARGETS = [
    ("users", "id", ["full_name", "phone_number"]),
    ("sms_transactions", "id", ["raw_body", "masked_account", "upi_id"]),
    ("aggregated_assets", "id", ["identifier"]),
    ("credit_accounts", "id", ["account_number_masked"]),
]


def _is_encrypted(value: str) -> bool:
    try:
        _get_pii_fernet().decrypt(value.encode())
        return True
    except (InvalidToken, ValueError, TypeError):
        return False


def _transform(direction: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table, pk, columns in _TARGETS:
        if table not in existing_tables:
            continue
        table_columns = {c["name"] for c in inspector.get_columns(table)}
        cols = [c for c in columns if c in table_columns]
        if not cols:
            continue

        col_list = ", ".join(cols)
        rows = bind.execute(
            sa.text(f"SELECT {pk}, {col_list} FROM {table}")
        ).fetchall()

        for row in rows:
            row_id = row[0]
            updates = {}
            for idx, col in enumerate(cols, start=1):
                value = row[idx]
                if value is None:
                    continue
                if direction == "encrypt":
                    if not _is_encrypted(value):
                        updates[col] = encrypt_pii(value)
                else:  # decrypt
                    if _is_encrypted(value):
                        updates[col] = _get_pii_fernet().decrypt(value.encode()).decode()
            if updates:
                set_clause = ", ".join(f"{col} = :{col}" for col in updates)
                bind.execute(
                    sa.text(f"UPDATE {table} SET {set_clause} WHERE {pk} = :__pk"),
                    {**updates, "__pk": row_id},
                )


def upgrade() -> None:
    _transform("encrypt")


def downgrade() -> None:
    _transform("decrypt")
