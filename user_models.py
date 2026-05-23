import datetime
import enum
import uuid
from datetime import timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship

from database import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    role = Column(String, default=UserRole.EDITOR)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc), onupdate=lambda: datetime.datetime.now(timezone.utc))

    # Relationships
    accounts = relationship("Account", backref="owner", cascade="all, delete-orphan")
    categories = relationship("Category", backref="owner", cascade="all, delete-orphan")
    transactions = relationship("Transaction", backref="owner", cascade="all, delete-orphan")
    budgets = relationship("Budget", backref="user", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", backref="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", backref="user", cascade="all, delete-orphan")
    report_jobs = relationship("ReportJob", backref="user", cascade="all, delete-orphan")
    email_report_preferences = relationship("EmailReportPreference", backref="user", cascade="all, delete-orphan")
    investments = relationship("Investment", backref="user", cascade="all, delete-orphan")
    net_worth_snapshots = relationship("NetWorthSnapshot", backref="user", cascade="all, delete-orphan")
    health_score_snapshots = relationship("HealthScoreSnapshot", backref="user", cascade="all, delete-orphan")
    loans = relationship("Loan", backref="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, nullable=False)
    device_info = Column(String, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))
    revoked_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    user = relationship("User", back_populates="refresh_tokens")
