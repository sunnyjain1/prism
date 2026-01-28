"""
Credit card PDF statement importers.
Each credit card issuer has different PDF layouts and formats.
"""
import io
import re
from typing import Optional, List, Dict, Tuple
from datetime import datetime
import uuid
import logging
import pdfplumber
from .base_importer import BaseImporter, ImportResult
from schemas import TransactionCreate, TransactionType

logger = logging.getLogger(__name__)


class ChaseCreditCardPDFImporter(BaseImporter):
    """Chase credit card PDF statement importer."""
    
    def __init__(self):
        super().__init__("Chase Credit Card", ["pdf"])
    
    def can_handle(self, file_content: bytes, filename: Optional[str] = None) -> bool:
        """Detect Chase credit card PDF."""
        if filename:
            filename_lower = filename.lower()
            if 'chase' in filename_lower and 'pdf' in filename_lower:
                return True
        
        # Try to detect from PDF content
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                first_page_text = pdf.pages[0].extract_text() or ""
                if 'chase' in first_page_text.lower() and 'credit card' in first_page_text.lower():
                    return True
        except Exception:
            pass
        
        return False
    
    def parse(self, file_content: bytes, filename: Optional[str] = None) -> ImportResult:
        result = ImportResult()
        result.metadata["bank"] = "Chase Credit Card"
        result.metadata["file_type"] = "PDF"
        
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                transactions = []
                
                for page_num, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if not text:
                        continue
                    
                    # Extract transactions from text
                    # Chase format: Date Description Amount
                    # Example: "12/15 AMAZON.COM PURCHASE $45.67"
                    
                    # Try table extraction first (more reliable)
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            for row_idx, row in enumerate(table):
                                if row_idx == 0:  # Skip header
                                    continue
                                
                                if len(row) < 3:
                                    continue
                                
                                try:
                                    tx = self._parse_table_row(row, page_num + 1, row_idx + 1)
                                    if tx:
                                        transactions.append(tx)
                                except Exception as e:
                                    logger.debug(f"Error parsing table row: {e}")
                                    continue
                    
                    # Fallback to text parsing
                    if not transactions:
                        text_txs = self._parse_text_transactions(text, page_num + 1)
                        transactions.extend(text_txs)
                
                result.transactions = transactions
                result.metadata["pages_processed"] = len(pdf.pages)
                result.metadata["parsed_count"] = len(transactions)
                
        except Exception as e:
            result.add_error(0, f"Failed to parse Chase PDF: {str(e)}")
            logger.exception("Error parsing Chase PDF")
        
        return result
    
    def _parse_table_row(self, row: List, page: int, row_num: int) -> Optional[TransactionCreate]:
        """Parse a table row from Chase PDF."""
        # Chase table typically has: Date, Description, Amount
        if len(row) < 3:
            return None
        
        # Find date column (usually first)
        date_str = str(row[0]).strip() if row[0] else None
        if not date_str or date_str.lower() in ['date', 'transaction date', '']:
            return None
        
        # Find amount column (usually last)
        amount_str = None
        for i in range(len(row) - 1, -1, -1):
            if row[i] and '$' in str(row[i]) or re.search(r'[\d,]+\.\d{2}', str(row[i])):
                amount_str = str(row[i]).strip()
                break
        
        if not amount_str:
            return None
        
        # Description is everything in between
        desc_parts = []
        for i in range(1, len(row) - 1):
            if row[i] and str(row[i]).strip():
                desc_parts.append(str(row[i]).strip())
        description = ' '.join(desc_parts) if desc_parts else "Transaction"
        
        # Parse date
        dt = self.parse_date(date_str, ["%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"])
        if not dt:
            return None
        
        # Parse amount
        amount = self.normalize_amount(amount_str)
        if amount == 0:
            return None
        
        # Credit card: positive amounts are charges (expenses)
        tx_type = TransactionType.expense
        amount = abs(amount)
        
        merchant = self.extract_merchant(description)
        
        return TransactionCreate(
            id=str(uuid.uuid4()),
            amount=amount,
            type=tx_type,
            description=self.clean_description(description),
            merchant=merchant,
            date=dt,
            timestamp=int(dt.timestamp()),
            account_id=None,
            category_id=None
        )
    
    def _parse_text_transactions(self, text: str, page: int) -> List[TransactionCreate]:
        """Parse transactions from PDF text (fallback method)."""
        transactions = []
        
        # Pattern: Date Description Amount
        # Example: "12/15 AMAZON.COM $45.67"
        pattern = r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+([A-Z\s\.]+?)\s+(\$?[\d,]+\.\d{2})'
        
        matches = re.finditer(pattern, text, re.MULTILINE)
        for match in matches:
            try:
                date_str = match.group(1)
                description = match.group(2).strip()
                amount_str = match.group(3)
                
                dt = self.parse_date(date_str)
                if not dt:
                    continue
                
                amount = self.normalize_amount(amount_str)
                if amount == 0:
                    continue
                
                tx = TransactionCreate(
                    id=str(uuid.uuid4()),
                    amount=abs(amount),
                    type=TransactionType.expense,
                    description=self.clean_description(description),
                    merchant=self.extract_merchant(description),
                    date=dt,
                    timestamp=int(dt.timestamp()),
                    account_id=None,
                    category_id=None
                )
                
                transactions.append(tx)
            except Exception as e:
                logger.debug(f"Error parsing text transaction: {e}")
                continue
        
        return transactions


class AmexCreditCardPDFImporter(BaseImporter):
    """American Express credit card PDF statement importer."""
    
    def __init__(self):
        super().__init__("American Express", ["pdf"])
    
    def can_handle(self, file_content: bytes, filename: Optional[str] = None) -> bool:
        if filename:
            filename_lower = filename.lower()
            if ('amex' in filename_lower or 'american express' in filename_lower) and 'pdf' in filename_lower:
                return True
        
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                first_page_text = pdf.pages[0].extract_text() or ""
                if 'american express' in first_page_text.lower() or 'amex' in first_page_text.lower():
                    return True
        except Exception:
            pass
        
        return False
    
    def parse(self, file_content: bytes, filename: Optional[str] = None) -> ImportResult:
        result = ImportResult()
        result.metadata["bank"] = "American Express"
        result.metadata["file_type"] = "PDF"
        
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                transactions = []
                
                for page in pdf.pages:
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            for row_idx, row in enumerate(table):
                                if row_idx == 0:
                                    continue
                                
                                if len(row) < 3:
                                    continue
                                
                                try:
                                    tx = self._parse_table_row(row)
                                    if tx:
                                        transactions.append(tx)
                                except Exception:
                                    continue
                
                result.transactions = transactions
                result.metadata["pages_processed"] = len(pdf.pages)
                result.metadata["parsed_count"] = len(transactions)
                
        except Exception as e:
            result.add_error(0, f"Failed to parse Amex PDF: {str(e)}")
            logger.exception("Error parsing Amex PDF")
        
        return result
    
    def _parse_table_row(self, row: List) -> Optional[TransactionCreate]:
        """Parse Amex table row."""
        if len(row) < 3:
            return None
        
        # Amex format: Date, Description, Amount
        date_str = str(row[0]).strip() if row[0] else None
        if not date_str:
            return None
        
        # Find amount (look for $ or number with decimals)
        amount_str = None
        for cell in reversed(row):
            cell_str = str(cell).strip()
            if '$' in cell_str or re.search(r'[\d,]+\.\d{2}', cell_str):
                amount_str = cell_str
                break
        
        if not amount_str:
            return None
        
        # Description is everything else
        desc_parts = [str(cell).strip() for cell in row[1:-1] if cell and str(cell).strip()]
        description = ' '.join(desc_parts) if desc_parts else "Transaction"
        
        dt = self.parse_date(date_str)
        if not dt:
            return None
        
        amount = self.normalize_amount(amount_str)
        if amount == 0:
            return None
        
        return TransactionCreate(
            id=str(uuid.uuid4()),
            amount=abs(amount),
            type=TransactionType.expense,
            description=self.clean_description(description),
            merchant=self.extract_merchant(description),
            date=dt,
            timestamp=int(dt.timestamp()),
            account_id=None,
            category_id=None
        )


class CitiCreditCardPDFImporter(BaseImporter):
    """Citi credit card PDF statement importer."""
    
    def __init__(self):
        super().__init__("Citi Credit Card", ["pdf"])
    
    def can_handle(self, file_content: bytes, filename: Optional[str] = None) -> bool:
        if filename:
            filename_lower = filename.lower()
            if 'citi' in filename_lower and 'pdf' in filename_lower:
                return True
        
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                first_page_text = pdf.pages[0].extract_text() or ""
                if 'citibank' in first_page_text.lower() or 'citi' in first_page_text.lower():
                    return True
        except Exception:
            pass
        
        return False
    
    def parse(self, file_content: bytes, filename: Optional[str] = None) -> ImportResult:
        result = ImportResult()
        result.metadata["bank"] = "Citi"
        result.metadata["file_type"] = "PDF"
        
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                transactions = []
                
                for page in pdf.pages:
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            for row_idx, row in enumerate(table):
                                if row_idx == 0:
                                    continue
                                
                                try:
                                    tx = self._parse_table_row(row)
                                    if tx:
                                        transactions.append(tx)
                                except Exception:
                                    continue
                
                result.transactions = transactions
                result.metadata["pages_processed"] = len(pdf.pages)
                result.metadata["parsed_count"] = len(transactions)
                
        except Exception as e:
            result.add_error(0, f"Failed to parse Citi PDF: {str(e)}")
            logger.exception("Error parsing Citi PDF")
        
        return result
    
    def _parse_table_row(self, row: List) -> Optional[TransactionCreate]:
        """Parse Citi table row."""
        if len(row) < 3:
            return None
        
        date_str = str(row[0]).strip() if row[0] else None
        if not date_str:
            return None
        
        amount_str = None
        for cell in reversed(row):
            cell_str = str(cell).strip()
            if '$' in cell_str or re.search(r'[\d,]+\.\d{2}', cell_str):
                amount_str = cell_str
                break
        
        if not amount_str:
            return None
        
        desc_parts = [str(cell).strip() for cell in row[1:-1] if cell and str(cell).strip()]
        description = ' '.join(desc_parts) if desc_parts else "Transaction"
        
        dt = self.parse_date(date_str)
        if not dt:
            return None
        
        amount = self.normalize_amount(amount_str)
        if amount == 0:
            return None
        
        return TransactionCreate(
            id=str(uuid.uuid4()),
            amount=abs(amount),
            type=TransactionType.expense,
            description=self.clean_description(description),
            merchant=self.extract_merchant(description),
            date=dt,
            timestamp=int(dt.timestamp()),
            account_id=None,
            category_id=None
        )


class CapitalOneCreditCardPDFImporter(BaseImporter):
    """Capital One credit card PDF statement importer."""
    
    def __init__(self):
        super().__init__("Capital One", ["pdf"])
    
    def can_handle(self, file_content: bytes, filename: Optional[str] = None) -> bool:
        if filename:
            filename_lower = filename.lower()
            if ('capital one' in filename_lower or 'capitalone' in filename_lower) and 'pdf' in filename_lower:
                return True
        
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                first_page_text = pdf.pages[0].extract_text() or ""
                if 'capital one' in first_page_text.lower():
                    return True
        except Exception:
            pass
        
        return False
    
    def parse(self, file_content: bytes, filename: Optional[str] = None) -> ImportResult:
        result = ImportResult()
        result.metadata["bank"] = "Capital One"
        result.metadata["file_type"] = "PDF"
        
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                transactions = []
                
                for page in pdf.pages:
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            for row_idx, row in enumerate(table):
                                if row_idx == 0:
                                    continue
                                
                                try:
                                    tx = self._parse_table_row(row)
                                    if tx:
                                        transactions.append(tx)
                                except Exception:
                                    continue
                
                result.transactions = transactions
                result.metadata["pages_processed"] = len(pdf.pages)
                result.metadata["parsed_count"] = len(transactions)
                
        except Exception as e:
            result.add_error(0, f"Failed to parse Capital One PDF: {str(e)}")
            logger.exception("Error parsing Capital One PDF")
        
        return result
    
    def _parse_table_row(self, row: List) -> Optional[TransactionCreate]:
        """Parse Capital One table row."""
        if len(row) < 3:
            return None
        
        date_str = str(row[0]).strip() if row[0] else None
        if not date_str:
            return None
        
        amount_str = None
        for cell in reversed(row):
            cell_str = str(cell).strip()
            if '$' in cell_str or re.search(r'[\d,]+\.\d{2}', cell_str):
                amount_str = cell_str
                break
        
        if not amount_str:
            return None
        
        desc_parts = [str(cell).strip() for cell in row[1:-1] if cell and str(cell).strip()]
        description = ' '.join(desc_parts) if desc_parts else "Transaction"
        
        dt = self.parse_date(date_str)
        if not dt:
            return None
        
        amount = self.normalize_amount(amount_str)
        if amount == 0:
            return None
        
        return TransactionCreate(
            id=str(uuid.uuid4()),
            amount=abs(amount),
            type=TransactionType.expense,
            description=self.clean_description(description),
            merchant=self.extract_merchant(description),
            date=dt,
            timestamp=int(dt.timestamp()),
            account_id=None,
            category_id=None
        )


class GenericCreditCardPDFImporter(BaseImporter):
    """Generic credit card PDF importer - tries to extract transactions from any PDF."""
    
    def __init__(self):
        super().__init__("Generic Credit Card", ["pdf"])
    
    def can_handle(self, file_content: bytes, filename: Optional[str] = None) -> bool:
        # Can handle any PDF file
        return filename and filename.lower().endswith('.pdf')
    
    def parse(self, file_content: bytes, filename: Optional[str] = None) -> ImportResult:
        result = ImportResult()
        result.metadata["bank"] = "Generic Credit Card"
        result.metadata["file_type"] = "PDF"
        
        try:
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                transactions = []
                
                for page in pdf.pages:
                    # Try table extraction
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            # Skip header rows
                            for row_idx, row in enumerate(table[1:], start=1):
                                if len(row) < 3:
                                    continue
                                
                                try:
                                    tx = self._parse_generic_row(row)
                                    if tx:
                                        transactions.append(tx)
                                except Exception:
                                    continue
                    
                    # Fallback to text extraction
                    if not transactions:
                        text = page.extract_text()
                        if text:
                            text_txs = self._parse_text(text)
                            transactions.extend(text_txs)
                
                result.transactions = transactions
                result.metadata["pages_processed"] = len(pdf.pages)
                result.metadata["parsed_count"] = len(transactions)
                
        except Exception as e:
            result.add_error(0, f"Failed to parse PDF: {str(e)}")
            logger.exception("Error parsing generic PDF")
        
        return result
    
    def _parse_generic_row(self, row: List) -> Optional[TransactionCreate]:
        """Parse a generic table row."""
        if len(row) < 2:
            return None
        
        # Look for date in first few columns
        date_str = None
        for i in range(min(3, len(row))):
            cell = str(row[i]).strip() if row[i] else ""
            if re.match(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', cell):
                date_str = cell
                break
        
        if not date_str:
            return None
        
        # Look for amount (usually last column or has $)
        amount_str = None
        for cell in reversed(row):
            cell_str = str(cell).strip() if cell else ""
            if '$' in cell_str or re.search(r'[\d,]+\.\d{2}', cell_str):
                amount_str = cell_str
                break
        
        if not amount_str:
            return None
        
        # Description is everything else
        desc_parts = []
        for cell in row:
            cell_str = str(cell).strip() if cell else ""
            if cell_str and cell_str != date_str and cell_str != amount_str:
                desc_parts.append(cell_str)
        description = ' '.join(desc_parts) if desc_parts else "Transaction"
        
        dt = self.parse_date(date_str)
        if not dt:
            return None
        
        amount = self.normalize_amount(amount_str)
        if amount == 0:
            return None
        
        return TransactionCreate(
            id=str(uuid.uuid4()),
            amount=abs(amount),
            type=TransactionType.expense,
            description=self.clean_description(description),
            merchant=self.extract_merchant(description),
            date=dt,
            timestamp=int(dt.timestamp()),
            account_id=None,
            category_id=None
        )
    
    def _parse_text(self, text: str) -> List[TransactionCreate]:
        """Parse transactions from text."""
        transactions = []
        
        # Pattern: Date Description Amount
        pattern = r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+([A-Z\s\.]+?)\s+(\$?[\d,]+\.\d{2})'
        
        matches = re.finditer(pattern, text, re.MULTILINE)
        for match in matches:
            try:
                date_str = match.group(1)
                description = match.group(2).strip()
                amount_str = match.group(3)
                
                dt = self.parse_date(date_str)
                if not dt:
                    continue
                
                amount = self.normalize_amount(amount_str)
                if amount == 0:
                    continue
                
                tx = TransactionCreate(
                    id=str(uuid.uuid4()),
                    amount=abs(amount),
                    type=TransactionType.expense,
                    description=self.clean_description(description),
                    merchant=self.extract_merchant(description),
                    date=dt,
                    timestamp=int(dt.timestamp()),
                    account_id=None,
                    category_id=None
                )
                
                transactions.append(tx)
            except Exception:
                continue
        
        return transactions
