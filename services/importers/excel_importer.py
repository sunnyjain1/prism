import io
import pandas as pd
from typing import List, Dict, Any
from .base_importer import BaseImporter
from schemas import TransactionCreate, TransactionType
from datetime import datetime
import uuid

class ExcelImporter(BaseImporter):
    def parse(self, file_content: bytes) -> List[TransactionCreate]:
        df = pd.read_excel(io.BytesIO(file_content))
        
        transactions = []
        for _, row in df.iterrows():
            try:
                # Common headers in bank exports: Transaction Date, Description, Amount
                date_val = row.get('Date', row.get('Transaction Date', datetime.now()))
                amount = float(row.get('Amount', 0))
                
                tx_type = TransactionType.expense if amount < 0 else TransactionType.income
                
                tx = TransactionCreate(
                    id=str(uuid.uuid4()),
                    amount=abs(amount),
                    type=tx_type,
                    description=str(row.get('Description', row.get('Memo', 'Excel Import'))),
                    date=date_val.isoformat() if hasattr(date_val, 'isoformat') else str(date_val),
                    timestamp=0, # Placeholder
                    account_id=None,
                    category_id=None
                )
                transactions.append(tx)
            except Exception as e:
                print(f"Excel row error: {e}")
                continue
                
        return transactions

    def validate(self, data: List[Dict[str, Any]]) -> bool:
        return True
