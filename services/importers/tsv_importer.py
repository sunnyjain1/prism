import io
import pandas as pd
from typing import List, Dict, Any
from .base_importer import BaseImporter
from schemas import TransactionCreate, TransactionType
from datetime import datetime
import uuid

class MoneyManagerImporter(BaseImporter):
    def parse(self, file_content: bytes) -> List[TransactionCreate]:
        # Try reading as Excel first since the user's sample is .xls
        try:
            df = pd.read_excel(io.BytesIO(file_content))
        except Exception:
            # Fallback to TSV (Money Manager often uses UTF-16 for TSV)
            try:
                decoded = file_content.decode('utf-16')
                df = pd.read_csv(io.StringIO(decoded), sep='\t')
            except Exception as e:
                raise ValueError(f"Could not parse Money Manager file as Excel or TSV: {e}")

        transactions = []
        for _, row in df.iterrows():
            try:
                # Map columns based on observed user sample
                # Columns: ['Date', 'Account', 'Category', 'Subcategory', 'Note', 'INR', 'Income/Expense', 'Description', 'Amount', 'Currency']
                
                date_val = row.get('Date')
                if pd.isna(date_val):
                    continue
                
                # Handle various date formats (e.g., 15/12/2025 or datetime objects)
                if isinstance(date_val, str):
                    try:
                        dt = datetime.strptime(date_val, "%d/%m/%Y")
                    except ValueError:
                        dt = pd.to_datetime(date_val)
                else:
                    dt = pd.to_datetime(date_val)

                raw_amount = row.get('Amount', 0)
                amount = float(str(raw_amount).replace(',', ''))
                
                type_str = str(row.get('Income/Expense', 'Expense')).lower()
                tx_type = TransactionType.income if type_str == 'income' else TransactionType.expense
                
                description = str(row.get('Note', row.get('Description', 'MM Import')))
                if pd.isna(description) or description == 'nan':
                    description = str(row.get('Category', 'Transaction'))

                tx = TransactionCreate(
                    id=str(uuid.uuid4()),
                    amount=abs(amount),
                    type=tx_type,
                    description=description,
                    date=dt.isoformat(),
                    timestamp=int(dt.timestamp()),
                    account_id=None,
                    category_id=None
                )
                transactions.append(tx)
            except Exception as e:
                print(f"Skipping Money Manager row due to error: {e}")
                continue
                
        return transactions

    def validate(self, data: List[Dict[str, Any]]) -> bool:
        return True
