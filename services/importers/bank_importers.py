"""
Bank-specific importers for CSV and Excel transaction files.
Each bank has different column formats and naming conventions.
"""
import io
import pandas as pd
from typing import Optional, List
from datetime import datetime
import uuid
import logging
from .base_importer import BaseImporter, ImportResult
from schemas import TransactionCreate, TransactionType

logger = logging.getLogger(__name__)


class ChaseBankImporter(BaseImporter):
    """Chase Bank CSV/Excel importer."""
    
    def __init__(self):
        super().__init__("Chase Bank", ["csv", "xlsx", "xls"])
        # Common Chase column names
        self.date_columns = ["Transaction Date", "Posting Date", "Date"]
        self.description_columns = ["Description", "Transaction Description", "Details"]
        self.amount_columns = ["Amount", "Transaction Amount"]
        self.type_columns = ["Type", "Transaction Type"]
        self.category_columns = ["Category", "Category Type"]
    
    def can_handle(self, file_content: bytes, filename: Optional[str] = None) -> bool:
        """Check if file is from Chase Bank."""
        if filename:
            filename_lower = filename.lower()
            if 'chase' in filename_lower:
                return True
        
        # Try to detect from content
        try:
            df = pd.read_csv(io.BytesIO(file_content), nrows=5)
            columns = [col.lower() for col in df.columns]
            # Chase typically has "Transaction Date" and "Description"
            if any('transaction date' in col or 'posting date' in col for col in columns):
                if any('description' in col for col in columns):
                    return True
        except Exception:
            pass
        
        return False
    
    def parse(self, file_content: bytes, filename: Optional[str] = None) -> ImportResult:
        result = ImportResult()
        result.metadata["bank"] = "Chase"
        
        try:
            # Try CSV first
            try:
                df = pd.read_csv(io.BytesIO(file_content))
            except Exception:
                # Try Excel
                df = pd.read_excel(io.BytesIO(file_content))
            
            # Normalize column names (lowercase, strip spaces)
            df.columns = [col.strip().lower() for col in df.columns]
            
            # Find date column
            date_col = None
            for col in self.date_columns:
                if col.lower() in df.columns:
                    date_col = col.lower()
                    break
            
            if not date_col:
                result.add_error(0, "Could not find date column in Chase file")
                return result
            
            # Find description column
            desc_col = None
            for col in self.description_columns:
                if col.lower() in df.columns:
                    desc_col = col.lower()
                    break
            
            if not desc_col:
                result.add_error(0, "Could not find description column in Chase file")
                return result
            
            # Find amount column
            amount_col = None
            for col in self.amount_columns:
                if col.lower() in df.columns:
                    amount_col = col.lower()
                    break
            
            if not amount_col:
                result.add_error(0, "Could not find amount column in Chase file")
                return result
            
            # Find type column (optional)
            type_col = None
            for col in self.type_columns:
                if col.lower() in df.columns:
                    type_col = col.lower()
                    break
            
            # Find category column (optional)
            category_col = None
            for col in self.category_columns:
                if col.lower() in df.columns:
                    category_col = col.lower()
                    break
            
            # Find account column (optional) - common names
            account_col = None
            account_columns = ["Account", "Account Name", "Account Number", "From Account", "To Account"]
            for col in account_columns:
                if col.lower() in df.columns:
                    account_col = col.lower()
                    break
            
            # Parse transactions
            for idx, row in df.iterrows():
                try:
                    # Parse date
                    date_val = row.get(date_col)
                    if pd.isna(date_val):
                        result.add_warning(f"Row {idx + 2}: Missing date, skipping")
                        continue
                    
                    dt = self.parse_date(date_val)
                    if not dt:
                        result.add_error(idx + 2, f"Could not parse date: {date_val}", row.to_dict())
                        continue
                    
                    # Parse amount
                    amount_raw = row.get(amount_col)
                    amount = self.normalize_amount(amount_raw)
                    if amount == 0:
                        result.add_warning(f"Row {idx + 2}: Zero amount, skipping")
                        continue
                    
                    # Determine transaction type
                    # Chase: negative amounts are debits (expenses), positive are credits (income)
                    original_amount = amount
                    is_negative = amount < 0
                    amount = abs(amount)
                    
                    if type_col and not pd.isna(row.get(type_col)):
                        tx_type = self.determine_transaction_type(
                            amount, 
                            str(row.get(desc_col, "")),
                            str(row.get(type_col, "")),
                            original_amount=original_amount
                        )
                    else:
                        # Use amount sign: negative = expense, positive = income
                        tx_type = TransactionType.expense if is_negative else TransactionType.income
                    
                    # Parse description
                    description = self.clean_description(row.get(desc_col))
                    merchant = self.extract_merchant(description)
                    
                    # Extract category and account information for auto-creation
                    import_category = None
                    if category_col and not pd.isna(row.get(category_col)):
                        cat_val = str(row.get(category_col)).strip()
                        if cat_val and cat_val.lower() not in ['nan', 'none', '']:
                            import_category = cat_val
                    
                    import_account = None
                    if account_col and not pd.isna(row.get(account_col)):
                        acc_val = str(row.get(account_col)).strip()
                        if acc_val and acc_val.lower() not in ['nan', 'none', '']:
                            import_account = acc_val
                    
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
                        notes=None
                    )
                    
                    # Store category and account names for auto-creation
                    if import_category:
                        tx._import_category = import_category
                    if import_account:
                        tx._import_account = import_account
                    
                    result.transactions.append(tx)
                    
                except Exception as e:
                    result.add_error(idx + 2, f"Error parsing row: {str(e)}", row.to_dict())
                    logger.exception(f"Error parsing Chase row {idx + 2}")
                    continue
            
            result.metadata["total_rows"] = len(df)
            result.metadata["parsed_count"] = len(result.transactions)
            
        except Exception as e:
            result.add_error(0, f"Failed to parse Chase file: {str(e)}")
            logger.exception("Error parsing Chase file")
        
        return result


class BankOfAmericaImporter(BaseImporter):
    """Bank of America CSV/Excel importer."""
    
    def __init__(self):
        super().__init__("Bank of America", ["csv", "xlsx", "xls"])
        self.date_columns = ["Date", "Transaction Date"]
        self.description_columns = ["Description", "Payee"]
        self.amount_columns = ["Amount", "Transaction Amount"]
        self.balance_columns = ["Balance", "Running Balance"]
    
    def can_handle(self, file_content: bytes, filename: Optional[str] = None) -> bool:
        if filename and 'bofa' in filename.lower() or 'bank of america' in filename.lower():
            return True
        
        try:
            df = pd.read_csv(io.BytesIO(file_content), nrows=5)
            columns = [col.lower() for col in df.columns]
            # BofA typically has "Date", "Description", "Amount"
            if 'date' in columns and 'description' in columns and 'amount' in columns:
                return True
        except Exception:
            pass
        
        return False
    
    def parse(self, file_content: bytes, filename: Optional[str] = None) -> ImportResult:
        result = ImportResult()
        result.metadata["bank"] = "Bank of America"
        
        try:
            try:
                df = pd.read_csv(io.BytesIO(file_content))
            except Exception:
                df = pd.read_excel(io.BytesIO(file_content))
            
            df.columns = [col.strip().lower() for col in df.columns]
            
            # Find columns
            date_col = next((col for col in self.date_columns if col.lower() in df.columns), None)
            desc_col = next((col for col in self.description_columns if col.lower() in df.columns), None)
            amount_col = next((col for col in self.amount_columns if col.lower() in df.columns), None)
            
            # Find optional columns
            category_col = next((col for col in ["category", "category type"] if col.lower() in df.columns), None)
            account_col = next((col for col in ["account", "account name"] if col.lower() in df.columns), None)
            
            if not all([date_col, desc_col, amount_col]):
                result.add_error(0, "Missing required columns in Bank of America file")
                return result
            
            for idx, row in df.iterrows():
                try:
                    date_val = row.get(date_col.lower())
                    if pd.isna(date_val):
                        continue
                    
                    dt = self.parse_date(date_val)
                    if not dt:
                        result.add_error(idx + 2, f"Could not parse date: {date_val}")
                        continue
                    
                    amount_raw = row.get(amount_col.lower())
                    amount = self.normalize_amount(amount_raw)
                    if amount == 0:
                        continue
                    
                    # BofA: negative = expense, positive = income
                    original_amount = amount
                    is_negative = amount < 0
                    amount = abs(amount)
                    # Use amount sign: negative = expense, positive = income
                    tx_type = TransactionType.expense if is_negative else TransactionType.income
                    
                    description = self.clean_description(row.get(desc_col.lower()))
                    merchant = self.extract_merchant(description)
                    
                    # Extract category and account information for auto-creation
                    import_category = None
                    if category_col and not pd.isna(row.get(category_col.lower())):
                        cat_val = str(row.get(category_col.lower())).strip()
                        if cat_val and cat_val.lower() not in ['nan', 'none', '']:
                            import_category = cat_val
                    
                    import_account = None
                    if account_col and not pd.isna(row.get(account_col.lower())):
                        acc_val = str(row.get(account_col.lower())).strip()
                        if acc_val and acc_val.lower() not in ['nan', 'none', '']:
                            import_account = acc_val
                    
                    tx = TransactionCreate(
                        id=str(uuid.uuid4()),
                        amount=amount,
                        type=tx_type,
                        description=description,
                        merchant=merchant,
                        date=dt,
                        timestamp=int(dt.timestamp()),
                        account_id=None,
                        category_id=None
                    )
                    
                    # Store category and account names for auto-creation
                    if import_category:
                        tx._import_category = import_category
                    if import_account:
                        tx._import_account = import_account
                    
                    result.transactions.append(tx)
                    
                except Exception as e:
                    result.add_error(idx + 2, f"Error parsing row: {str(e)}")
                    continue
            
            result.metadata["total_rows"] = len(df)
            result.metadata["parsed_count"] = len(result.transactions)
            
        except Exception as e:
            result.add_error(0, f"Failed to parse Bank of America file: {str(e)}")
            logger.exception("Error parsing BofA file")
        
        return result


class WellsFargoImporter(BaseImporter):
    """Wells Fargo CSV/Excel importer."""
    
    def __init__(self):
        super().__init__("Wells Fargo", ["csv", "xlsx", "xls"])
        self.date_columns = ["Date", "Transaction Date"]
        self.description_columns = ["Description", "Transaction Description"]
        self.amount_columns = ["Amount", "Debit", "Credit"]
    
    def can_handle(self, file_content: bytes, filename: Optional[str] = None) -> bool:
        if filename and ('wells' in filename.lower() or 'wf' in filename.lower()):
            return True
        
        try:
            df = pd.read_csv(io.BytesIO(file_content), nrows=5)
            columns = [col.lower() for col in df.columns]
            # Wells Fargo often has separate Debit and Credit columns
            if ('debit' in columns or 'credit' in columns) and 'date' in columns:
                return True
        except Exception:
            pass
        
        return False
    
    def parse(self, file_content: bytes, filename: Optional[str] = None) -> ImportResult:
        result = ImportResult()
        result.metadata["bank"] = "Wells Fargo"
        
        try:
            try:
                df = pd.read_csv(io.BytesIO(file_content))
            except Exception:
                df = pd.read_excel(io.BytesIO(file_content))
            
            df.columns = [col.strip().lower() for col in df.columns]
            
            date_col = next((col for col in self.date_columns if col.lower() in df.columns), None)
            desc_col = next((col for col in self.description_columns if col.lower() in df.columns), None)
            
            # Find optional columns
            category_col = next((col for col in ["category", "category type"] if col.lower() in df.columns), None)
            account_col = next((col for col in ["account", "account name"] if col.lower() in df.columns), None)
            
            if not date_col or not desc_col:
                result.add_error(0, "Missing required columns in Wells Fargo file")
                return result
            
            # Check for separate debit/credit columns or single amount column
            has_debit = 'debit' in df.columns
            has_credit = 'credit' in df.columns
            amount_col = next((col for col in self.amount_columns if col.lower() in df.columns), None)
            
            for idx, row in df.iterrows():
                try:
                    date_val = row.get(date_col.lower())
                    if pd.isna(date_val):
                        continue
                    
                    dt = self.parse_date(date_val)
                    if not dt:
                        result.add_error(idx + 2, f"Could not parse date: {date_val}")
                        continue
                    
                    # Handle debit/credit columns
                    amount = 0.0
                    tx_type = TransactionType.expense
                    
                    if has_debit and has_credit:
                        debit = self.normalize_amount(row.get('debit', 0))
                        credit = self.normalize_amount(row.get('credit', 0))
                        if debit > 0:
                            amount = debit
                            tx_type = TransactionType.expense
                        elif credit > 0:
                            amount = credit
                            tx_type = TransactionType.income
                        else:
                            continue
                    elif amount_col:
                        amount_raw = row.get(amount_col.lower())
                        amount = self.normalize_amount(amount_raw)
                        if amount == 0:
                            continue
                        tx_type = TransactionType.expense if amount < 0 else TransactionType.income
                        amount = abs(amount)
                    else:
                        result.add_error(idx + 2, "Could not find amount column")
                        continue
                    
                    description = self.clean_description(row.get(desc_col.lower()))
                    merchant = self.extract_merchant(description)
                    
                    # Extract category and account information for auto-creation
                    import_category = None
                    if category_col and not pd.isna(row.get(category_col.lower())):
                        cat_val = str(row.get(category_col.lower())).strip()
                        if cat_val and cat_val.lower() not in ['nan', 'none', '']:
                            import_category = cat_val
                    
                    import_account = None
                    if account_col and not pd.isna(row.get(account_col.lower())):
                        acc_val = str(row.get(account_col.lower())).strip()
                        if acc_val and acc_val.lower() not in ['nan', 'none', '']:
                            import_account = acc_val
                    
                    tx = TransactionCreate(
                        id=str(uuid.uuid4()),
                        amount=amount,
                        type=tx_type,
                        description=description,
                        merchant=merchant,
                        date=dt,
                        timestamp=int(dt.timestamp()),
                        account_id=None,
                        category_id=None
                    )
                    
                    # Store category and account names for auto-creation
                    if import_category:
                        tx._import_category = import_category
                    if import_account:
                        tx._import_account = import_account
                    
                    result.transactions.append(tx)
                    
                except Exception as e:
                    result.add_error(idx + 2, f"Error parsing row: {str(e)}")
                    continue
            
            result.metadata["total_rows"] = len(df)
            result.metadata["parsed_count"] = len(result.transactions)
            
        except Exception as e:
            result.add_error(0, f"Failed to parse Wells Fargo file: {str(e)}")
            logger.exception("Error parsing Wells Fargo file")
        
        return result


class GenericBankImporter(BaseImporter):
    """Generic importer for unknown bank formats - tries to auto-detect columns."""
    
    def __init__(self):
        super().__init__("Generic Bank", ["csv", "xlsx", "xls"])
    
    def can_handle(self, file_content: bytes, filename: Optional[str] = None) -> bool:
        # Generic importer can handle any CSV/Excel file
        return True
    
    def parse(self, file_content: bytes, filename: Optional[str] = None) -> ImportResult:
        result = ImportResult()
        result.metadata["bank"] = "Generic"
        
        try:
            # Try CSV first
            try:
                df = pd.read_csv(io.BytesIO(file_content))
            except Exception:
                # Try Excel
                df = pd.read_excel(io.BytesIO(file_content))
            
            df.columns = [col.strip().lower() for col in df.columns]
            
            # Auto-detect columns
            date_col = None
            desc_col = None
            amount_col = None
            category_col = None
            account_col = None
            
            # Find date column
            date_keywords = ['date', 'transaction date', 'posting date', 'trans date']
            for col in df.columns:
                if any(keyword in col for keyword in date_keywords):
                    date_col = col
                    break
            
            # Find description column
            desc_keywords = ['description', 'desc', 'details', 'memo', 'payee', 'merchant', 'vendor']
            for col in df.columns:
                if any(keyword in col for keyword in desc_keywords):
                    desc_col = col
                    break
            
            # Find amount column
            amount_keywords = ['amount', 'amt', 'transaction amount', 'value', 'total']
            for col in df.columns:
                if any(keyword in col for keyword in amount_keywords):
                    amount_col = col
                    break
            
            # Find category column (optional)
            category_keywords = ['category', 'cat', 'type']
            for col in df.columns:
                if any(keyword in col for keyword in category_keywords) and col != date_col:
                    category_col = col
                    break
            
            # Find account column (optional)
            account_keywords = ['account', 'acct', 'from account', 'to account']
            for col in df.columns:
                if any(keyword in col for keyword in account_keywords):
                    account_col = col
                    break
            
            if not date_col or not amount_col:
                result.add_error(0, "Could not auto-detect required columns (date and amount)")
                result.metadata["available_columns"] = list(df.columns)
                return result
            
            if not desc_col:
                result.add_warning("Could not find description column, using 'Transaction' as default")
                desc_col = None
            
            # Parse transactions
            for idx, row in df.iterrows():
                try:
                    date_val = row.get(date_col) if date_col else None
                    if pd.isna(date_val) if date_val is not None else True:
                        continue
                    
                    dt = self.parse_date(date_val)
                    if not dt:
                        result.add_error(idx + 2, f"Could not parse date: {date_val}")
                        continue
                    
                    amount_raw = row.get(amount_col)
                    amount = self.normalize_amount(amount_raw)
                    if amount == 0:
                        continue
                    
                    # Default: negative = expense, positive = income
                    is_negative = amount < 0
                    amount = abs(amount)
                    tx_type = TransactionType.expense if is_negative else TransactionType.income
                    
                    description = self.clean_description(
                        row.get(desc_col) if desc_col else "Transaction"
                    )
                    merchant = self.extract_merchant(description)
                    
                    # Extract category and account information for auto-creation
                    import_category = None
                    if category_col and not pd.isna(row.get(category_col)):
                        cat_val = str(row.get(category_col)).strip()
                        if cat_val and cat_val.lower() not in ['nan', 'none', '']:
                            import_category = cat_val
                    
                    import_account = None
                    if account_col and not pd.isna(row.get(account_col)):
                        acc_val = str(row.get(account_col)).strip()
                        if acc_val and acc_val.lower() not in ['nan', 'none', '']:
                            import_account = acc_val
                    
                    tx = TransactionCreate(
                        id=str(uuid.uuid4()),
                        amount=amount,
                        type=tx_type,
                        description=description,
                        merchant=merchant,
                        date=dt,
                        timestamp=int(dt.timestamp()),
                        account_id=None,
                        category_id=None
                    )
                    
                    # Store category and account names for auto-creation
                    if import_category:
                        tx._import_category = import_category
                    if import_account:
                        tx._import_account = import_account
                    
                    result.transactions.append(tx)
                    
                except Exception as e:
                    result.add_error(idx + 2, f"Error parsing row: {str(e)}")
                    continue
            
            result.metadata["total_rows"] = len(df)
            result.metadata["parsed_count"] = len(result.transactions)
            result.metadata["detected_columns"] = {
                "date": date_col,
                "description": desc_col,
                "amount": amount_col
            }
            
        except Exception as e:
            result.add_error(0, f"Failed to parse file: {str(e)}")
            logger.exception("Error parsing generic bank file")
        
        return result
