from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Any, Dict, Generic, List, Optional, TypeVar
from datetime import date, datetime
from enum import Enum

T = TypeVar("T")


def _clean_required_string(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty")
    return cleaned


def _clean_optional_string(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned

class AccountType(str, Enum):
    checking = "checking"
    current = "current"
    savings = "savings"
    credit = "credit"
    credit_card = "credit_card"
    loan = "loan"
    investment = "investment"
    cash = "cash"


class InvestmentType(str, Enum):
    mutual_fund = "mutual_fund"
    stock = "stock"
    fd = "fd"
    ppf = "ppf"
    epf = "epf"
    nps = "nps"
    gold = "gold"
    real_estate = "real_estate"
    bond = "bond"
    other = "other"


class LoanType(str, Enum):
    home = "home"
    car = "car"
    personal = "personal"
    education = "education"
    credit_card = "credit_card"
    other = "other"


class TransactionType(str, Enum):
    income = "income"
    expense = "expense"
    transfer = "transfer"

class NotificationType(str, Enum):
    info = "info"
    warning = "warning"
    alert = "alert"
    success = "success"


class BudgetPeriod(str, Enum):
    monthly = "monthly"
    weekly = "weekly"
    yearly = "yearly"


class NotificationCategory(str, Enum):
    transaction = "transaction"
    budget = "budget"
    system = "system"
    report = "report"


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None


class MessageResponse(BaseModel):
    message: str


class OkResponse(BaseModel):
    ok: bool = True


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    skip: int
    limit: int


class CategoryBase(BaseModel):
    name: str
    type: TransactionType
    color: str = "#10b981"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _clean_required_string(value, "Category name")

class CategoryCreate(CategoryBase):
    id: Optional[str] = None

class Category(CategoryBase):
    id: str
    model_config = ConfigDict(from_attributes=True)

class TransactionBase(BaseModel):
    amount: float = Field(gt=0)
    type: TransactionType
    description: str
    merchant: Optional[str] = None
    date: datetime
    timestamp: int
    account_id: Optional[str] = None
    category_id: Optional[str] = None
    destination_account_id: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _clean_required_string(value, "Transaction description")

    @field_validator("merchant", "notes")
    @classmethod
    def validate_optional_text(cls, value: Optional[str], info) -> Optional[str]:
        field_label = "Merchant" if info.field_name == "merchant" else "Notes"
        return _clean_optional_string(value, field_label)

class TransactionCreate(TransactionBase):
    id: str

class TransactionUpdate(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    type: Optional[TransactionType] = None
    description: Optional[str] = None
    merchant: Optional[str] = None
    date: Optional[datetime] = None
    account_id: Optional[str] = None
    category_id: Optional[str] = None
    destination_account_id: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("description", "merchant", "notes")
    @classmethod
    def validate_optional_fields(cls, value: Optional[str], info) -> Optional[str]:
        field_names = {
            "description": "Transaction description",
            "merchant": "Merchant",
            "notes": "Notes",
        }
        return _clean_optional_string(value, field_names[info.field_name])

class Transaction(TransactionBase):
    id: str
    category: Optional[Category] = None
    categorization_method: Optional[str] = None
    categorization_confidence: Optional[float] = None
    model_config = ConfigDict(from_attributes=True)

    # Response schema: be lenient with legacy data that has empty descriptions.
    # Strict validation only applies on create/update (TransactionBase/TransactionCreate).
    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, value: str) -> str:  # type: ignore[override]
        if not value or not str(value).strip():
            return "(no description)"
        return str(value).strip()

class AccountBase(BaseModel):
    name: str
    type: AccountType
    currency: str = "INR"
    balance: float = 0.0
    billing_cycle_day: int = Field(default=1, ge=1, le=31)
    credit_limit: Optional[float] = Field(default=None, ge=0, description="Total credit limit for the card")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _clean_required_string(value, "Account name")

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if len(cleaned) != 3 or not cleaned.isalpha():
            raise ValueError("Currency must be a 3-letter ISO code")
        return cleaned

class AccountCreate(AccountBase):
    id: Optional[str] = None

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[AccountType] = None
    currency: Optional[str] = None
    billing_cycle_day: Optional[int] = Field(default=None, ge=1, le=31)
    credit_limit: Optional[float] = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_string(value, "Account name")

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip().upper()
        if len(cleaned) != 3 or not cleaned.isalpha():
            raise ValueError("Currency must be a 3-letter ISO code")
        return cleaned

class Account(AccountBase):
    id: str
    is_deleted: bool = False
    deleted_at: Optional[datetime] = None
    monthly_income: float = 0.0
    monthly_expense: float = 0.0
    transactions: List[Transaction] = []
    model_config = ConfigDict(from_attributes=True)


class InvestmentBase(BaseModel):
    account_id: Optional[str] = None
    name: str
    type: InvestmentType
    symbol: Optional[str] = None
    quantity: Optional[float] = Field(default=None, ge=0)
    buy_price: Optional[float] = Field(default=None, ge=0)
    buy_date: Optional[date] = None
    current_price: Optional[float] = Field(default=None, ge=0)
    current_value: Optional[float] = Field(default=None, ge=0)
    invested_amount: float = Field(ge=0)
    currency: str = "INR"
    maturity_date: Optional[date] = None
    interest_rate: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def validate_investment_name(cls, value: str) -> str:
        return _clean_required_string(value, "Investment name")

    @field_validator("symbol", "notes")
    @classmethod
    def validate_optional_investment_strings(cls, value: Optional[str], info) -> Optional[str]:
        field_names = {
            "symbol": "Investment symbol",
            "notes": "Investment notes",
        }
        return _clean_optional_string(value, field_names[info.field_name])

    @field_validator("currency")
    @classmethod
    def validate_investment_currency(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if len(cleaned) != 3 or not cleaned.isalpha():
            raise ValueError("Currency must be a 3-letter ISO code")
        return cleaned


class InvestmentCreate(InvestmentBase):
    id: Optional[str] = None


class InvestmentUpdate(BaseModel):
    account_id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[InvestmentType] = None
    symbol: Optional[str] = None
    quantity: Optional[float] = Field(default=None, ge=0)
    buy_price: Optional[float] = Field(default=None, ge=0)
    buy_date: Optional[date] = None
    current_price: Optional[float] = Field(default=None, ge=0)
    current_value: Optional[float] = Field(default=None, ge=0)
    invested_amount: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = None
    maturity_date: Optional[date] = None
    interest_rate: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("name", "symbol", "notes")
    @classmethod
    def validate_optional_investment_fields(cls, value: Optional[str], info) -> Optional[str]:
        field_names = {
            "name": "Investment name",
            "symbol": "Investment symbol",
            "notes": "Investment notes",
        }
        return _clean_optional_string(value, field_names[info.field_name])

    @field_validator("currency")
    @classmethod
    def validate_optional_investment_currency(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip().upper()
        if len(cleaned) != 3 or not cleaned.isalpha():
            raise ValueError("Currency must be a 3-letter ISO code")
        return cleaned


class Investment(InvestmentBase):
    id: str
    user_id: str
    last_updated: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InvestmentPerformanceItem(BaseModel):
    id: str
    name: str
    type: InvestmentType
    invested_amount: float
    current_value: float
    total_returns: float
    returns_percentage: float


class InvestmentPortfolioSummary(BaseModel):
    total_invested: float
    total_current_value: float
    total_returns: float
    returns_percentage: float
    allocation_by_type: Dict[str, float]
    top_performers: List[InvestmentPerformanceItem]
    worst_performers: List[InvestmentPerformanceItem]


class NetWorthHistoryPoint(BaseModel):
    id: Optional[str] = None
    snapshot_date: date
    total_assets: float
    total_liabilities: float
    net_worth: float
    breakdown: Dict[str, float] = Field(default_factory=dict)
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class NetWorthSnapshotResponse(NetWorthHistoryPoint):
    user_id: str


class NetWorthSummary(BaseModel):
    total_assets: float
    total_liabilities: float
    net_worth: float
    breakdown: Dict[str, float] = Field(default_factory=dict)
    asset_breakdown: Dict[str, float] = Field(default_factory=dict)
    liability_breakdown: Dict[str, float] = Field(default_factory=dict)
    debt_to_asset_ratio: float
    snapshot_date: date


class AssetAllocationItem(BaseModel):
    type: str
    value: float
    percentage: float


class AssetAllocationResponse(BaseModel):
    total_assets: float
    allocation: List[AssetAllocationItem]


class HealthScoreComponent(BaseModel):
    score: Optional[int] = None
    value: Optional[float] = None
    label: str
    has_data: bool = True


class HealthScoreResponse(BaseModel):
    score: Optional[int] = None
    grade: Optional[str] = None
    components: Dict[str, HealthScoreComponent] = Field(default_factory=dict)
    recommendations: List[str] = Field(default_factory=list)
    has_enough_data: bool = True
    message: Optional[str] = None
    snapshot_date: date


class HealthScoreHistoryPoint(BaseModel):
    score: int
    grade: str
    snapshot_date: date
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class LoanBase(BaseModel):
    name: str
    loan_type: LoanType
    principal_amount: float = Field(gt=0)
    outstanding_amount: Optional[float] = Field(default=None, ge=0)
    interest_rate: float = Field(ge=0)
    emi_amount: Optional[float] = Field(default=None, gt=0)
    tenure_months: Optional[int] = Field(default=None, ge=1)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    emi_day: Optional[int] = Field(default=None, ge=1, le=31)
    lender: Optional[str] = None
    account_id: Optional[str] = None
    is_active: bool = True
    notes: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_loan_name(cls, value: str) -> str:
        return _clean_required_string(value, "Loan name")

    @field_validator("lender", "notes")
    @classmethod
    def validate_optional_loan_strings(cls, value: Optional[str], info) -> Optional[str]:
        field_names = {
            "lender": "Lender",
            "notes": "Notes",
        }
        return _clean_optional_string(value, field_names[info.field_name])

    @model_validator(mode="after")
    def validate_loan_dates_and_amounts(self):
        if self.outstanding_amount is not None and self.outstanding_amount > self.principal_amount:
            raise ValueError("Outstanding amount cannot exceed principal amount")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be after or equal to start_date")
        return self


class LoanCreate(LoanBase):
    id: Optional[str] = None


class LoanUpdate(BaseModel):
    name: Optional[str] = None
    loan_type: Optional[LoanType] = None
    principal_amount: Optional[float] = Field(default=None, gt=0)
    outstanding_amount: Optional[float] = Field(default=None, ge=0)
    interest_rate: Optional[float] = Field(default=None, ge=0)
    emi_amount: Optional[float] = Field(default=None, gt=0)
    tenure_months: Optional[int] = Field(default=None, ge=1)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    emi_day: Optional[int] = Field(default=None, ge=1, le=31)
    lender: Optional[str] = None
    account_id: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None

    @field_validator("name", "lender", "notes")
    @classmethod
    def validate_optional_loan_fields(cls, value: Optional[str], info) -> Optional[str]:
        field_names = {
            "name": "Loan name",
            "lender": "Lender",
            "notes": "Notes",
        }
        return _clean_optional_string(value, field_names[info.field_name])

    @model_validator(mode="after")
    def validate_optional_loan_dates_and_amounts(self):
        if (
            self.principal_amount is not None
            and self.outstanding_amount is not None
            and self.outstanding_amount > self.principal_amount
        ):
            raise ValueError("Outstanding amount cannot exceed principal amount")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be after or equal to start_date")
        return self


class LoanOverview(LoanBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    next_due_date: Optional[date] = None
    progress_percentage: float = 0
    paid_amount: float = 0
    total_interest_remaining: float = 0
    remaining_tenure_months: int = 0
    model_config = ConfigDict(from_attributes=True)


class LoanUpcomingEmi(BaseModel):
    loan_id: str
    name: str
    lender: Optional[str] = None
    due_date: date
    emi_amount: float
    outstanding_amount: float


class LoanSummaryResponse(BaseModel):
    total_outstanding: float
    monthly_emi_burden: float
    total_interest_payable: float
    active_count: int


class LoanListResponse(BaseModel):
    summary: LoanSummaryResponse
    loans: List[LoanOverview]
    upcoming_emis: List[LoanUpcomingEmi]


class LoanAmortizationItem(BaseModel):
    month_number: int
    due_date: Optional[date] = None
    emi_amount: float
    principal_component: float
    interest_component: float
    outstanding_balance: float
    is_current: bool = False


class LoanAmortizationResponse(BaseModel):
    loan: LoanOverview
    schedule: List[LoanAmortizationItem]
    monthly_emi: float
    total_interest_payable: float
    total_interest_paid: float
    total_interest_remaining: float
    remaining_tenure_months: int


class LoanPaymentCreate(BaseModel):
    amount: float = Field(gt=0)
    date: date


class LoanPaymentResponse(BaseModel):
    loan: LoanOverview
    amount: float
    payment_date: date
    principal_component: float
    interest_component: float
    outstanding_amount: float
    is_closed: bool


class GoogleToken(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    token: str = Field(default=None)
    credential: str = Field(default=None)

    @model_validator(mode="after")
    def resolve_token(self):
        if self.credential and not self.token:
            self.token = self.credential
        if not self.token:
            raise ValueError("Either 'token' or 'credential' must be provided")
        return self

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class SessionOut(BaseModel):
    id: str
    device_info: Optional[str] = None
    expires_at: datetime
    created_at: datetime
    is_active: bool
    model_config = ConfigDict(from_attributes=True)

class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str = ""

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _clean_required_string(value, "Email").lower()

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        return value.strip()

class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    model_config = ConfigDict(from_attributes=True)

class Notification(BaseModel):
    id: str
    user_id: str
    title: str
    message: str
    type: NotificationType
    category: Optional[NotificationCategory] = None
    is_read: bool = False
    action_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default=None, alias="extra_metadata", serialization_alias="metadata")
    created_at: datetime

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _clean_required_string(value, "Notification title")

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return _clean_required_string(value, "Notification message")

    @field_validator("action_url")
    @classmethod
    def validate_action_url(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_string(value, "Notification action URL")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class BudgetBase(BaseModel):
    name: str
    category_id: Optional[str] = None
    amount: float = Field(gt=0)
    period: BudgetPeriod
    start_date: Optional[date] = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def validate_budget_name(cls, value: str) -> str:
        return _clean_required_string(value, "Budget name")


class BudgetCreate(BudgetBase):
    pass


class BudgetUpdate(BaseModel):
    name: Optional[str] = None
    category_id: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)
    period: Optional[BudgetPeriod] = None
    start_date: Optional[date] = None
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validate_budget_name(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_string(value, "Budget name")


class Budget(BudgetBase):
    id: str
    user_id: str
    category: Optional[Category] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BudgetProgress(Budget):
    spent: float
    remaining: float
    percentage: float
    status: str


class BudgetAlert(BaseModel):
    budget: BudgetProgress
    severity: str
    message: str


class NotificationUnreadCount(BaseModel):
    unread_count: int


class NotificationReadAllResponse(BaseModel):
    updated_count: int


# --- Sync schemas ---

class SyncConfigBase(BaseModel):
    gmail_search_query: str
    importer_key: str
    sync_interval_days: int = Field(default=30, ge=1)
    attachment_filename_pattern: Optional[str] = None
    is_enabled: bool = True
    sync_start_date: Optional[datetime] = Field(
        default=None,
        description="Earliest date to sync from on the first run. "
                    "Set this to sync historical data (e.g. 2-3 years back)."
    )
    sync_end_date: Optional[date] = None

    @field_validator("gmail_search_query", "importer_key")
    @classmethod
    def validate_required_strings(cls, value: str, info) -> str:
        field_names = {
            "gmail_search_query": "Gmail search query",
            "importer_key": "Importer key",
        }
        return _clean_required_string(value, field_names[info.field_name])

    @field_validator("attachment_filename_pattern")
    @classmethod
    def validate_attachment_pattern(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_string(value, "Attachment filename pattern")

class SyncConfigCreate(SyncConfigBase):
    pdf_password: Optional[str] = None

class SyncConfigUpdate(BaseModel):
    gmail_search_query: Optional[str] = None
    importer_key: Optional[str] = None
    sync_interval_days: Optional[int] = Field(default=None, ge=1)
    attachment_filename_pattern: Optional[str] = None
    is_enabled: Optional[bool] = None
    pdf_password: Optional[str] = None
    sync_start_date: Optional[datetime] = None
    sync_end_date: Optional[date] = None

    @field_validator("gmail_search_query", "importer_key", "attachment_filename_pattern", "pdf_password")
    @classmethod
    def validate_optional_strings(cls, value: Optional[str], info) -> Optional[str]:
        field_names = {
            "gmail_search_query": "Gmail search query",
            "importer_key": "Importer key",
            "attachment_filename_pattern": "Attachment filename pattern",
            "pdf_password": "PDF password",
        }
        return _clean_optional_string(value, field_names[info.field_name])

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
    state: str


class CategorizationRuleBase(BaseModel):
    pattern: str
    category_id: str
    priority: int = 0
    is_regex: bool = False

    @field_validator("pattern", "category_id")
    @classmethod
    def validate_rule_fields(cls, value: str, info) -> str:
        field_names = {
            "pattern": "Rule pattern",
            "category_id": "Category ID",
        }
        return _clean_required_string(value, field_names[info.field_name])

class CategorizationRuleCreate(CategorizationRuleBase):
    id: Optional[str] = None

class CategorizationRule(CategorizationRuleBase):
    id: str
    owner_id: str
    category: Optional[Category] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CategorizationSuggestionRequest(BaseModel):
    description: Optional[str] = None
    merchant: Optional[str] = None
    amount: float = Field(default=0, ge=0)
    type: TransactionType

    @field_validator("description", "merchant")
    @classmethod
    def validate_optional_suggestion_fields(cls, value: Optional[str], info) -> Optional[str]:
        field_names = {
            "description": "Transaction description",
            "merchant": "Merchant",
        }
        return _clean_optional_string(value, field_names[info.field_name])

    @model_validator(mode="after")
    def validate_description_or_merchant(self):
        if not self.description and not self.merchant:
            raise ValueError("description or merchant is required")
        return self


class CategorizationSuggestion(BaseModel):
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    confidence: float
    method: str
    normalized_merchant: Optional[str] = None


class BulkCategorizationItem(BaseModel):
    transaction_id: Optional[str] = None
    description: Optional[str] = None
    merchant: Optional[str] = None
    amount: Optional[float] = Field(default=None, ge=0)
    type: Optional[TransactionType] = None

    @field_validator("transaction_id", "description", "merchant")
    @classmethod
    def validate_bulk_strings(cls, value: Optional[str], info) -> Optional[str]:
        field_names = {
            "transaction_id": "Transaction ID",
            "description": "Transaction description",
            "merchant": "Merchant",
        }
        return _clean_optional_string(value, field_names[info.field_name])

    @model_validator(mode="after")
    def validate_bulk_item(self):
        if not self.transaction_id and not self.description and not self.merchant:
            raise ValueError("transaction_id, description, or merchant is required")
        return self


class BulkCategorizationRequest(BaseModel):
    transactions: List[BulkCategorizationItem]
    apply: bool = True


class BulkCategorizationSuggestion(CategorizationSuggestion):
    transaction_id: Optional[str] = None
    applied: bool = False


class MerchantCategoryPattern(BaseModel):
    id: str
    user_id: str
    merchant_pattern: str
    category_id: str
    confidence: float
    usage_count: int
    created_at: datetime
    updated_at: datetime
    category: Optional[Category] = None

    model_config = ConfigDict(from_attributes=True)


class TransactionSummaryItem(BaseModel):
    type: TransactionType
    currency: str
    total: float


class TransactionAggregateResponse(BaseModel):
    count: int
    total_income: float
    total_expense: float


class SearchTransactionHit(BaseModel):
    id: str
    amount: float
    type: TransactionType
    description: str
    merchant: Optional[str] = None
    notes: Optional[str] = None
    date: datetime
    timestamp: Optional[int] = None
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    destination_account_id: Optional[str] = None
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SearchAggregations(BaseModel):
    total_amount: float
    count: int
    by_category: Dict[str, int]
    by_month: Dict[str, float]
    average_amount: float


class SearchResponse(BaseModel):
    hits: List[SearchTransactionHit]
    total: int
    query: str
    aggregations: SearchAggregations


class SearchReindexResponse(BaseModel):
    message: str
    indexed_count: int
    backend: str


class JobStatusResponse(BaseModel):
    id: str
    name: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class NLQueryParseResult(BaseModel):
    search: Optional[str] = None
    type: Optional[TransactionType] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    categories: List[str] = Field(default_factory=list)
    aggregate: str = "list"
    sort_by: str = "date_desc"
    original_query: str
    parsed: bool = False


class NaturalSearchResponse(SearchResponse):
    parsed_query: NLQueryParseResult
    interpretation: str


class MonthlyHistoryItem(BaseModel):
    month: str
    income: float
    expense: float


class PortfolioHolding(BaseModel):
    symbol: str
    name: str
    quantity: float
    avg_price: float
    current_price: float
    gain_pct: float


class PortfolioResponse(BaseModel):
    total_value: float
    holdings: List[PortfolioHolding]


class AuthUrlResponse(BaseModel):
    auth_url: str
    state: str


class GmailOAuthCallbackResponse(BaseModel):
    message: str
    email: Optional[str] = None


class SyncTriggerResponse(BaseModel):
    message: str
    account_id: str
    status: str


class SubscriptionFrequency(str, Enum):
    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


class SubscriptionBase(BaseModel):
    name: str
    amount: float = Field(gt=0)
    currency: str = "INR"
    frequency: SubscriptionFrequency
    category_id: Optional[str] = None
    account_id: Optional[str] = None
    next_due_date: Optional[date] = None
    last_paid_date: Optional[date] = None
    is_active: bool = True
    auto_detected: bool = False
    notes: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_subscription_name(cls, value: str) -> str:
        return _clean_required_string(value, "Subscription name")

    @field_validator("currency")
    @classmethod
    def validate_subscription_currency(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if len(cleaned) != 3 or not cleaned.isalpha():
            raise ValueError("Currency must be a 3-letter ISO code")
        return cleaned

    @field_validator("notes")
    @classmethod
    def validate_subscription_notes(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_string(value, "Notes")


class SubscriptionCreate(SubscriptionBase):
    pass


class SubscriptionUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = None
    frequency: Optional[SubscriptionFrequency] = None
    category_id: Optional[str] = None
    account_id: Optional[str] = None
    next_due_date: Optional[date] = None
    last_paid_date: Optional[date] = None
    is_active: Optional[bool] = None
    auto_detected: Optional[bool] = None
    notes: Optional[str] = None

    @field_validator("name", "notes")
    @classmethod
    def validate_subscription_optional_text(cls, value: Optional[str], info) -> Optional[str]:
        field_names = {
            "name": "Subscription name",
            "notes": "Notes",
        }
        return _clean_optional_string(value, field_names[info.field_name])

    @field_validator("currency")
    @classmethod
    def validate_subscription_optional_currency(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip().upper()
        if len(cleaned) != 3 or not cleaned.isalpha():
            raise ValueError("Currency must be a 3-letter ISO code")
        return cleaned


class Subscription(SubscriptionBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SubscriptionDetectionSuggestion(BaseModel):
    id: str
    name: str
    amount: float
    currency: str = "INR"
    frequency: SubscriptionFrequency
    category_id: Optional[str] = None
    account_id: Optional[str] = None
    next_due_date: Optional[date] = None
    last_paid_date: Optional[date] = None
    occurrences: int
    confidence: float = Field(ge=0, le=1)
    auto_detected: bool = True
    notes: Optional[str] = None


class SubscriptionCostBreakdown(BaseModel):
    currency: str
    monthly_cost: float


class SubscriptionSummaryResponse(BaseModel):
    monthly_cost: float
    active_count: int
    upcoming_renewals: List[Subscription]
    currency_breakdown: List[SubscriptionCostBreakdown] = []


class ReportType(str, Enum):
    monthly_summary = "monthly_summary"
    category_breakdown = "category_breakdown"
    cash_flow = "cash_flow"
    tax_report = "tax_report"


class ReportFormat(str, Enum):
    pdf = "pdf"
    csv = "csv"
    xlsx = "xlsx"


class ReportGenerateRequest(BaseModel):
    report_type: ReportType
    period_start: date
    period_end: date
    format: ReportFormat = ReportFormat.pdf

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_start > self.period_end:
            raise ValueError("period_start must be before or equal to period_end")
        return self


class ReportExportRequest(BaseModel):
    start_date: date
    end_date: date
    search: Optional[str] = None
    category_ids: Optional[List[str]] = None
    account_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_period(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must be before or equal to end_date")
        return self

    def export_filters(self) -> Dict[str, Any]:
        return {
            "search": self.search,
            "category_ids": self.category_ids,
            "account_id": self.account_id,
        }


class ReportJobResponse(BaseModel):
    id: str
    report_type: ReportType
    period_start: date
    period_end: date
    format: ReportFormat
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    download_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# --- Credit Score & Report Schemas ---

class CreditScoreResponse(BaseModel):
    score: Optional[int] = None
    provider: str = "cibil"
    score_range_min: int = 300
    score_range_max: int = 900
    classification: str = "unknown"
    report_date: Optional[date] = None
    fetched_at: Optional[datetime] = None
    has_report: bool = False


class CreditAccountResponse(BaseModel):
    id: str
    account_type: str
    institution: str
    account_number_masked: Optional[str] = None
    status: str
    opened_date: Optional[date] = None
    closed_date: Optional[date] = None
    sanctioned_amount: float = 0.0
    current_balance: float = 0.0
    credit_limit: float = 0.0
    emi_amount: float = 0.0
    interest_rate: float = 0.0
    days_past_due: int = 0
    is_overdue: bool = False
    last_payment_date: Optional[date] = None
    ownership: str = "individual"
    payment_history: Optional[List[Dict[str, Any]]] = None

    model_config = ConfigDict(from_attributes=True)


class CreditInquiryResponse(BaseModel):
    id: str
    institution: str
    inquiry_type: str
    purpose: Optional[str] = None
    inquiry_date: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)


class CreditReportSummary(BaseModel):
    total_accounts: int = 0
    active_accounts: int = 0
    closed_accounts: int = 0
    total_credit_limit: float = 0.0
    total_current_balance: float = 0.0
    credit_utilization_percent: float = 0.0
    overdue_accounts: int = 0
    total_emi_obligation: float = 0.0
    oldest_account_age_months: Optional[int] = None
    inquiries_last_6_months: int = 0


class CreditReportResponse(BaseModel):
    score: Optional[int] = None
    provider: str
    classification: str = "unknown"
    report_date: Optional[date] = None
    summary: CreditReportSummary
    accounts: List[CreditAccountResponse] = []
    inquiries: List[CreditInquiryResponse] = []
    recommendations: List[str] = []
    score_history: List[Dict[str, Any]] = []


class CreditConsentRequest(BaseModel):
    provider: str = "cibil"
    pan: Optional[str] = None
    consent_purpose: str = "credit_monitoring"


class CreditConsentResponse(BaseModel):
    consent_id: str
    status: str
    provider: str
    redirect_url: Optional[str] = None


class AccountDiscoveryRequest(BaseModel):
    pan: Optional[str] = None
    consent_id: Optional[str] = None


class DiscoveredAccount(BaseModel):
    source: str
    account_type: str
    institution: str
    account_number_masked: Optional[str] = None
    balance: Optional[float] = None
    credit_limit: Optional[float] = None
    already_linked: bool = False
    suggested_name: str = ""


class AccountDiscoveryResponse(BaseModel):
    discovered_accounts: List[DiscoveredAccount] = []
    source: str = "credit_report"
    consent_active: bool = False


class ImportAccountRequest(BaseModel):
    account_type: str
    institution: str
    account_number_masked: Optional[str] = None
    balance: float = 0.0
    credit_limit: Optional[float] = None
    name: Optional[str] = None
