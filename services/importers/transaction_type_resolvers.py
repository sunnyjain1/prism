"""
Transaction Type Resolvers - SOLID principle implementation.
Each resolver handles a specific strategy for determining transaction type.
"""
from abc import ABC, abstractmethod
from typing import Optional, Any
from schemas import TransactionType
import logging

logger = logging.getLogger(__name__)


class TransactionTypeResolver(ABC):
    """
    Abstract base class for transaction type resolution strategies.
    Follows Strategy Pattern (SOLID: Open/Closed Principle).
    """
    
    @abstractmethod
    def resolve(
        self,
        amount: float,
        row_data: dict,
        column_mapping: dict
    ) -> TransactionType:
        """
        Resolve transaction type from available data.
        
        Args:
            amount: Normalized amount (always positive)
            row_data: Dictionary of row data
            column_mapping: Mapping of column names to their values
            
        Returns:
            TransactionType (income or expense)
        """
        pass
    
    @abstractmethod
    def can_handle(self, column_mapping: dict) -> bool:
        """
        Check if this resolver can handle the given column mapping.
        
        Args:
            column_mapping: Available columns in the data
            
        Returns:
            True if this resolver can handle the data
        """
        pass


class IncomeExpenseColumnResolver(TransactionTypeResolver):
    """
    Resolves transaction type from explicit Income/Expense column.
    This is the primary resolver for Money Manager format.
    """
    
    def can_handle(self, column_mapping: dict) -> bool:
        """Check if Income/Expense column exists."""
        type_column_names = [
            'income/expense', 'income_expense', 'type', 
            'transaction type', 'tx_type', 'income expense'
        ]
        
        for col_name in column_mapping.keys():
            col_lower = str(col_name).lower().strip()
            if any(type_name in col_lower for type_name in type_column_names):
                return True
        return False
    
    def resolve(
        self,
        amount: float,
        row_data: dict,
        column_mapping: dict
    ) -> TransactionType:
        """Resolve from Income/Expense column value."""
        type_column_names = [
            'income/expense', 'income_expense', 'type', 
            'transaction type', 'tx_type', 'income expense'
        ]
        
        # 1. Try to find the column from mapping
        type_col = None
        
        # Priority 1: Explicit mapping from importer
        for logical_name in ['type', 'income/expense', 'income_expense', 'income expense', 'transaction type']:
            if logical_name in column_mapping:
                type_col = column_mapping[logical_name]
                break
        
        # Priority 2: Substring search in mapping keys (backward compatibility/generic use)
        if not type_col:
            for col_name in column_mapping.keys():
                col_lower = str(col_name).lower().strip()
                if any(type_name in col_lower for type_name in type_column_names):
                    type_col = col_name
                    break
        
        if not type_col:
            logger.warning("Income/Expense column not found in mapping")
            return TransactionType.expense
        
        # Get the value
        type_value = row_data.get(type_col)
        if type_value is None:
            # Maybe the mapping key was already the physical column name
            # This handles cases where column_mapping is {col: col}
            type_value = row_data.get(type_col) # Redundant but clear
            
        if type_value is None:
            logger.warning(f"Type column '{type_col}' not found in row data")
            return TransactionType.expense
        
        # Normalize the value
        type_str = str(type_value).lower().strip()
        
        # Check for transfer first (most specific)
        # Money Manager uses: "Transfer-Out", "Transfer-In", "Transfer"
        transfer_indicators = ['transfer-out', 'transfer-in', 'transfer out', 'transfer in', 'transfer']
        if any(type_str == indicator or type_str.startswith(indicator) for indicator in transfer_indicators):
            return TransactionType.transfer

        # Check for income indicators
        income_indicators = ['income', 'credit', 'deposit', 'receipt', 'in']
        if type_str in income_indicators:
             return TransactionType.income

        # Check for expense indicators
        expense_indicators = ['expense', 'debit', 'withdrawal', 'payment', 'out', 'exp']
        if type_str in expense_indicators:
            return TransactionType.expense
        
        # Fallback to loose matching
        if 'transfer' in type_str:
            return TransactionType.transfer
        if 'income' in type_str:
            return TransactionType.income
        if 'expense' in type_str:
            return TransactionType.expense

        # If we can't determine, log and default to expense
        logger.warning(f"Could not determine type from value: {type_str}, defaulting to expense")
        return TransactionType.expense


class AmountSignResolver(TransactionTypeResolver):
    """
    Resolves transaction type from amount sign.
    Negative = expense, Positive = income.
    """
    
    def can_handle(self, column_mapping: dict) -> bool:
        """Can always handle if we have original amount."""
        return 'original_amount' in column_mapping
    
    def resolve(
        self,
        amount: float,
        row_data: dict,
        column_mapping: dict
    ) -> TransactionType:
        """Resolve from amount sign."""
        original_amount = column_mapping.get('original_amount', amount)
        
        if original_amount < 0:
            return TransactionType.expense
        elif original_amount > 0:
            return TransactionType.income
        else:
            # Zero amount - default to expense
            return TransactionType.expense


class DebitCreditColumnResolver(TransactionTypeResolver):
    """
    Resolves transaction type from Debit/Credit column.
    Common in bank statements.
    """
    
    def can_handle(self, column_mapping: dict) -> bool:
        """Check if Debit/Credit column exists."""
        debit_credit_names = ['debit', 'credit', 'dr', 'cr', 'debit/credit']
        
        for col_name in column_mapping.keys():
            col_lower = str(col_name).lower().strip()
            if any(name in col_lower for name in debit_credit_names):
                return True
        return False
    
    def resolve(
        self,
        amount: float,
        row_data: dict,
        column_mapping: dict
    ) -> TransactionType:
        """Resolve from Debit/Credit column."""
        debit_credit_names = ['debit', 'credit', 'dr', 'cr', 'debit/credit']
        
        # 1. Try to find column from mapping
        dc_col = None
        for logical_name in ['debit', 'credit', 'dr', 'cr', 'debit/credit']:
            if logical_name in column_mapping:
                dc_col = column_mapping[logical_name]
                break
                
        # 2. Substring search
        if not dc_col:
            for col_name in column_mapping.keys():
                col_lower = str(col_name).lower().strip()
                if any(name in col_lower for name in debit_credit_names):
                    dc_col = col_name
                    break
        
        if not dc_col:
            return TransactionType.expense
        
        value = str(row_data.get(dc_col, '')).lower().strip()
        
        if 'credit' in value or 'cr' in value:
            return TransactionType.income
        elif 'debit' in value or 'dr' in value:
            return TransactionType.expense
        
        return TransactionType.expense


class DescriptionKeywordResolver(TransactionTypeResolver):
    """
    Resolves transaction type from description keywords.
    Fallback strategy when no explicit type column exists.
    """
    
    def can_handle(self, column_mapping: dict) -> bool:
        """Can handle if description column exists."""
        desc_names = ['description', 'desc', 'memo', 'note', 'details']
        return any(name in str(col).lower() for col in column_mapping.keys() 
                  for name in desc_names)
    
    def resolve(
        self,
        amount: float,
        row_data: dict,
        column_mapping: dict
    ) -> TransactionType:
        """Resolve from description keywords."""
        desc_names = ['description', 'desc', 'memo', 'note', 'details']
        
        # Find description column
        desc_col = None
        for col_name in column_mapping.keys():
            col_lower = str(col_name).lower().strip()
            if any(name in col_lower for name in desc_names):
                desc_col = col_name
                break
        
        if not desc_col:
            return TransactionType.expense
        
        description = str(row_data.get(desc_col, '')).lower()
        
        # Income keywords
        income_keywords = [
            'deposit', 'credit', 'refund', 'interest', 'dividend', 
            'salary', 'income', 'payroll', 'reimbursement', 'bonus'
        ]
        if any(keyword in description for keyword in income_keywords):
            return TransactionType.income
        
        # Expense keywords
        expense_keywords = [
            'purchase', 'payment', 'fee', 'charge', 'withdrawal', 
            'debit', 'bill', 'subscription', 'rent'
        ]
        if any(keyword in description for keyword in expense_keywords):
            return TransactionType.expense
        
        return TransactionType.expense


class TransactionTypeResolverChain:
    """
    Chain of Responsibility pattern for transaction type resolution.
    Tries resolvers in order of priority.
    """
    
    def __init__(self):
        # Order matters: more specific resolvers first
        self.resolvers: list[TransactionTypeResolver] = [
            IncomeExpenseColumnResolver(),  # Highest priority for Money Manager
            DebitCreditColumnResolver(),     # For bank statements
            AmountSignResolver(),            # Common fallback
            DescriptionKeywordResolver(),    # Last resort
        ]
    
    def resolve(
        self,
        amount: float,
        row_data: dict,
        column_mapping: dict,
        original_amount: Optional[float] = None
    ) -> TransactionType:
        """
        Resolve transaction type using the chain of resolvers.
        
        Args:
            amount: Normalized amount (always positive)
            row_data: Dictionary of row data
            column_mapping: Mapping of column names
            original_amount: Original amount before normalization
            
        Returns:
            TransactionType
        """
        # Add original_amount to column_mapping for AmountSignResolver
        if original_amount is not None:
            column_mapping = {**column_mapping, 'original_amount': original_amount}
        
        # Try each resolver in order
        for resolver in self.resolvers:
            if resolver.can_handle(column_mapping):
                try:
                    result = resolver.resolve(amount, row_data, column_mapping)
                    logger.debug(f"Resolved transaction type using {resolver.__class__.__name__}: {result}")
                    return result
                except Exception as e:
                    logger.warning(f"Resolver {resolver.__class__.__name__} failed: {e}, trying next")
                    continue
        
        # If all resolvers fail, default to expense
        logger.warning("All transaction type resolvers failed, defaulting to expense")
        return TransactionType.expense
