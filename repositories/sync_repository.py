"""
Repository for Gmail sync models: UserGmailToken and AccountSyncConfig.
"""
from sqlalchemy.orm import Session
from typing import Optional, List
from models import UserGmailToken, AccountSyncConfig, SyncStatus
from core.encryption import encrypt_token, decrypt_token
import uuid
import datetime
import logging

logger = logging.getLogger(__name__)


class SyncRepository:
    def __init__(self, db: Session):
        self.db = db

    # --- UserGmailToken ---

    def get_gmail_token(self, user_id: str) -> Optional[UserGmailToken]:
        return self.db.query(UserGmailToken).filter(
            UserGmailToken.user_id == user_id
        ).first()

    def save_gmail_token(
        self, user_id: str, refresh_token: str,
        gmail_email: str = None, scopes: str = None
    ) -> UserGmailToken:
        existing = self.get_gmail_token(user_id)
        encrypted = encrypt_token(refresh_token)

        if existing:
            existing.encrypted_refresh_token = encrypted
            existing.gmail_email = gmail_email or existing.gmail_email
            existing.scopes = scopes or existing.scopes
            existing.is_valid = True
            self.db.commit()
            self.db.refresh(existing)
            return existing

        token = UserGmailToken(
            id=str(uuid.uuid4()),
            user_id=user_id,
            encrypted_refresh_token=encrypted,
            gmail_email=gmail_email,
            scopes=scopes,
            is_valid=True,
            created_at=datetime.datetime.utcnow()
        )
        self.db.add(token)
        self.db.commit()
        self.db.refresh(token)
        return token

    def get_decrypted_refresh_token(self, user_id: str) -> Optional[str]:
        token = self.get_gmail_token(user_id)
        if not token or not token.is_valid:
            return None
        return decrypt_token(token.encrypted_refresh_token)

    def invalidate_gmail_token(self, user_id: str) -> bool:
        token = self.get_gmail_token(user_id)
        if token:
            token.is_valid = False
            self.db.commit()
            return True
        return False

    def delete_gmail_token(self, user_id: str) -> bool:
        token = self.get_gmail_token(user_id)
        if token:
            self.db.delete(token)
            self.db.commit()
            return True
        return False

    # --- AccountSyncConfig ---

    def get_sync_config(self, account_id: str, owner_id: str) -> Optional[AccountSyncConfig]:
        return self.db.query(AccountSyncConfig).filter(
            AccountSyncConfig.account_id == account_id,
            AccountSyncConfig.owner_id == owner_id
        ).first()

    def get_sync_config_by_id(self, config_id: str) -> Optional[AccountSyncConfig]:
        return self.db.query(AccountSyncConfig).filter(
            AccountSyncConfig.id == config_id
        ).first()

    def create_sync_config(
        self, account_id: str, owner_id: str,
        gmail_search_query: str, importer_key: str,
        sync_interval_days: int = 30,
        attachment_filename_pattern: str = None,
        is_enabled: bool = True,
        pdf_password: str = None
    ) -> AccountSyncConfig:
        encrypted_pw = encrypt_token(pdf_password) if pdf_password else None
        
        config = AccountSyncConfig(
            id=str(uuid.uuid4()),
            account_id=account_id,
            owner_id=owner_id,
            gmail_search_query=gmail_search_query,
            importer_key=importer_key,
            sync_interval_days=sync_interval_days,
            attachment_filename_pattern=attachment_filename_pattern,
            encrypted_pdf_password=encrypted_pw,
            is_enabled=is_enabled,
            last_sync_status=SyncStatus.idle.value,
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow()
        )
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config

    def update_sync_config(self, config: AccountSyncConfig, **kwargs) -> AccountSyncConfig:
        if "pdf_password" in kwargs:
            raw_pw = kwargs.pop("pdf_password")
            if raw_pw is not None:
                config.encrypted_pdf_password = encrypt_token(raw_pw)

        for key, value in kwargs.items():
            if value is not None and hasattr(config, key):
                setattr(config, key, value)
        config.updated_at = datetime.datetime.utcnow()
        self.db.commit()
        self.db.refresh(config)
        return config

    def get_decrypted_pdf_password(self, config: AccountSyncConfig) -> Optional[str]:
        if not config or not config.encrypted_pdf_password:
            return None
        return decrypt_token(config.encrypted_pdf_password)

    def delete_sync_config(self, account_id: str, owner_id: str) -> bool:
        config = self.get_sync_config(account_id, owner_id)
        if config:
            self.db.delete(config)
            self.db.commit()
            return True
        return False

    def get_all_sync_configs_for_user(self, owner_id: str) -> List[AccountSyncConfig]:
        return self.db.query(AccountSyncConfig).filter(
            AccountSyncConfig.owner_id == owner_id
        ).all()

    def get_due_sync_configs(self) -> List[AccountSyncConfig]:
        """Get all enabled configs that are due for sync."""
        now = datetime.datetime.utcnow()
        configs = self.db.query(AccountSyncConfig).filter(
            AccountSyncConfig.is_enabled == True,
            AccountSyncConfig.last_sync_status != SyncStatus.syncing.value
        ).all()

        due = []
        for config in configs:
            if config.last_synced_at is None:
                due.append(config)
            else:
                next_sync = config.last_synced_at + datetime.timedelta(days=config.sync_interval_days)
                if now >= next_sync:
                    due.append(config)
        return due

    def set_sync_status(
        self, config: AccountSyncConfig, status: SyncStatus,
        error: str = None, txn_count: int = 0
    ):
        config.last_sync_status = status.value
        config.last_sync_error = error
        config.last_sync_txn_count = txn_count
        if status == SyncStatus.success:
            config.last_synced_at = datetime.datetime.utcnow()
        config.updated_at = datetime.datetime.utcnow()
        self.db.commit()
