from pydantic import BaseModel
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
    class Config:
        from_attributes = True

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

class TransactionCreate(TransactionBase):
    id: str

class Transaction(TransactionBase):
    id: str
    category: Optional[Category] = None
    class Config:
        from_attributes = True

class AccountBase(BaseModel):
    name: str
    type: AccountType
    currency: str = "USD"
    balance: float = 0.0
    billing_cycle_day: int = 1
    credit_limit: Optional[float] = None

class AccountCreate(AccountBase):
    id: str

class Account(AccountBase):
    id: str
    transactions: List[Transaction] = []
    class Config:
        from_attributes = True

