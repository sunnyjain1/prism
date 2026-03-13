"""
Encryption utilities for sensitive data (OAuth tokens, etc.)
Uses Fernet symmetric encryption with the app's SECRET_KEY.
"""
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from core.config import settings


def _derive_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from the app's SECRET_KEY."""
    # Fernet requires a URL-safe base64-encoded 32-byte key
    key_bytes = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


def _get_fernet() -> Fernet:
    return Fernet(_derive_key(settings.SECRET_KEY))


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
