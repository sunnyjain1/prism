"""
Encrypted Backup & Data Portability Service.

Features:
- Export all user data as AES-256 encrypted JSON
- Import/restore from encrypted backup
- Incremental backup support
- Backup verification & integrity check
"""
import json
import hashlib
import base64
import os
from datetime import datetime
from typing import Optional
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from sqlalchemy.orm import Session
from sqlalchemy import and_

from models import Account, Transaction, Category, Budget


BACKUP_VERSION = "1.0"
PBKDF2_ITERATIONS = 100_000


def derive_key(password: str, salt: bytes) -> bytes:
    """Derive AES-256 key from user password using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode())


def encrypt_data(plaintext: bytes, password: str) -> dict:
    """Encrypt data with AES-256-GCM. Returns envelope with salt, nonce, ciphertext."""
    salt = os.urandom(16)
    key = derive_key(password, salt)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return {
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def decrypt_data(envelope: dict, password: str) -> bytes:
    """Decrypt AES-256-GCM envelope. Raises on wrong password."""
    salt = base64.b64decode(envelope["salt"])
    nonce = base64.b64decode(envelope["nonce"])
    ciphertext = base64.b64decode(envelope["ciphertext"])
    key = derive_key(password, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


class BackupService:
    def __init__(self, db: Session):
        self.db = db

    def export_user_data(self, user_id: str, password: str) -> dict:
        """
        Export all user data as encrypted backup.
        Returns the encrypted envelope ready for download.
        """
        data = self._collect_user_data(user_id)
        plaintext = json.dumps(data, default=str).encode("utf-8")

        # Compute checksum before encryption
        checksum = hashlib.sha256(plaintext).hexdigest()

        encrypted = encrypt_data(plaintext, password)

        return {
            "version": BACKUP_VERSION,
            "format": "prism-backup-v1",
            "created_at": datetime.utcnow().isoformat(),
            "user_id_hash": hashlib.sha256(user_id.encode()).hexdigest()[:16],
            "checksum": checksum,
            "data_size": len(plaintext),
            "encrypted": encrypted,
        }

    def import_user_data(self, user_id: str, backup: dict, password: str) -> dict:
        """
        Import/restore from encrypted backup.
        Returns summary of imported data.
        """
        if backup.get("format") != "prism-backup-v1":
            raise ValueError("Invalid backup format")

        # Decrypt
        plaintext = decrypt_data(backup["encrypted"], password)

        # Verify checksum
        checksum = hashlib.sha256(plaintext).hexdigest()
        if checksum != backup.get("checksum"):
            raise ValueError("Backup integrity check failed — file may be corrupted")

        data = json.loads(plaintext.decode("utf-8"))
        return self._restore_user_data(user_id, data)

    def verify_backup(self, backup: dict, password: str) -> dict:
        """Verify a backup without importing. Returns metadata."""
        if backup.get("format") != "prism-backup-v1":
            return {"valid": False, "error": "Invalid format"}

        try:
            plaintext = decrypt_data(backup["encrypted"], password)
            checksum = hashlib.sha256(plaintext).hexdigest()
            if checksum != backup.get("checksum"):
                return {"valid": False, "error": "Integrity check failed"}

            data = json.loads(plaintext.decode("utf-8"))
            return {
                "valid": True,
                "version": backup.get("version"),
                "created_at": backup.get("created_at"),
                "accounts": len(data.get("accounts", [])),
                "transactions": len(data.get("transactions", [])),
                "categories": len(data.get("categories", [])),
                "budgets": len(data.get("budgets", [])),
            }
        except Exception as e:
            return {"valid": False, "error": str(e)}

    def _collect_user_data(self, user_id: str) -> dict:
        """Collect all user data for backup."""
        accounts = self.db.query(Account).filter(
            Account.owner_id == user_id,
            Account.is_deleted == False,
        ).all()

        transactions = self.db.query(Transaction).filter(
            Transaction.owner_id == user_id,
        ).all()

        categories = self.db.query(Category).filter(
            Category.owner_id == user_id,
        ).all()

        budgets = self.db.query(Budget).filter(
            Budget.user_id == user_id,
        ).all()

        return {
            "accounts": [
                {
                    "id": a.id, "name": a.name, "account_type": a.account_type,
                    "balance": a.balance, "institution": a.institution,
                    "account_number": a.account_number, "currency": a.currency,
                    "color": a.color,
                }
                for a in accounts
            ],
            "transactions": [
                {
                    "id": t.id, "amount": t.amount, "type": t.type,
                    "description": t.description, "merchant": t.merchant,
                    "date": t.date, "notes": t.notes,
                    "category_id": t.category_id, "account_id": t.account_id,
                    "destination_account_id": t.destination_account_id,
                }
                for t in transactions
            ],
            "categories": [
                {
                    "id": c.id, "name": c.name, "type": c.type,
                    "color": c.color, "icon": c.icon,
                }
                for c in categories
            ],
            "budgets": [
                {
                    "id": b.id, "name": b.name, "amount": b.amount,
                    "period": b.period, "category_id": b.category_id,
                    "start_date": b.start_date, "end_date": b.end_date,
                }
                for b in budgets
            ],
            "exported_at": datetime.utcnow().isoformat(),
        }

    def _restore_user_data(self, user_id: str, data: dict) -> dict:
        """Restore user data from decrypted backup. Uses upsert logic."""
        summary = {"accounts": 0, "transactions": 0, "categories": 0, "budgets": 0}

        # Restore categories first (transactions reference them)
        for cat_data in data.get("categories", []):
            existing = self.db.query(Category).filter(
                Category.id == cat_data["id"]
            ).first()
            if not existing:
                cat = Category(
                    id=cat_data["id"],
                    name=cat_data["name"],
                    type=cat_data["type"],
                    color=cat_data.get("color", "#10b981"),
                    icon=cat_data.get("icon"),
                    owner_id=user_id,
                )
                self.db.add(cat)
                summary["categories"] += 1

        # Restore accounts
        for acc_data in data.get("accounts", []):
            existing = self.db.query(Account).filter(
                Account.id == acc_data["id"]
            ).first()
            if not existing:
                acc = Account(
                    id=acc_data["id"],
                    name=acc_data["name"],
                    account_type=acc_data.get("account_type", "savings"),
                    balance=acc_data.get("balance", 0),
                    institution=acc_data.get("institution"),
                    account_number=acc_data.get("account_number"),
                    currency=acc_data.get("currency", "INR"),
                    color=acc_data.get("color"),
                    owner_id=user_id,
                )
                self.db.add(acc)
                summary["accounts"] += 1

        self.db.flush()

        # Restore transactions
        for txn_data in data.get("transactions", []):
            existing = self.db.query(Transaction).filter(
                Transaction.id == txn_data["id"]
            ).first()
            if not existing:
                txn = Transaction(
                    id=txn_data["id"],
                    amount=txn_data["amount"],
                    type=txn_data["type"],
                    description=txn_data.get("description"),
                    merchant=txn_data.get("merchant"),
                    date=txn_data.get("date"),
                    notes=txn_data.get("notes"),
                    category_id=txn_data.get("category_id"),
                    account_id=txn_data.get("account_id"),
                    destination_account_id=txn_data.get("destination_account_id"),
                    owner_id=user_id,
                )
                self.db.add(txn)
                summary["transactions"] += 1

        # Restore budgets
        for bud_data in data.get("budgets", []):
            existing = self.db.query(Budget).filter(
                Budget.id == bud_data["id"]
            ).first()
            if not existing:
                bud = Budget(
                    id=bud_data["id"],
                    name=bud_data["name"],
                    amount=bud_data.get("amount", 0),
                    period=bud_data.get("period", "monthly"),
                    category_id=bud_data.get("category_id"),
                    start_date=bud_data.get("start_date"),
                    end_date=bud_data.get("end_date"),
                    user_id=user_id,
                )
                self.db.add(bud)
                summary["budgets"] += 1

        self.db.commit()
        return summary
