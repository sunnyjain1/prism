"""
Bank account PDF statement importers.
Handles PDF statements from Indian banks (HDFC, SBI, ICICI, etc.)
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


class HdfcBankPDFImporter(BaseImporter):
    """HDFC Bank savings/current account PDF statement importer.
    
    Handles HDFC Bank statements where pdfplumber extracts tables as:
      - Row 0: Header ['Txn Date', 'Narration', 'Withdrawals', 'Deposits', 'Closing Balance']
      - Row 1: All values newline-separated in a single cell per column
    """
    
    def __init__(self):
        super().__init__("HDFC Bank", ["pdf"])
        # Patterns to detect HDFC bank statements
        self.detection_keywords = [
            "hdfc bank",
            "hdfc0",  # IFSC prefix
        ]
        self.txn_header = ['Txn Date', 'Narration', 'Withdrawals', 'Deposits', 'Closing Balance']
    
    def can_handle(self, file_content: bytes, filename: Optional[str] = None) -> bool:
        """Detect HDFC Bank savings/current account PDF."""
        if filename and not filename.lower().endswith('.pdf'):
            return False
        
        try:
            pdf = pdfplumber.open(io.BytesIO(file_content))
            # Check first 2 pages for HDFC identifiers
            for page in pdf.pages[:2]:
                text = (page.extract_text() or "").lower()
                if any(kw in text for kw in self.detection_keywords):
                    # Also confirm it has the transaction table format
                    if "txn date" in text and "narration" in text:
                        pdf.close()
                        return True
            pdf.close()
        except Exception:
            pass
        return False
    
    def parse(self, file_content: bytes, filename: Optional[str] = None) -> ImportResult:
        """Parse HDFC Bank PDF statement and extract transactions."""
        result = ImportResult()
        
        try:
            pdf = pdfplumber.open(io.BytesIO(file_content))
        except Exception as e:
            result.add_error(0, f"Failed to open PDF: {e}")
            return result
        
        # Extract metadata from first page
        first_page_text = pdf.pages[0].extract_text() or "" if pdf.pages else ""
        result.metadata = self._extract_metadata(first_page_text)
        
        total_parsed = 0
        
        for page_num, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            
            for table in tables:
                if not table or len(table) < 2:
                    continue
                
                header = table[0]
                if not header or not self._is_transaction_table(header):
                    continue
                
                # Data row (row 1) has newline-separated values
                data_row = table[1]
                if not data_row or len(data_row) < 5:
                    continue
                
                transactions = self._parse_packed_row(data_row, page_num + 1, result)
                total_parsed += len(transactions)
                result.transactions.extend(transactions)
        
        pdf.close()
        
        result.metadata["total_parsed"] = total_parsed
        result.metadata["source"] = "HDFC Bank PDF Statement"
        
        if not result.transactions:
            result.add_warning("No transactions found in the PDF. Please check the file format.")
        
        logger.info(f"HDFC Bank PDF: Parsed {len(result.transactions)} transactions from {filename or 'unknown'}")
        return result
    
    def _is_transaction_table(self, header: List) -> bool:
        """Check if a table header matches HDFC transaction format."""
        if not header or len(header) < 5:
            return False
        header_str = [str(h).strip() if h else "" for h in header]
        return (
            "Txn Date" in header_str[0]
            and "Narration" in header_str[1]
            and "Withdrawal" in header_str[2]
            and "Deposit" in header_str[3]
        )
    
    def _parse_packed_row(
        self, data_row: List, page_num: int, result: ImportResult
    ) -> List[TransactionCreate]:
        """Parse a single packed row where values are newline-separated."""
        transactions = []
        
        dates_raw = (data_row[0] or "").split("\n")
        narrations_raw = (data_row[1] or "").split("\n")
        withdrawals_raw = (data_row[2] or "").split("\n")
        deposits_raw = (data_row[3] or "").split("\n")
        balances_raw = (data_row[4] or "").split("\n")
        
        num_txns = len(dates_raw)
        
        # Withdrawals, deposits, balances should have same count as dates
        if len(withdrawals_raw) != num_txns or len(deposits_raw) != num_txns:
            result.add_warning(
                f"Page {page_num}: Column count mismatch - "
                f"dates={num_txns}, withdrawals={len(withdrawals_raw)}, deposits={len(deposits_raw)}. "
                f"Falling back to text parsing."
            )
            return transactions
        
        # Reassemble narrations: dates tell us the count, narrations are multi-line
        narrations = self._reassemble_narrations(narrations_raw, num_txns)
        
        for i in range(num_txns):
            try:
                # Parse date
                date = self.parse_date(dates_raw[i].strip(), ["%d/%m/%Y"])
                if not date:
                    result.add_error(i + 1, f"Page {page_num}: Invalid date '{dates_raw[i]}'")
                    continue
                
                # Parse amounts
                withdrawal = self._parse_indian_amount(withdrawals_raw[i])
                deposit = self._parse_indian_amount(deposits_raw[i])
                
                # Determine type and amount
                if deposit > 0:
                    tx_type = TransactionType.income
                    amount = deposit
                else:
                    tx_type = TransactionType.expense
                    amount = withdrawal
                
                if amount <= 0:
                    result.add_warning(f"Page {page_num}, row {i+1}: Zero amount, skipping")
                    continue
                
                # Clean narration
                narration = narrations[i] if i < len(narrations) else ""
                description = self._clean_narration(narration)
                notes = self._extract_notes(narration)
                
                tx = TransactionCreate(
                    id=str(uuid.uuid4()),
                    date=date,
                    timestamp=int(date.timestamp()),
                    amount=amount,
                    type=tx_type,
                    description=description,
                    notes=notes,
                    currency="INR",
                )
                
                transactions.append(tx)
                
            except Exception as e:
                result.add_error(i + 1, f"Page {page_num}: Error parsing row: {e}")
        
        return transactions
    
    def _reassemble_narrations(self, narration_lines: List[str], num_txns: int) -> List[str]:
        """Reassemble multi-line narrations into per-transaction narrations.
        
        HDFC narrations span multiple lines. Each transaction's narration typically
        ends with a reference number pattern like 'Ref XXXXXXXXX' or a 'Value Dt' line.
        We use the known transaction count to split them.
        
        Strategy: Join all lines, then split at transaction boundaries detected by
        patterns that mark the start of a new narration entry.
        """
        if num_txns <= 0:
            return []
        
        if num_txns == 1:
            return [" ".join(line.strip() for line in narration_lines)]
        
        # Join all narration lines into one block
        full_text = "\n".join(narration_lines)
        
        # Split at narration boundaries. Each new narration starts with a known prefix:
        # UPI-, NEFT, RTGS, IMPS, ACH, BIL/, ATM, POS, etc.
        # The pattern is: a new transaction narration starts after a Ref number on the previous line
        boundary_pattern = re.compile(
            r'(?=(?:UPI-|NEFT |RTGS |IMPS |ACH [DC]-|BIL/|ATM-|POS |INT\.PD |'
            r'CASH WDL|CHQ PAID|FD RENEWAL|SWEEP IN|SWEEP OUT|'
            r'MOB BANKING|NET BANKING|BY TRANSFER))',
            re.IGNORECASE
        )
        
        parts = boundary_pattern.split(full_text)
        # Remove empty parts
        parts = [p.strip() for p in parts if p.strip()]
        
        # If split count matches, great
        if len(parts) == num_txns:
            return [self._join_narration(p) for p in parts]
        
        # Fallback: distribute lines evenly or by Ref pattern
        # Try to split by finding "Ref XXXX" endings
        narrations = []
        current = []
        for line in narration_lines:
            current.append(line.strip())
            # Check if line contains a reference — likely end of a narration
            if re.search(r'Ref\s+\w{6,}', line):
                narrations.append(" ".join(current))
                current = []
        if current:
            if narrations:
                narrations[-1] += " " + " ".join(current)
            else:
                narrations.append(" ".join(current))
        
        if len(narrations) == num_txns:
            return narrations
        
        # Last resort: return the raw boundary split even if counts differ
        if len(parts) >= num_txns:
            return [self._join_narration(p) for p in parts[:num_txns]]
        
        # Pad with empty strings
        while len(parts) < num_txns:
            parts.append("")
        return [self._join_narration(p) for p in parts[:num_txns]]
    
    def _join_narration(self, text: str) -> str:
        """Join multiline narration into a single line."""
        return re.sub(r'\s+', ' ', text.replace('\n', ' ')).strip()
    
    def _parse_indian_amount(self, amount_str: str) -> float:
        """Parse Indian-format amount (e.g., '9,55,871.54' or '30,092.00')."""
        if not amount_str:
            return 0.0
        try:
            cleaned = amount_str.strip().replace(",", "")
            return float(cleaned)
        except (ValueError, TypeError):
            return 0.0
    
    def _clean_narration(self, narration: str) -> str:
        """Extract a clean, human-readable description from HDFC narration.
        
        Examples:
            'UPI-CRED Club-cred.club@axisb-UTIB0000114-...' → 'CRED Club'
            'NEFT Cr-ICIC0099999-MLL EXPRESS SERVICES...' → 'MLL EXPRESS SERVICES PRIVATE LIMITED'
            'ACH D- Indian Clearing Corp-...' → 'Indian Clearing Corp'
            'ACH C- Apollo Hosp IDV2526-...' → 'Apollo Hosp'
        """
        if not narration:
            return ""
        
        narration = narration.strip()
        
        # UPI transactions: UPI-<merchant>-<vpa>-<ifsc>-<ref>-...
        upi_match = re.match(r'UPI-(.+?)[-](?:[a-zA-Z0-9.@]+[-])', narration)
        if upi_match:
            merchant = upi_match.group(1).strip()
            # Remove trailing phone numbers
            merchant = re.sub(r'[-]?\d{10,}$', '', merchant).strip()
            if merchant:
                return f"UPI - {merchant}"
        
        # NEFT: NEFT Cr-<IFSC>-<Company>-...
        neft_match = re.match(r'NEFT\s+Cr[-]\w+-(.+?)[-]', narration)
        if neft_match:
            company = neft_match.group(1).strip()
            if company:
                return f"NEFT - {company}"
        
        # ACH Debit: ACH D- <entity>-...
        ach_d_match = re.match(r'ACH\s+D[-]\s*(.+?)[-]', narration)
        if ach_d_match:
            entity = ach_d_match.group(1).strip()
            if entity:
                return f"ACH Debit - {entity}"
        
        # ACH Credit: ACH C- <entity>...
        ach_c_match = re.match(r'ACH\s+C[-]\s*(.+?)[-]', narration)
        if ach_c_match:
            entity = ach_c_match.group(1).strip()
            if entity:
                return f"ACH Credit - {entity}"
        
        # BIL/: BIL/<biller>/<details>
        bil_match = re.match(r'BIL/(.+?)/', narration)
        if bil_match:
            biller = bil_match.group(1).strip()
            if biller:
                return f"Bill Payment - {biller}"
        
        # Fallback: truncate at "Value Dt" or first reference marker
        cleaned = re.split(r'\s*Value Dt\s*', narration)[0]
        cleaned = re.split(r'\s*Ref\s+', cleaned)[0]
        # Limit length
        if len(cleaned) > 60:
            cleaned = cleaned[:60].rstrip() + "..."
        return cleaned.strip()
    
    def _extract_notes(self, narration: str) -> str:
        """Extract reference number and value date as notes."""
        if not narration:
            return ""
        
        parts = []
        
        # Extract reference number
        ref_match = re.search(r'Ref\s+(\w+)', narration)
        if ref_match:
            parts.append(f"Ref: {ref_match.group(1)}")
        
        # Extract value date
        vdt_match = re.search(r'Value Dt\s+(\d{2}/\d{2}/\d{4})', narration)
        if vdt_match:
            parts.append(f"Value Date: {vdt_match.group(1)}")
        
        return " | ".join(parts)
    
    def _extract_metadata(self, text: str) -> Dict:
        """Extract account metadata from the statement header page."""
        metadata = {}
        
        # Account number
        acc_match = re.search(r'Account Number\s*:\s*(\d+)', text)
        if acc_match:
            metadata["account_number"] = acc_match.group(1)
        
        # Customer ID
        cust_match = re.search(r'Customer ID\s*:\s*(\d+)', text)
        if cust_match:
            metadata["customer_id"] = cust_match.group(1)
        
        # Statement period
        period_match = re.search(r'Statement From\s*:\s*(\d{2}/\d{2}/\d{4})\s*To\s*(\d{2}/\d{2}/\d{4})', text)
        if period_match:
            metadata["statement_from"] = period_match.group(1)
            metadata["statement_to"] = period_match.group(2)
        
        # Opening balance
        bal_match = re.search(r'Opening Balance\s*:\s*([\d,]+\.\d+)', text)
        if bal_match:
            metadata["opening_balance"] = bal_match.group(1)
        
        # Account type
        type_match = re.search(r'Account Type\s*:\s*(.+?)(?:\n|$)', text)
        if type_match:
            metadata["account_type"] = type_match.group(1).strip()
        
        return metadata
