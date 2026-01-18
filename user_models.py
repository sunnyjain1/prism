from sqlalchemy import Column, String, Boolean, Enum as sqlalchemyEnum
from .database import Base
from sqlalchemy.orm import relationship

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

    # Relationships
    accounts = relationship("Account", backref="owner", cascade="all, delete-orphan")
    categories = relationship("Category", backref="owner", cascade="all, delete-orphan")
    transactions = relationship("Transaction", backref="owner", cascade="all, delete-orphan")

