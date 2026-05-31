from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, Enum, BigInteger, UniqueConstraint, Boolean, JSON, Text, func
from sqlalchemy.orm import relationship
from database import Base
import datetime
from datetime import timezone
import enum
from uuid import uuid4

class AccountType(str, enum.Enum):
    checking = "checking"
    current = "current"
    savings = "savings"
    credit = "credit"
    credit_card = "credit_card"
    loan = "loan"
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

    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc), onupdate=lambda: datetime.datetime.now(timezone.utc))




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

    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc), onupdate=lambda: datetime.datetime.now(timezone.utc))

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

    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc), onupdate=lambda: datetime.datetime.now(timezone.utc))

    # Category relation
    category_id = Column(String, ForeignKey("categories.id"), nullable=True)
    category = relationship("Category")
    categorization_method = Column(String, nullable=True)
    categorization_confidence = Column(Float, nullable=True)
    
    # Account relations
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    account = relationship("Account", foreign_keys=[account_id], back_populates="transactions")
    
    # Transfer relations
    destination_account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    destination_account = relationship("Account", foreign_keys=[destination_account_id])


class Budget(Base):
    __tablename__ = "budgets"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    category_id = Column(String, ForeignKey("categories.id"), nullable=True)
    amount = Column(Float, nullable=False)
    period = Column(String, nullable=False)
    start_date = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    category = relationship("Category")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="INR")
    frequency = Column(String, nullable=False)
    category_id = Column(String, ForeignKey("categories.id"), nullable=True)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    next_due_date = Column(Date, nullable=True)
    last_paid_date = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    auto_detected = Column(Boolean, default=False, nullable=False)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    category = relationship("Category")
    account = relationship("Account", foreign_keys=[account_id])


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    message = Column(String, nullable=False)
    type = Column(String, nullable=False)
    category = Column(String, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    action_url = Column(String, nullable=True)
    extra_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)


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
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc), onupdate=lambda: datetime.datetime.now(timezone.utc))


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
    sync_end_date = Column(Date, nullable=True)

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


class MerchantCategoryMapping(Base):
    __tablename__ = "merchant_category_mappings"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    merchant_pattern = Column(String, nullable=False)
    category_id = Column(String, ForeignKey("categories.id"), nullable=False)
    confidence = Column(Float, default=1.0)
    usage_count = Column(Integer, default=1)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    category = relationship("Category")

    __table_args__ = (
        UniqueConstraint("user_id", "merchant_pattern", name="uq_merchant_category_user_pattern"),
    )


class Investment(Base):
    __tablename__ = "investments"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    symbol = Column(String, nullable=True)
    quantity = Column(Float, nullable=True)
    buy_price = Column(Float, nullable=True)
    buy_date = Column(Date, nullable=True)
    current_price = Column(Float, nullable=True)
    current_value = Column(Float, nullable=True)
    invested_amount = Column(Float, nullable=False)
    currency = Column(String, default="INR")
    maturity_date = Column(Date, nullable=True)
    interest_rate = Column(Float, nullable=True)
    notes = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    last_updated = Column(DateTime, default=func.now())
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class NetWorthSnapshot(Base):
    __tablename__ = "net_worth_snapshots"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    total_assets = Column(Float, nullable=False)
    total_liabilities = Column(Float, nullable=False)
    net_worth = Column(Float, nullable=False)
    breakdown = Column(JSON, nullable=True)
    snapshot_date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=func.now())


class HealthScoreSnapshot(Base):
    __tablename__ = "health_score_snapshots"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    score = Column(Integer, nullable=False)
    grade = Column(String, nullable=False)
    components = Column(JSON, nullable=True)
    recommendations = Column(JSON, nullable=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "snapshot_date", name="uq_health_score_snapshot_user_date"),
    )


class Loan(Base):
    __tablename__ = "loans"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    loan_type = Column(String, nullable=False)
    principal_amount = Column(Float, nullable=False)
    outstanding_amount = Column(Float, nullable=False)
    interest_rate = Column(Float, nullable=False)
    emi_amount = Column(Float, nullable=True)
    tenure_months = Column(Integer, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    emi_day = Column(Integer, nullable=True)
    lender = Column(String, nullable=True)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    account = relationship("Account", foreign_keys=[account_id])


class ReportJob(Base):
    __tablename__ = "report_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    report_type = Column(String, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    format = Column(String, default="pdf", nullable=False)
    status = Column(String, default="pending", nullable=False)
    file_path = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)


class EmailReportPreference(Base):
    __tablename__ = "email_report_preferences"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    report_type = Column(String, nullable=False)
    frequency = Column(String, nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "report_type", name="uq_email_report_pref_user_type"),
    )


class SMSTransactionStatus(str, enum.Enum):
    draft = "draft"
    confirmed = "confirmed"
    rejected = "rejected"
    duplicate = "duplicate"


class SMSTransaction(Base):
    """Parsed SMS transaction — lives in review queue until confirmed."""
    __tablename__ = "sms_transactions"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    # Raw SMS data
    raw_body = Column(String, nullable=False)
    sender = Column(String, nullable=True)
    sms_timestamp = Column(DateTime, nullable=True)
    device_id = Column(String, nullable=True)

    # Parsed fields
    amount = Column(Float, nullable=True)
    transaction_type = Column(String, nullable=True)  # debit, credit, transfer, upi, atm, refund
    merchant = Column(String, nullable=True)
    bank_name = Column(String, nullable=True)
    masked_account = Column(String, nullable=True)  # last 4 digits e.g. "XX1234"
    reference_number = Column(String, nullable=True)
    available_balance = Column(Float, nullable=True)
    upi_id = Column(String, nullable=True)
    card_type = Column(String, nullable=True)  # credit_card, debit_card

    # Matching
    matched_account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    matched_account = relationship("Account", foreign_keys=[matched_account_id])
    suggested_category_id = Column(String, ForeignKey("categories.id"), nullable=True)
    suggested_category = relationship("Category", foreign_keys=[suggested_category_id])

    # Confidence & status
    confidence = Column(Float, default=0.0)  # 0.0 to 1.0
    status = Column(String, default=SMSTransactionStatus.draft.value, index=True)
    confirmed_transaction_id = Column(String, ForeignKey("transactions.id"), nullable=True)

    # Deduplication
    dedup_hash = Column(String, nullable=True, index=True)

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "dedup_hash", name="uq_sms_txn_dedup"),
    )


class SMSParserRule(Base):
    """Custom parser rules for specific bank SMS formats."""
    __tablename__ = "sms_parser_rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    bank_name = Column(String, nullable=False)
    sender_pattern = Column(String, nullable=False)  # regex for SMS sender
    body_pattern = Column(String, nullable=False)  # regex with named groups
    transaction_type = Column(String, nullable=False)
    priority = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)


class DataSourceType(str, enum.Enum):
    bank = "bank"
    mutual_fund = "mutual_fund"
    stock = "stock"
    credit_bureau = "credit_bureau"
    insurance = "insurance"
    epf = "epf"
    ppf = "ppf"
    nps = "nps"
    credit_card = "credit_card"


class ConnectionStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    failed = "failed"
    expired = "expired"
    revoked = "revoked"


class DataSourceConnection(Base):
    """User's connection to an external financial data source."""
    __tablename__ = "data_source_connections"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    source_type = Column(String, nullable=False)  # DataSourceType
    provider_name = Column(String, nullable=False)  # e.g., "CAMS", "KFintech", "CIBIL"
    display_name = Column(String)  # User-friendly name
    status = Column(String, default=ConnectionStatus.pending.value)
    consent_id = Column(String)  # External consent reference
    last_synced_at = Column(DateTime)
    next_sync_at = Column(DateTime)
    sync_frequency_hours = Column(Integer, default=24)
    error_message = Column(String)
    metadata_json = Column(Text, default="{}")  # Provider-specific metadata
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class AggregatedAsset(Base):
    """Assets discovered from connected data sources."""
    __tablename__ = "aggregated_assets"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    connection_id = Column(String, ForeignKey("data_source_connections.id"))
    asset_type = Column(String, nullable=False)  # mutual_fund, stock, fd, ppf, epf, nps, insurance
    name = Column(String, nullable=False)
    identifier = Column(String)  # ISIN, folio number, policy number
    institution = Column(String)  # AMC, broker, bank
    current_value = Column(Float, default=0.0)
    invested_value = Column(Float, default=0.0)
    returns_absolute = Column(Float, default=0.0)
    returns_percentage = Column(Float, default=0.0)
    units = Column(Float)  # For MF/stocks
    nav = Column(Float)  # Current NAV
    last_updated = Column(DateTime)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class CreditReport(Base):
    """User's credit report fetched from credit bureaus."""
    __tablename__ = "credit_reports"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String, nullable=False)  # cibil, experian, crif
    score = Column(Integer, nullable=True)
    score_range_min = Column(Integer, default=300)
    score_range_max = Column(Integer, default=900)
    report_date = Column(Date, nullable=True)
    fetched_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    status = Column(String, default="success")  # success, partial, failed
    raw_data_json = Column(Text, default="{}")
    consent_reference = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))

    accounts = relationship("CreditAccount", back_populates="report", cascade="all, delete-orphan")
    inquiries = relationship("CreditInquiry", back_populates="report", cascade="all, delete-orphan")


class CreditAccount(Base):
    """Individual credit account from a credit report."""
    __tablename__ = "credit_accounts"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    report_id = Column(String, ForeignKey("credit_reports.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    account_type = Column(String, nullable=False)  # credit_card, personal_loan, home_loan, auto_loan, consumer_loan
    institution = Column(String, nullable=False)
    account_number_masked = Column(String, nullable=True)
    status = Column(String, nullable=False)  # active, closed, written_off, settled
    opened_date = Column(Date, nullable=True)
    closed_date = Column(Date, nullable=True)
    sanctioned_amount = Column(Float, default=0.0)
    current_balance = Column(Float, default=0.0)
    credit_limit = Column(Float, default=0.0)
    emi_amount = Column(Float, default=0.0)
    interest_rate = Column(Float, default=0.0)
    payment_history = Column(JSON, nullable=True)  # Monthly payment statuses
    days_past_due = Column(Integer, default=0)
    is_overdue = Column(Boolean, default=False)
    last_payment_date = Column(Date, nullable=True)
    ownership = Column(String, default="individual")  # individual, joint, guarantor
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))

    report = relationship("CreditReport", back_populates="accounts")


class CreditInquiry(Base):
    """Hard/soft inquiries on the credit report."""
    __tablename__ = "credit_inquiries"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    report_id = Column(String, ForeignKey("credit_reports.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    institution = Column(String, nullable=False)
    inquiry_type = Column(String, nullable=False)  # hard, soft
    purpose = Column(String, nullable=True)  # credit_card, personal_loan, home_loan, etc.
    inquiry_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))

    report = relationship("CreditReport", back_populates="inquiries")
