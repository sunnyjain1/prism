from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum

class AccountType(str, Enum):
    checking = "checking"
    savings = "savings"
    credit = "credit"
    investment = "investment"
    cash = "cash"

class TransactionType(str, Enum):
    income = "income"
    expense = "expense"
    transfer = "transfer"

class CategoryBase(BaseModel):
    name: str
    type: TransactionType
    color: str = "#10b981"

class CategoryCreate(CategoryBase):
    id: str

class Category(CategoryBase):
    id: str
    model_config = ConfigDict(from_attributes=True)

class TransactionBase(BaseModel):
    amount: float
    type: TransactionType
    description: str
    merchant: Optional[str] = None
    date: datetime
    timestamp: int
    account_id: Optional[str] = None
    category_id: Optional[str] = None
    destination_account_id: Optional[str] = None
    notes: Optional[str] = None

class TransactionCreate(TransactionBase):
    id: str

class TransactionUpdate(BaseModel):
    amount: Optional[float] = None
    type: Optional[TransactionType] = None
    description: Optional[str] = None
    merchant: Optional[str] = None
    date: Optional[datetime] = None
    account_id: Optional[str] = None
    category_id: Optional[str] = None
    destination_account_id: Optional[str] = None
    notes: Optional[str] = None

class Transaction(TransactionBase):
    id: str
    category: Optional[Category] = None
    model_config = ConfigDict(from_attributes=True)

class AccountBase(BaseModel):
    name: str
    type: AccountType
    currency: str = "INR"
    balance: float = 0.0
    billing_cycle_day: int = 1
    credit_limit: Optional[float] = None

class AccountCreate(AccountBase):
    id: str

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[AccountType] = None
    currency: Optional[str] = None

class Account(AccountBase):
    id: str
    is_deleted: bool = False
    deleted_at: Optional[datetime] = None
    transactions: List[Transaction] = []
    model_config = ConfigDict(from_attributes=True)


class GoogleToken(BaseModel):
    token: str

class Token(BaseModel):
    access_token: str
    token_type: str

class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str = ""

class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    model_config = ConfigDict(from_attributes=True)

# --- Sync schemas ---

class SyncConfigBase(BaseModel):
    gmail_search_query: str
    importer_key: str
    sync_interval_days: int = Field(default=30, ge=1)
    attachment_filename_pattern: Optional[str] = None
    subject_match_pattern: Optional[str] = None
    is_enabled: bool = True

class SyncConfigCreate(SyncConfigBase):
    pdf_password: Optional[str] = None

class SyncConfigUpdate(BaseModel):
    gmail_search_query: Optional[str] = None
    importer_key: Optional[str] = None
    sync_interval_days: Optional[int] = Field(default=None, ge=1)
    attachment_filename_pattern: Optional[str] = None
    subject_match_pattern: Optional[str] = None
    is_enabled: Optional[bool] = None
    pdf_password: Optional[str] = None

class SyncConfigOut(SyncConfigBase):
    id: str
    account_id: str
    last_synced_at: Optional[datetime] = None
    last_sync_status: str = "idle"
    last_sync_error: Optional[str] = None
    last_sync_txn_count: int = 0
    has_pdf_password: bool = False
    model_config = ConfigDict(from_attributes=True)

class GmailConnectionStatus(BaseModel):
    is_connected: bool
    gmail_email: Optional[str] = None

class GmailOAuthCallback(BaseModel):
    code: str
