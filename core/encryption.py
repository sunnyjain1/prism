"""
Encryption utilities for sensitive data.

Two consumers:
- ``encrypt_token`` / ``decrypt_token`` — OAuth tokens and PDF passwords, keyed off SECRET_KEY.
- ``EncryptedString`` — a SQLAlchemy column type that transparently encrypts identifier PII
  at rest, keyed off ``settings.PII_ENCRYPTION_KEY``. Always on; there is no user toggle.

Both use Fernet (AES-128-CBC + HMAC). Fernet ciphertext is randomized, so encrypted columns
must never be used in SQL ``WHERE`` / ``ORDER BY`` / aggregation clauses.
"""
import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import Text, TypeDecorator

from core.config import settings


def _derive_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from a secret string."""
    # Fernet requires a URL-safe base64-encoded 32-byte key
    key_bytes = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


def _get_fernet() -> Fernet:
    return Fernet(_derive_key(settings.SECRET_KEY))


def _get_pii_fernet() -> Fernet:
    return Fernet(_derive_key(settings.PII_ENCRYPTION_KEY))


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token string. Returns base64-encoded ciphertext."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a token string. Returns plaintext."""
    f = _get_fernet()
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise ValueError("Decryption failed: Invalid token or key mismatch. Please re-save your settings.")
    except Exception as e:
        raise ValueError(f"Decrypted failed: {str(e)}")


def encrypt_pii(plaintext: str) -> str:
    """Encrypt a PII string with the dedicated PII key. Returns base64 ciphertext."""
    return _get_pii_fernet().encrypt(plaintext.encode()).decode()


def decrypt_pii(value: str) -> str:
    """
    Decrypt a PII string. Returns the value unchanged if it is not valid ciphertext,
    so legacy plaintext rows written before encryption was introduced still read back.
    """
    try:
        return _get_pii_fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        return value


class EncryptedString(TypeDecorator):
    """
    SQLAlchemy column type that transparently encrypts/decrypts string PII at rest.

    Stored as Text ciphertext. ``None`` passes through untouched. Decryption tolerates
    legacy plaintext (returns it as-is) so a backfill migration can run incrementally.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect) -> Optional[str]:
        if value is None:
            return None
        return encrypt_pii(value)

    def process_result_value(self, value: Optional[str], dialect) -> Optional[str]:
        if value is None:
            return None
        return decrypt_pii(value)
