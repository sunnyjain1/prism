from sqlalchemy import Column, String, Boolean, DateTime, Enum as sqlalchemyEnum
from database import Base
from sqlalchemy.orm import relationship
import datetime
from datetime import timezone

import enum
import uuid

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
