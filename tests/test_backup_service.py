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
