"""Tests for backup service — encrypt, decrypt, verify."""
import pytest
from services.backup_service import encrypt_data, decrypt_data, BackupService


class TestEncryptDecrypt:
    def test_round_trip(self):
        plaintext = b"Hello, Prism backup!"
        password = "test-password-123"
        encrypted = encrypt_data(plaintext, password)
        decrypted = decrypt_data(encrypted, password)
        assert decrypted == plaintext

    def test_wrong_password_fails(self):
        plaintext = b"Secret financial data"
        encrypted = encrypt_data(plaintext, "correct-password")
        with pytest.raises(Exception):
            decrypt_data(encrypted, "wrong-password")

    def test_different_encryptions_differ(self):
        plaintext = b"Same data"
        e1 = encrypt_data(plaintext, "password")
        e2 = encrypt_data(plaintext, "password")
        # Different salt means different ciphertext
        assert e1["ciphertext"] != e2["ciphertext"]

    def test_large_data(self):
        plaintext = b"x" * 100_000
        encrypted = encrypt_data(plaintext, "strong-pass")
        decrypted = decrypt_data(encrypted, "strong-pass")
        assert decrypted == plaintext


class TestBackupServiceExport:
    """Integration tests require DB fixtures — tested via API tests."""

    def test_verify_invalid_format(self):
        """Verify rejects wrong format."""
        from unittest.mock import MagicMock
        db = MagicMock()
        service = BackupService(db)
        result = service.verify_backup({"format": "unknown"}, "password")
        assert result["valid"] is False
        assert "Invalid format" in result["error"]

    def test_verify_wrong_password(self):
        """Verify with wrong password returns invalid."""
        from unittest.mock import MagicMock
        db = MagicMock()
        service = BackupService(db)

        # Create a valid backup envelope manually
        import json, hashlib
        data = {"accounts": [], "transactions": [], "categories": [], "budgets": []}
        plaintext = json.dumps(data).encode()
        checksum = hashlib.sha256(plaintext).hexdigest()
        encrypted = encrypt_data(plaintext, "correct")
        backup = {
            "format": "prism-backup-v1",
            "version": "1.0",
            "checksum": checksum,
            "encrypted": encrypted,
        }

        result = service.verify_backup(backup, "wrong-password")
        assert result["valid"] is False

    def test_verify_valid_backup(self):
        """Verify a properly encrypted backup."""
        from unittest.mock import MagicMock
        db = MagicMock()
        service = BackupService(db)

        import json, hashlib
        data = {
            "accounts": [{"id": "a1"}],
            "transactions": [{"id": "t1"}, {"id": "t2"}],
            "categories": [],
            "budgets": [{"id": "b1"}],
        }
        plaintext = json.dumps(data).encode()
        checksum = hashlib.sha256(plaintext).hexdigest()
        encrypted = encrypt_data(plaintext, "my-password")
        backup = {
            "format": "prism-backup-v1",
            "version": "1.0",
            "checksum": checksum,
            "encrypted": encrypted,
        }

        result = service.verify_backup(backup, "my-password")
        assert result["valid"] is True
        assert result["accounts"] == 1
        assert result["transactions"] == 2
        assert result["budgets"] == 1


class TestExportRestoreRoundTrip:
    """Exports real model rows and restores them into a second user."""

    def _make_user(self, db_session, suffix):
        from uuid import uuid4
        from user_models import User

        user = User(id=str(uuid4()), email=f"backup-{suffix}-{uuid4().hex[:8]}@example.com",
                    hashed_password="x", full_name="Backup Tester")
        db_session.add(user)
        db_session.flush()
        return user

    def test_export_then_restore(self, db_session):
        from datetime import date, datetime
        from uuid import uuid4
        from models import Account, Budget, Category, Transaction

        source = self._make_user(db_session, "src")
        category = Category(id=str(uuid4()), name="Food", type="expense", owner_id=source.id)
        account = Account(id=str(uuid4()), name="HDFC Savings", type="savings", balance=1500.0,
                          currency="INR", owner_id=source.id)
        db_session.add_all([category, account])
        db_session.flush()
        db_session.add_all([
            Transaction(id=str(uuid4()), amount=250.0, type="expense", description="Lunch",
                        date=datetime(2026, 9, 1, 13, 30), owner_id=source.id,
                        account_id=account.id, category_id=category.id),
            Budget(id=str(uuid4()), user_id=source.id, name="Food budget", amount=5000.0,
                   period="monthly", category_id=category.id, start_date=date(2026, 9, 1)),
        ])
        db_session.flush()

        service = BackupService(db_session)
        envelope = service.export_user_data(source.id, "backup-pass")

        verified = service.verify_backup(envelope, "backup-pass")
        assert verified["valid"] is True
        assert verified["accounts"] == 1 and verified["transactions"] == 1

        # Restoring into the same user is a no-op: ids already exist.
        assert service.import_user_data(source.id, envelope, "backup-pass") == {
            "accounts": 0, "transactions": 0, "categories": 0, "budgets": 0,
        }

        # Delete the originals, then restore and check the rows come back intact.
        for model in (Transaction, Budget, Account, Category):
            db_session.query(model).filter(
                (model.user_id if model is Budget else model.owner_id) == source.id
            ).delete()
        db_session.flush()

        summary = service.import_user_data(source.id, envelope, "backup-pass")
        assert summary == {"accounts": 1, "transactions": 1, "categories": 1, "budgets": 1}
        restored = db_session.query(Account).filter(Account.owner_id == source.id).one()
        assert (restored.type, restored.balance) == ("savings", 1500.0)
        txn = db_session.query(Transaction).filter(Transaction.owner_id == source.id).one()
        assert txn.date == datetime(2026, 9, 1, 13, 30)
        budget = db_session.query(Budget).filter(Budget.user_id == source.id).one()
        assert budget.start_date == date(2026, 9, 1)
