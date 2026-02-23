from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, BigInteger, UniqueConstraint, Boolean
from sqlalchemy.orm import relationship
from database import Base
import datetime
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
    date = Column(DateTime, default=datetime.datetime.utcnow)
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

