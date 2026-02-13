"""
Money Manager XLS/TSV importer - Refactored with SOLID principles.
Properly handles Income/Expense column for transaction type determination.
"""
import io
import pandas as pd
from typing import Optional, List, Dict
from datetime import datetime
import uuid
import logging
from .base_importer import BaseImporter, ImportResult
from .transaction_type_resolvers import TransactionTypeResolverChain
from schemas import TransactionCreate, TransactionType

logger = logging.getLogger(__name__)


class MoneyManagerImporter(BaseImporter):
    """
    Money Manager XLS/TSV importer.
    
    Follows SOLID principles:
    - Single Responsibility: Only handles Money Manager file parsing
    - Open/Closed: Extensible via TransactionTypeResolverChain
    - Dependency Inversion: Depends on TransactionTypeResolver abstraction
    """
    
    def __init__(self):
        super().__init__("Money Manager", ["xls", "xlsx", "tsv", "txt"])
        self.type_resolver = TransactionTypeResolverChain()
    
    def can_handle(self, file_content: bytes, filename: Optional[str] = None) -> bool:
        """Check if file is from Money Manager."""
        if filename:
            filename_lower = filename.lower()
            if any(ext in filename_lower for ext in ['.xls', '.xlsx', '.tsv', '.txt']):
                if 'money' in filename_lower or 'manager' in filename_lower:
                    return True
        
        # Try to detect from content
        try:
            df = self._try_read_file(file_content, nrows=5)
            if df is None:
                return False
            
            # Check for Money Manager columns
            columns = [col.lower() for col in df.columns]
            money_manager_indicators = [
                'date', 'account', 'category', 'subcategory', 
                'income/expense', 'description', 'amount'
            ]
            
            # If we find at least 4 Money Manager indicators, likely a match
            matches = sum(1 for indicator in money_manager_indicators 
                         if any(indicator in col for col in columns))
            return matches >= 4
            
        except Exception:
            return False
    
    def parse(self, file_content: bytes, filename: Optional[str] = None) -> ImportResult:
        """Parse Money Manager file and return ImportResult."""
        result = ImportResult()
        result.metadata["source"] = "Money Manager"
        
        try:
            # Read file
            df, file_type = self._read_file(file_content)
            
            if df is None or df.empty:
                result.add_error(0, "File is empty or could not be parsed")
                return result
            
            result.metadata["file_type"] = file_type
            result.metadata["total_rows"] = len(df)
            
            # Normalize column names
            df.columns = [col.strip().lower() for col in df.columns]
            
            # Detect columns
            column_mapping = self._detect_columns(df, result)
            if not column_mapping:
                return result  # Error already added
            
            # Parse transactions
            self._parse_transactions(df, column_mapping, result)
            
            result.metadata["parsed_count"] = len(result.transactions)
            result.metadata["error_count"] = len(result.errors)
            result.metadata["warning_count"] = len(result.warnings)
            
        except Exception as e:
            result.add_error(0, f"Failed to parse Money Manager file: {str(e)}")
            logger.exception("Error parsing Money Manager file")
        
        return result
    
    def _try_read_file(self, file_content: bytes, nrows: Optional[int] = None) -> Optional[pd.DataFrame]:
        """Try to read file in various formats."""
        # Try Excel first
        try:
            return pd.read_excel(io.BytesIO(file_content), nrows=nrows)
        except Exception:
            pass
        
        # Try TSV with UTF-16
        try:
            decoded = file_content.decode('utf-16')
            return pd.read_csv(io.StringIO(decoded), sep='\t', nrows=nrows)
        except Exception:
            pass
        
        # Try TSV with UTF-8
        try:
            decoded = file_content.decode('utf-8')
            return pd.read_csv(io.StringIO(decoded), sep='\t', nrows=nrows)
        except Exception:
            pass
        
        # Try CSV
        try:
            decoded = file_content.decode('utf-8')
            return pd.read_csv(io.StringIO(decoded), nrows=nrows)
        except Exception:
            pass
        
        return None
    
    def _read_file(self, file_content: bytes) -> tuple[Optional[pd.DataFrame], Optional[str]]:
        """Read file and return DataFrame with file type."""
        # Try Excel first
        try:
            df = pd.read_excel(io.BytesIO(file_content))
            return df, "Excel"
        except Exception as e1:
            logger.debug(f"Could not read as Excel: {e1}")
        
        # Try TSV with UTF-16
        try:
            decoded = file_content.decode('utf-16')
            df = pd.read_csv(io.StringIO(decoded), sep='\t')
            return df, "TSV (UTF-16)"
        except Exception as e2:
            logger.debug(f"Could not read as UTF-16 TSV: {e2}")
        
        # Try TSV with UTF-8
        try:
            decoded = file_content.decode('utf-8')
            df = pd.read_csv(io.StringIO(decoded), sep='\t')
            return df, "TSV (UTF-8)"
        except Exception as e3:
            logger.debug(f"Could not read as UTF-8 TSV: {e3}")
        
        # Try CSV
        try:
            decoded = file_content.decode('utf-8')
            df = pd.read_csv(io.StringIO(decoded))
            return df, "CSV"
        except Exception as e4:
            raise ValueError(f"Could not parse Money Manager file. Tried Excel, TSV (UTF-16), TSV (UTF-8), and CSV. Last error: {e4}")
    
    def _detect_columns(self, df: pd.DataFrame, result: ImportResult) -> Optional[Dict[str, str]]:
        """
        Detect and map required/optional columns.
        Returns column mapping dictionary or None if required columns missing.
        """
        column_mapping = {}
        
        # Required columns
        date_col = self._find_column(df, ['date', 'transaction date'])
        amount_col = self._find_column(df, ['amount', 'transaction amount', 'value'])
        
        if not date_col:
            result.add_error(0, "Could not find 'Date' column in Money Manager file")
            result.metadata["available_columns"] = list(df.columns)
            return None
        
        if not amount_col:
            result.add_error(0, "Could not find 'Amount' column in Money Manager file")
            result.metadata["available_columns"] = list(df.columns)
            return None
        
        column_mapping['date'] = date_col
        column_mapping['amount'] = amount_col
        
        # Optional columns
        column_mapping['type'] = self._find_column(df, ['income/expense', 'type', 'transaction type', 'income expense'])
        column_mapping['description'] = self._find_column(df, ['description', 'desc', 'memo', 'note', 'payee'])
        column_mapping['account'] = self._find_column(df, ['account', 'account name'])
        column_mapping['category'] = self._find_column(df, ['category', 'cat'])
        column_mapping['subcategory'] = self._find_column(df, ['subcategory', 'sub category'])
        column_mapping['note'] = self._find_column(df, ['note', 'notes', 'memo'])
        column_mapping['currency'] = self._find_column(df, ['currency', 'curr'])
        
        result.metadata["detected_columns"] = {k: v for k, v in column_mapping.items() if v}
        
        return column_mapping
    
    def _parse_transactions(
        self, 
        df: pd.DataFrame, 
        column_mapping: Dict[str, str],
        result: ImportResult
    ):
        """Parse all transactions from DataFrame."""
        for idx, row in df.iterrows():
            try:
                tx = self._parse_single_transaction(row, column_mapping, idx + 2)
                if tx:
                    result.transactions.append(tx)
            except Exception as e:
                result.add_error(idx + 2, f"Error parsing row: {str(e)}", row.to_dict())
                logger.exception(f"Error parsing Money Manager row {idx + 2}")
                continue
    
    def _parse_single_transaction(
        self,
        row: pd.Series,
        column_mapping: Dict[str, str],
        row_num: int
    ) -> Optional[TransactionCreate]:
        """Parse a single transaction row."""
        # Parse date
        date_col = column_mapping['date']
        date_val = row.get(date_col)
        if pd.isna(date_val):
            logger.warning(f"Row {row_num}: Missing date, skipping")
            return None
        
        dt = self.parse_date(date_val, [
            "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d",
            "%d-%m-%Y", "%m-%d-%Y", "%Y/%m/%d"
        ])
        
        if not dt:
            logger.warning(f"Row {row_num}: Could not parse date: {date_val}")
            return None
        
        # Parse amount
        amount_col = column_mapping['amount']
        amount_raw = row.get(amount_col)
        if pd.isna(amount_raw):
            logger.warning(f"Row {row_num}: Missing amount, skipping")
            return None
        
        original_amount = self.normalize_amount(amount_raw)
        amount = abs(original_amount)
        
        if amount == 0:
            logger.warning(f"Row {row_num}: Zero amount, skipping")
            return None
        
        # Resolve transaction type using resolver chain
        # This properly handles Income/Expense column
        row_data = row.to_dict()
        # Create column mapping with actual column names from DataFrame
        # The resolver needs to know which columns exist to check can_handle()
        resolver_column_mapping = {col: col for col in row_data.keys()}
        
        tx_type = self.type_resolver.resolve(
            amount=amount,
            row_data=row_data,
            column_mapping=resolver_column_mapping,
            original_amount=original_amount
        )
        
        # Parse description (maps file's 'Note' to schema's description)
        description = self._parse_description(row, column_mapping)
        
        # Parse notes (maps file's 'Description' to schema's notes)
        notes = self._parse_notes(row, column_mapping)
        
        # Extract merchant
        merchant = self.extract_merchant(description)
        
        # Extract category and account for auto-creation
        import_category = self._extract_category(row, column_mapping)
        import_account = self._extract_account(row, column_mapping)
        
        import_destination_account = None
        if tx_type == TransactionType.transfer:
            # For Money Manager transfers, the Category column often contains the destination account
            import_destination_account = import_category
            import_category = None # Transfers don't usually have a category in Prism schema
        
        # Create transaction
        tx = TransactionCreate(
            id=str(uuid.uuid4()),
            amount=amount,
            type=tx_type,
            description=description,
            merchant=merchant,
            date=dt,
            timestamp=int(dt.timestamp()),
            account_id=None,
            category_id=None,
            notes=notes
        )
        
        # Store category and account names for auto-creation
        if import_category:
            tx._import_category = import_category
        if import_account:
            tx._import_account = import_account
        if import_destination_account:
            tx._import_destination_account = import_destination_account
        
        return tx
    
    def _parse_description(self, row: pd.Series, column_mapping: Dict[str, str]) -> str:
        """Parse description from row - Swapped to use 'note' column."""
        note_col = column_mapping.get('note')
        if note_col and not pd.isna(row.get(note_col)):
            return self.clean_description(row.get(note_col))
        
        # Fallback to category
        cat_col = column_mapping.get('category')
        if cat_col and not pd.isna(row.get(cat_col)):
            return self.clean_description(row.get(cat_col))
        
        return "Transaction"
    
    def _parse_notes(self, row: pd.Series, column_mapping: Dict[str, str]) -> Optional[str]:
        """Parse notes from row - Swapped to use 'description' column."""
        notes_parts = []
        
        # Add description column if exists
        desc_col = column_mapping.get('description')
        if desc_col and not pd.isna(row.get(desc_col)):
            desc_val = str(row.get(desc_col)).strip()
            if desc_val and desc_val.lower() not in ['nan', 'none', '']:
                notes_parts.append(desc_val)
        
        # Add category/subcategory if exists
        cat_col = column_mapping.get('category')
        if cat_col and not pd.isna(row.get(cat_col)):
            cat_val = str(row.get(cat_col)).strip()
            if cat_val and cat_val.lower() not in ['nan', 'none', '']:
                subcat_col = column_mapping.get('subcategory')
                if subcat_col and not pd.isna(row.get(subcat_col)):
                    subcat_val = str(row.get(subcat_col)).strip()
                    if subcat_val and subcat_val.lower() not in ['nan', 'none', '']:
                        notes_parts.append(f"Category: {cat_val} / {subcat_val}")
                    else:
                        notes_parts.append(f"Category: {cat_val}")
        
        return ' | '.join(notes_parts) if notes_parts else None
    
    def _extract_category(self, row: pd.Series, column_mapping: Dict[str, str]) -> Optional[str]:
        """Extract category name for auto-creation."""
        cat_col = column_mapping.get('category')
        if cat_col and not pd.isna(row.get(cat_col)):
            cat_val = str(row.get(cat_col)).strip()
            if cat_val and cat_val.lower() not in ['nan', 'none', '']:
                return cat_val
        return None
    
    def _extract_account(self, row: pd.Series, column_mapping: Dict[str, str]) -> Optional[str]:
        """Extract account name for auto-creation."""
        acc_col = column_mapping.get('account')
        if acc_col and not pd.isna(row.get(acc_col)):
            acc_val = str(row.get(acc_col)).strip()
            if acc_val and acc_val.lower() not in ['nan', 'none', '']:
                return acc_val
        return None
    
    def _find_column(self, df: pd.DataFrame, possible_names: List[str]) -> Optional[str]:
        """Find a column by trying multiple possible names."""
        for name in possible_names:
            for col in df.columns:
                if name.lower() in col.lower():
                    return col
        return None
