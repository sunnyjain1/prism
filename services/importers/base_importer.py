from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from schemas import TransactionCreate, TransactionType
import logging

logger = logging.getLogger(__name__)

# Optional: Import resolver chain for subclasses that want to use it
try:
    from .transaction_type_resolvers import TransactionTypeResolverChain
    RESOLVER_CHAIN_AVAILABLE = True
except ImportError:
    RESOLVER_CHAIN_AVAILABLE = False

class ImportResult:
    """Result of an import operation with detailed information."""
    def __init__(self):
        self.transactions: List[TransactionCreate] = []
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[str] = []
        self.metadata: Dict[str, Any] = {}
    
    def add_error(self, row_num: int, message: str, raw_data: Any = None):
        self.errors.append({
            "row": row_num,
            "message": message,
            "raw_data": str(raw_data) if raw_data else None
        })
    
    def add_warning(self, message: str):
        self.warnings.append(message)
    
    def is_valid(self) -> bool:
        return len(self.transactions) > 0 and len(self.errors) == 0

class BaseImporter(ABC):
    """
    Base class for all file importers with common functionality.
    
    Follows SOLID principles:
    - Single Responsibility: Base functionality for all importers
    - Open/Closed: Extensible via subclasses and resolver chain
    - Dependency Inversion: Can use TransactionTypeResolverChain abstraction
    """
    
    def __init__(self, name: str, supported_formats: List[str]):
        self.name = name
        self.supported_formats = supported_formats
        # Optional: Subclasses can override to use resolver chain
        self.type_resolver = None
        if RESOLVER_CHAIN_AVAILABLE:
            self.type_resolver = TransactionTypeResolverChain()
    
    @abstractmethod
    def parse(self, file_content: bytes, filename: Optional[str] = None, password: Optional[str] = None) -> ImportResult:
        """
        Parse file content and return ImportResult with transactions and errors.
        
        Args:
            file_content: Raw file bytes
            filename: Optional filename for format detection
            
        Returns:
            ImportResult with parsed transactions, errors, and metadata
        """
        pass
    
    @abstractmethod
    def can_handle(self, file_content: bytes, filename: Optional[str] = None, password: Optional[str] = None) -> bool:
        """
        Check if this importer can handle the given file.
        
        Args:
            file_content: Raw file bytes
            filename: Optional filename
            
        Returns:
            True if this importer can handle the file
        """
        pass
    
    def normalize_amount(self, amount: Any, currency: str = "INR") -> float:
        """Normalize amount from various formats to float."""
        if amount is None:
            return 0.0
        
        # Handle string amounts
        if isinstance(amount, str):
            # Remove currency symbols, commas, spaces
            cleaned = amount.replace('$', '').replace(',', '').replace(' ', '').strip()
            # Handle parentheses for negative amounts (accounting format)
            if cleaned.startswith('(') and cleaned.endswith(')'):
                cleaned = '-' + cleaned[1:-1]
            try:
                return float(cleaned)
            except ValueError:
                logger.warning(f"Could not parse amount: {amount}")
                return 0.0
        
        # Handle numeric types
        try:
            return float(amount)
        except (ValueError, TypeError):
            logger.warning(f"Could not convert amount to float: {amount}")
            return 0.0
    
    def parse_date(self, date_value: Any, formats: Optional[List[str]] = None) -> Optional[datetime]:
        """
        Parse date from various formats.
        
        Args:
            date_value: Date value (string, datetime, etc.)
            formats: Optional list of date format strings to try
            
        Returns:
            Parsed datetime or None
        """
        if date_value is None:
            return None
        
        # Already a datetime
        if isinstance(date_value, datetime):
            return date_value
        
        # 1. Try specific formats first if provided (more precise)
        if isinstance(date_value, str) and formats:
            for fmt in formats:
                try:
                    return datetime.strptime(date_value.strip(), fmt)
                except ValueError:
                    continue
        
        # 2. Try pandas to_datetime (handles many formats)
        try:
            import pandas as pd
            # Use dayfirst=True to prioritize DD/MM over MM/DD for ambiguous dates
            dt = pd.to_datetime(date_value, dayfirst=True)
            if isinstance(dt, pd.Timestamp):
                return dt.to_pydatetime()
            return dt
        except Exception:
            pass
        
        # 3. Try default fallbacks if no formats provided or they failed
        if isinstance(date_value, str):
            default_formats = [
                "%Y-%m-%d %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
                "%m/%d/%Y %H:%M:%S",
                "%Y-%m-%d",
                "%d/%m/%Y",
                "%m/%d/%Y",
                "%Y/%m/%d",
                "%m-%d-%Y",
                "%d-%m-%Y",
                "%B %d, %Y",
                "%b %d, %Y",
                "%d %B %Y",
                "%d %b %Y",
            ]
            
            for fmt in default_formats:
                try:
                    return datetime.strptime(date_value.strip(), fmt)
                except ValueError:
                    continue
        
        logger.warning(f"Could not parse date: {date_value}")
        return None
    
    def determine_transaction_type(
        self, 
        amount: float, 
        description: str = "", 
        debit_credit: Optional[str] = None,
        original_amount: Optional[float] = None
    ) -> TransactionType:
        """
        Determine transaction type from amount and context.
        
        Args:
            amount: Transaction amount (positive number, normalized)
            description: Transaction description
            debit_credit: Optional "Debit" or "Credit" indicator
            original_amount: Original amount before normalization (to check sign)
            
        Returns:
            TransactionType (income or expense)
        """
        # Use debit/credit indicator if available (most reliable)
        if debit_credit:
            debit_credit_lower = debit_credit.lower().strip()
            if any(keyword in debit_credit_lower for keyword in ['credit', 'deposit', 'income', 'receipt']):
                return TransactionType.income
            elif any(keyword in debit_credit_lower for keyword in ['debit', 'withdrawal', 'payment', 'charge', 'purchase']):
                return TransactionType.expense
        
        # Use original amount sign if available (very reliable for bank statements)
        if original_amount is not None:
            if original_amount < 0:
                return TransactionType.expense
            elif original_amount > 0:
                return TransactionType.income
        
        # Use description keywords
        desc_lower = description.lower()
        income_keywords = [
            'deposit', 'credit', 'refund', 'interest', 'dividend', 'salary', 
            'income', 'payroll', 'transfer in', 'reimbursement', 'bonus',
            'gift received', 'income', 'earnings'
        ]
        expense_keywords = [
            'purchase', 'payment', 'fee', 'charge', 'withdrawal', 'debit',
            'transfer out', 'bill', 'subscription', 'rent', 'utilities',
            'grocery', 'gas', 'restaurant', 'shopping'
        ]
        
        if any(keyword in desc_lower for keyword in income_keywords):
            return TransactionType.income
        if any(keyword in desc_lower for keyword in expense_keywords):
            return TransactionType.expense
        
        # Default: if we can't determine, default to expense (most common)
        # This should be overridden by bank-specific logic that knows the format
        return TransactionType.expense
    
    def clean_description(self, description: Any) -> str:
        """Clean and normalize transaction description."""
        if description is None:
            return "Transaction"
        
        desc = str(description).strip()
        if not desc or desc.lower() in ['nan', 'none', 'null', '']:
            return "Transaction"
        
        return desc
    
    def extract_merchant(self, description: str) -> Optional[str]:
        """
        Extract merchant name from description.
        This is a simple implementation - can be enhanced with ML/NLP.
        """
        if not description:
            return None
        
        # Remove common prefixes
        prefixes = ['ACH ', 'DEBIT ', 'CREDIT ', 'CHECK ', 'ATM ']
        cleaned = description
        for prefix in prefixes:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
        
        # Take first part (before common separators)
        parts = cleaned.split(' #')[0].split(' - ')[0].split(' | ')[0]
        return parts.strip() if parts.strip() else None
