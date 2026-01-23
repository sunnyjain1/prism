from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from services.transaction_service import TransactionService
from .importers.tsv_importer import MoneyManagerImporter
from .importers.excel_importer import ExcelImporter
from .importers.pdf_importer import PDFImporter

class BulkUploadService:
    def __init__(self, db: Session):
        self.db = db
        self.tx_service = TransactionService(db)
        self.importers = {
            "money_manager": MoneyManagerImporter(),
            "excel": ExcelImporter(),
            "pdf": PDFImporter()
        }

    async def process_upload(
        self, 
        file: UploadFile, 
        source_type: str, 
        owner_id: str,
        target_account_id: Optional[str] = None
    ) -> dict:
        importer = self.importers.get(source_type)
        if not importer:
            raise HTTPException(status_code=400, detail=f"Unsupported source type: {source_type}")

        content = await file.read()
        try:
            parsed_txs = importer.parse(content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

        count = 0
        for tx in parsed_txs:
            # Overwrite sensitive fields to ensure data isolation
            if target_account_id:
                tx.account_id = target_account_id
                
            try:
                self.tx_service.create_transaction(tx, owner_id)
                count += 1
            except Exception as e:
                print(f"Error creating transaction during bulk upload: {e}")
                continue

        return {
            "message": f"Successfully imported {count} transactions",
            "count": count,
            "source": source_type
        }
