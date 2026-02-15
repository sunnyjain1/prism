"""
Service to create missing categories and accounts during bulk import.
"""
from sqlalchemy.orm import Session
from typing import Optional, Dict
from models import Category, Account
from schemas import TransactionType, AccountType
from services.category_service import CategoryService
from services.account_service import AccountService
import uuid
import logging

logger = logging.getLogger(__name__)


class ImportEntityService:
    """Service to handle creation of missing categories and accounts during import."""
    
    def __init__(self, db: Session, owner_id: str):
        self.db = db
        self.owner_id = owner_id
        self.category_service = CategoryService(db)
        self.account_service = AccountService(db)
        
        # Cache for created entities to avoid duplicate lookups
        self._category_cache: Dict[str, str] = {}  # name -> id
        self._account_cache: Dict[str, str] = {}  # name -> id
    
    def get_or_create_category(
        self, 
        category_name: str, 
        transaction_type: TransactionType,
        color: Optional[str] = None
    ) -> Optional[str]:
        """
        Get existing category or create a new one.
        
        Args:
            category_name: Name of the category
            transaction_type: Type of transaction (income/expense)
            color: Optional color for the category
            
        Returns:
            Category ID or None if category_name is empty
        """
        if not category_name or not category_name.strip():
            return None
        
        category_name = category_name.strip()
        
        # Check cache first
        cache_key = f"{category_name.lower()}_{transaction_type.value}"
        if cache_key in self._category_cache:
            return self._category_cache[cache_key]
        
        # Check if category exists
        existing = self.db.query(Category).filter(
            Category.owner_id == self.owner_id,
            Category.name.ilike(category_name),
            Category.type == transaction_type.value
        ).first()
        
        if existing:
            self._category_cache[cache_key] = existing.id
            return existing.id
        
        # Create new category
        try:
            from schemas import CategoryCreate
            import random
            
            # Generate a color if not provided
            if not color:
                colors = [
                    "#10b981", "#6366f1", "#f59e0b", "#ef4444", "#8b5cf6",
                    "#06b6d4", "#ec4899", "#14b8a6", "#f97316", "#84cc16"
                ]
                color = random.choice(colors)
            
            category_data = CategoryCreate(
                id=str(uuid.uuid4()),
                name=category_name,
                type=transaction_type,
                color=color
            )
            
            new_category = self.category_service.create_category(category_data, self.owner_id)
            self._category_cache[cache_key] = new_category.id
            logger.info(f"Created new category: {category_name} ({transaction_type.value})")
            return new_category.id
            
        except Exception as e:
            logger.error(f"Failed to create category {category_name}: {e}")
            return None
    
    def get_or_create_account(
        self,
        account_name: str,
        account_type: Optional[AccountType] = None,
        currency: str = "INR"
    ) -> Optional[str]:
        """
        Get existing account or create a new one.
        
        Args:
            account_name: Name of the account
            account_type: Type of account (checking, savings, etc.)
            currency: Currency code
            
        Returns:
            Account ID or None if account_name is empty
        """
        if not account_name or not account_name.strip():
            return None
        
        account_name = account_name.strip()
        
        # Check cache first
        cache_key = account_name.lower()
        if cache_key in self._account_cache:
            return self._account_cache[cache_key]
        
        # Check if account exists
        existing = self.db.query(Account).filter(
            Account.owner_id == self.owner_id,
            Account.name.ilike(account_name)
        ).first()
        
        if existing:
            self._account_cache[cache_key] = existing.id
            return existing.id
        
        # Create new account
        try:
            from schemas import AccountCreate
            
            # Default to checking if type not specified
            if not account_type:
                account_type = AccountType.checking
            
            account_data = AccountCreate(
                id=str(uuid.uuid4()),
                name=account_name,
                type=account_type,
                currency=currency,
                balance=0.0,
                billing_cycle_day=1,
                credit_limit=None
            )
            
            new_account = self.account_service.create_account(account_data, self.owner_id)
            self._account_cache[cache_key] = new_account.id
            logger.info(f"Created new account: {account_name} ({account_type.value})")
            return new_account.id
            
        except Exception as e:
            logger.error(f"Failed to create account {account_name}: {e}")
            return None
    
    def infer_account_type_from_name(self, account_name: str) -> AccountType:
        """
        Infer account type from account name.
        
        Args:
            account_name: Name of the account
            
        Returns:
            Inferred AccountType
        """
        name_lower = account_name.lower()
        
        if any(keyword in name_lower for keyword in ['credit', 'card', 'visa', 'mastercard', 'amex']):
            return AccountType.credit
        elif any(keyword in name_lower for keyword in ['savings', 'save']):
            return AccountType.savings
        elif any(keyword in name_lower for keyword in ['investment', 'invest', 'brokerage', '401k', 'ira']):
            return AccountType.investment
        elif any(keyword in name_lower for keyword in ['cash', 'wallet']):
            return AccountType.cash
        else:
            return AccountType.checking
