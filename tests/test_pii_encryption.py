"""
Tests for PII-at-rest encryption.

PII identifier columns use the EncryptedString type, so the ORM round-trips plaintext
while the underlying DB stores Fernet ciphertext. Encryption is unconditional — there is
no setting that turns it off.
"""
import uuid

import sqlalchemy as sa

from core.encryption import EncryptedString, decrypt_pii, encrypt_pii
from models import SMSTransaction
from user_models import User


def _raw_value(db_session, table, column, pk):
    """Read a column straight from the DB, bypassing the ORM's EncryptedString decode."""
    return db_session.execute(
        sa.text(f"SELECT {column} FROM {table} WHERE id = :id"),
        {"id": pk},
    ).scalar()


def test_user_pii_roundtrips_through_orm(db_session):
    user = User(
        id=str(uuid.uuid4()),
        email="pii@test.com",
        hashed_password="x",
        full_name="Sunny Jain",
        phone_number="9876543210",
    )
    db_session.add(user)
    db_session.flush()
    db_session.expire_all()  # force a fresh load from the DB

    reloaded = db_session.query(User).filter(User.id == user.id).first()
    assert reloaded.full_name == "Sunny Jain"
    assert reloaded.phone_number == "9876543210"


def test_user_pii_is_ciphertext_at_rest(db_session):
    user = User(
        id=str(uuid.uuid4()),
        email="pii2@test.com",
        hashed_password="x",
        full_name="Sunny Jain",
        phone_number="9876543210",
    )
    db_session.add(user)
    db_session.flush()

    raw_phone = _raw_value(db_session, "users", "phone_number", user.id)
    raw_name = _raw_value(db_session, "users", "full_name", user.id)

    # Stored value must NOT be the plaintext...
    assert raw_phone != "9876543210"
    assert raw_name != "Sunny Jain"
    # ...but must decrypt back to it.
    assert decrypt_pii(raw_phone) == "9876543210"
    assert decrypt_pii(raw_name) == "Sunny Jain"
    # email is intentionally left plaintext (it is the login lookup key).
    raw_email = _raw_value(db_session, "users", "email", user.id)
    assert raw_email == "pii2@test.com"


def test_null_pii_stays_null(db_session):
    user = User(
        id=str(uuid.uuid4()),
        email="pii3@test.com",
        hashed_password="x",
        full_name=None,
        phone_number=None,
    )
    db_session.add(user)
    db_session.flush()
    db_session.expire_all()

    reloaded = db_session.query(User).filter(User.id == user.id).first()
    assert reloaded.full_name is None
    assert reloaded.phone_number is None
    assert _raw_value(db_session, "users", "phone_number", user.id) is None


def test_sms_pii_columns_encrypted(db_session):
    sms = SMSTransaction(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        raw_body="Rs.500 debited from A/c XX1234 to user@upi",
        masked_account="XX1234",
        upi_id="user@upi",
        dedup_hash="hash-1",
    )
    db_session.add(sms)
    db_session.flush()

    raw_body = _raw_value(db_session, "sms_transactions", "raw_body", sms.id)
    assert raw_body != "Rs.500 debited from A/c XX1234 to user@upi"
    assert decrypt_pii(raw_body) == "Rs.500 debited from A/c XX1234 to user@upi"

    db_session.expire_all()
    reloaded = db_session.query(SMSTransaction).filter(SMSTransaction.id == sms.id).first()
    assert reloaded.masked_account == "XX1234"
    assert reloaded.upi_id == "user@upi"


def test_decrypt_pii_tolerates_legacy_plaintext():
    # Legacy rows written before encryption return unchanged (no crash).
    assert decrypt_pii("plain-legacy-value") == "plain-legacy-value"
    # Round-trip still works for genuine ciphertext.
    assert decrypt_pii(encrypt_pii("secret")) == "secret"


def test_encrypted_string_type_is_applied_to_columns():
    # Guard against someone reverting a column back to plain String.
    assert isinstance(User.__table__.c.phone_number.type, EncryptedString)
    assert isinstance(User.__table__.c.full_name.type, EncryptedString)
    assert isinstance(SMSTransaction.__table__.c.raw_body.type, EncryptedString)
    # email must stay plaintext for login lookups.
    assert not isinstance(User.__table__.c.email.type, EncryptedString)
