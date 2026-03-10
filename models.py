from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, BigInteger, UniqueConstraint, Boolean
from sqlalchemy.orm import relationship
from database import Base
import datetime
from datetime import timezone
import enum

class AccountType(str, enum.Enum):
    checking = "checking"
    savings = "savings"
    credit = "credit"
    investment = "investment"
    cash = "cash"

class TransactionType(str, enum.Enum):
    income = "income"
    expense = "expense"
    transfer = "transfer"

class Category(Base):
    __tablename__ = "categories"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False) # income, expense
    color = Column(String, default="#10b981") # Primary emerald color
    
    owner_id = Column(String, ForeignKey("users.id"), nullable=False)



class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    type = Column(String) # checking, savings, credit, investment, cash
    currency = Column(String, default="INR")
    balance = Column(Float, default=0.0)
    
    # New Phase 3 Fields
    billing_cycle_day = Column(Integer, default=1) # For credit cards
    credit_limit = Column(Float, nullable=True)
    
    owner_id = Column(String, ForeignKey("users.id"), nullable=False)

    # Soft delete
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint('name', 'owner_id', name='uq_account_name_owner'),
    )

    transactions = relationship("Transaction", foreign_keys="Transaction.account_id", back_populates="account")

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String, primary_key=True, index=True)
    amount = Column(Float, nullable=False)
    type = Column(String, nullable=False) # income, expense, transfer
    description = Column(String)
    merchant = Column(String, nullable=True)
    date = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    timestamp = Column(BigInteger) # For sync logic if needed
    notes = Column(String, nullable=True)
    
    owner_id = Column(String, ForeignKey("users.id"), nullable=False)


    
    # Category relation
    category_id = Column(String, ForeignKey("categories.id"), nullable=True)
    category = relationship("Category")
    
    # Account relations
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    account = relationship("Account", foreign_keys=[account_id], back_populates="transactions")
    
    # Transfer relations
    destination_account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    destination_account = relationship("Account", foreign_keys=[destination_account_id])


class UserGmailToken(Base):
    """Encrypted OAuth2 tokens for Gmail API access. One per user."""
    __tablename__ = "user_gmail_tokens"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    encrypted_refresh_token = Column(String, nullable=False)
    gmail_email = Column(String, nullable=True)
    scopes = Column(String, nullable=True)
    is_valid = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))


class SyncStatus(str, enum.Enum):
    idle = "idle"
    syncing = "syncing"
    success = "success"
    failed = "failed"


class AccountSyncConfig(Base):
    """Per-account configuration for Gmail auto-sync."""
    __tablename__ = "account_sync_configs"

    id = Column(String, primary_key=True, index=True)
    account_id = Column(String, ForeignKey("accounts.id"), unique=True, nullable=False)
    owner_id = Column(String, ForeignKey("users.id"), nullable=False)

    is_enabled = Column(Boolean, default=True, nullable=False)
    gmail_search_query = Column(String, nullable=False)
    importer_key = Column(String, nullable=False)
    sync_interval_days = Column(Integer, default=30)
    attachment_filename_pattern = Column(String, nullable=True)
    encrypted_pdf_password = Column(String, nullable=True)

    # Historical sync: earliest date to sync from on first run
    sync_start_date = Column(DateTime, nullable=True)

    # Sync state
    last_synced_at = Column(DateTime, nullable=True)
    last_sync_status = Column(String, default=SyncStatus.idle.value)
    last_sync_error = Column(String, nullable=True)
    last_sync_txn_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc), onupdate=lambda: datetime.datetime.now(timezone.utc))

    # Relationships
    account = relationship("Account")


class CategorizationRule(Base):
    """User-defined rules for auto-categorizing transactions."""
    __tablename__ = "categorization_rules"

    id = Column(String, primary_key=True, index=True)
    pattern = Column(String, nullable=False)
    category_id = Column(String, ForeignKey("categories.id"), nullable=False)
    priority = Column(Integer, default=0)
    owner_id = Column(String, ForeignKey("users.id"), nullable=False)
    is_regex = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc), onupdate=lambda: datetime.datetime.now(timezone.utc))

    # Relationships
    category = relationship("Category")
