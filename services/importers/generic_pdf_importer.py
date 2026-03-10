import io
import re
import uuid
import logging
import pdfplumber
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

from .base_importer import BaseImporter, ImportResult
from schemas import TransactionCreate, TransactionType

logger = logging.getLogger(__name__)

class GenericPdfTableImporter(BaseImporter):
    """
    A generic PDF table importer that can be configured for various layouts.
    
    Attributes:
        bank_name: Name of the bank/issuer
        detection_keywords: Keywords to detect this bank in PDF text
        column_mapping: Mapping of logical fields to column indices
        date_formats: List of date formats to try
        header_keywords: Keywords to identify the header row
    """
    
    def __init__(
        self, 
        bank_name: str, 
        detection_keywords: List[str],
        column_mapping: Dict[str, int],
        date_formats: List[str] = None,
        header_keywords: List[str] = None
    ):
        super().__init__(bank_name, ["pdf"])
        self.bank_name = bank_name
        self.detection_keywords = detection_keywords
        self.column_mapping = column_mapping
        self.date_formats = date_formats or ["%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y", "%d-%m-%Y"]
        self.header_keywords = header_keywords or ["date", "description", "amount"]

    def can_handle(self, file_content: bytes, filename: Optional[str] = None, password: Optional[str] = None) -> bool:
        if filename and self.bank_name.lower() in filename.lower():
            return True
            
        try:
            with pdfplumber.open(io.BytesIO(file_content), password=password) as pdf:
                first_page_text = pdf.pages[0].extract_text() or ""
                first_page_text_lower = first_page_text.lower()
                return any(kw.lower() in first_page_text_lower for kw in self.detection_keywords)
        except Exception:
            pass
        return False

    def parse(self, file_content: bytes, filename: Optional[str] = None, password: Optional[str] = None) -> ImportResult:
        result = ImportResult()
        result.metadata["bank"] = self.bank_name
        result.metadata["file_type"] = "PDF"
        
        try:
            with pdfplumber.open(io.BytesIO(file_content), password=password) as pdf:
                transactions = []
                for page_num, page in enumerate(pdf.pages):
                    tables = page.extract_tables()
                    if not tables:
                        continue
                        
                    for table in tables:
                        header_found = False
                        for row_idx, row in enumerate(table):
                            if not row: continue
                            
                            row_str = " ".join(str(cell) for cell in row).lower()
                            
                            # Identify header row
                            if not header_found:
                                if all(kw.lower() in row_str for kw in self.header_keywords):
                                    header_found = True
                                continue
                            
                            # Parse transaction row
                            try:
                                tx = self._parse_row(row)
                                if tx:
                                    transactions.append(tx)
                            except Exception as e:
                                logger.debug(f"Error parsing row {row_idx} on page {page_num+1}: {e}")
                                
                result.transactions = transactions
                result.metadata["pages_processed"] = len(pdf.pages)
                result.metadata["parsed_count"] = len(transactions)
                
        except Exception as e:
            result.add_error(0, f"Failed to parse {self.bank_name} PDF: {str(e)}")
            logger.exception(f"Error parsing {self.bank_name} PDF")
            
        return result

    def _parse_row(self, row: List) -> Optional[TransactionCreate]:
        # Basic validation: must have enough columns
        max_idx = max(self.column_mapping.values())
        if len(row) <= max_idx:
            return None
            
        # Extract fields
        date_str = str(row[self.column_mapping["date"]]).strip() if row[self.column_mapping["date"]] else None
        desc_str = str(row[self.column_mapping["description"]]).strip() if row[self.column_mapping["description"]] else None
        amount_str = str(row[self.column_mapping["amount"]]).strip() if row[self.column_mapping["amount"]] else None
        
        if not date_str or not amount_str or date_str.lower() in [k.lower() for k in self.header_keywords]:
            return None
            
        # Parse amount
        amount = self.normalize_amount(amount_str)
        if amount == 0:
            return None
            
        # Parse date
        dt = self.parse_date(date_str, self.date_formats)
        if not dt:
            return None
            
        # Determine type
        tx_type = self.determine_transaction_type(amount, desc_str, original_amount=self._get_original_amount(amount_str))
        
        return TransactionCreate(
            id=str(uuid.uuid4()),
            amount=abs(amount),
            type=tx_type,
            description=self.clean_description(desc_str),
            merchant=self.extract_merchant(desc_str),
            date=dt,
            timestamp=int(dt.timestamp()),
            account_id=None,
            category_id=None
        )

    def _get_original_amount(self, amount_str: str) -> float:
        """Helper to get signed float from amount string to help type determination."""
        try:
            return float(amount_str.replace('$', '').replace(',', '').replace(' ', '').replace('(', '-').replace(')', ''))
        except:
            return 0.0
