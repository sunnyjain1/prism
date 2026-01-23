import io
import pdfplumber
from typing import List, Dict, Any
from .base_importer import BaseImporter
from schemas import TransactionCreate, TransactionType
from datetime import datetime
import uuid

class PDFImporter(BaseImporter):
    def parse(self, file_content: bytes) -> List[TransactionCreate]:
        transactions = []
        with pdfplumber.open(io.BytesIO(file_content)) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if not table:
                    continue
                
                # Simple heuristic: skip header row and look for rows with dates and numbers
                for row in table[1:]:
                    try:
                        # Very generic PDF parsing logic - typical column indexes:
                        # 0: Date, 1: Description, 2: Amount
                        if not row[0] or not row[2]:
                            continue
                            
                        amount_str = str(row[2]).replace('$', '').replace(',', '')
                        amount = float(amount_str)
                        
                        tx_type = TransactionType.expense if amount < 0 else TransactionType.income
                        
                        tx = TransactionCreate(
                            id=str(uuid.uuid4()),
                            amount=abs(amount),
                            type=tx_type,
                            description=str(row[1]),
                            date=str(row[0]),
                            timestamp=0,
                            account_id=None,
                            category_id=None
                        )
                        transactions.append(tx)
                    except Exception:
                        continue
                        
        return transactions

    def validate(self, data: List[Dict[str, Any]]) -> bool:
        return True
