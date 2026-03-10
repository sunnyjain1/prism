"""
Enhanced bulk upload service with multiple bank support, deduplication, and better error handling.
"""
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from sqlalchemy import exc
import logging
import traceback

from services.transaction_service import TransactionService
from services.deduplication_service import DeduplicationService
from services.import_entity_service import ImportEntityService
from services.category_inference_service import CategoryInferenceService

# Import all bank importers
from .importers.bank_importers import (
    ChaseBankImporter,
    BankOfAmericaImporter,
    WellsFargoImporter,
    GenericBankImporter
)
from .importers.bank_pdf_importers import HdfcBankPDFImporter
from .importers.money_manager_importer import MoneyManagerImporter
from .importers.generic_pdf_importer import GenericPdfTableImporter

logger = logging.getLogger(__name__)


class BulkUploadService:
    """Enhanced bulk upload service with auto-detection and multiple format support."""
    
    def __init__(self, db: Session):
        self.db = db
        self.tx_service = TransactionService(db)
        self._register_importers()
    
    def _register_importers(self):
        """Register all supported importers."""
        self.importers = {
            "money_manager": MoneyManagerImporter(),
            "chase": ChaseBankImporter(),
            "bank_of_america": BankOfAmericaImporter(),
            "wells_fargo": WellsFargoImporter(),
            "hdfc_bank": HdfcBankPDFImporter(),
            
            # Credit Card PDF Importers (Refactored to Generic)
            "chase_credit": GenericPdfTableImporter(
                "Chase Credit Card", 
                ["chase", "credit card"],
                {"date": 0, "description": 1, "amount": 2}
            ),
            "amex": GenericPdfTableImporter(
                "American Express",
                ["american express", "amex"],
                {"date": 0, "description": 1, "amount": 2}
            ),
            "citi": GenericPdfTableImporter(
                "Citi",
                ["citibank", "citi"],
                {"date": 0, "description": 1, "amount": 2}
            ),
            "capital_one": GenericPdfTableImporter(
                "Capital One",
                ["capital one"],
                {"date": 0, "description": 1, "amount": 2}
            ),
            
            # Generic fallbacks
            "generic_bank": GenericBankImporter(),
            "generic_pdf": GenericPdfTableImporter(
                "Generic Statement",
                ["statement", "bank"],
                {"date": 0, "description": 1, "amount": 2}
            ),
        }

    async def process_upload(
        self,
        file: UploadFile,
        source_type: Optional[str] = None,
        owner_id: str = None,
        target_account_id: Optional[str] = None,
        currency: str = "INR",
        skip_duplicates: bool = True,
        auto_detect: bool = True,
        password: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process uploaded file and import transactions.
        """
        if not owner_id:
            raise HTTPException(status_code=400, detail="owner_id is required")
        
        # Read file content
        try:
            content = await file.read()
            if not content:
                raise HTTPException(status_code=400, detail="File is empty")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")
        
        # Select importer
        importer = None
        
        if source_type and source_type in self.importers:
            importer = self.importers[source_type]
        elif auto_detect:
            # Auto-detect importer
            importer = self._auto_detect_importer(content, file.filename, password=password)
            if not importer:
                raise HTTPException(
                    status_code=400,
                    detail="Could not auto-detect file format. Please specify source_type."
                )
        else:
            raise HTTPException(
                status_code=400,
                detail="source_type is required when auto_detect is False"
            )
        
        # Parse file
        try:
            import_result = importer.parse(content, file.filename, password=password)
        except Exception as e:
            logger.exception(f"Error parsing file: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to parse file: {str(e)}"
            )
        
        if not import_result.transactions:
            return {
                "message": "No transactions found in file",
                "count": 0,
                "source": importer.name,
                "errors": import_result.errors,
                "warnings": import_result.warnings
            }
        
        # Deduplication logic
        final_transactions = import_result.transactions
        duplicate_count = 0
        
        if skip_duplicates:
            dedup_service = DeduplicationService(self.db, owner_id)
            
            # 1. Remove duplicates within batch
            unique_in_batch = dedup_service.remove_duplicates_within_batch(final_transactions)
            batch_dups = len(final_transactions) - len(unique_in_batch)
            
            # 2. Check against existing transactions
            final_transactions, cross_duplicates = dedup_service.find_duplicates(unique_in_batch)
            duplicate_count = len(cross_duplicates) + batch_dups
            
            if duplicate_count > 0:
                logger.info(f"Skipped {duplicate_count} duplicates ({batch_dups} in batch, {len(cross_duplicates)} cross-batch)")
        
        # Create import entity service for handling missing categories/accounts
        entity_service = ImportEntityService(self.db, owner_id)
        # Create category inference service for auto-categorization
        category_inferrer = CategoryInferenceService(self.db, owner_id)
        # Ensure user has default rules if they haven't customized anything yet
        category_inferrer.seed_default_rules()
        
        # Process transactions: create missing categories/accounts and assign IDs
        for tx in final_transactions:
            # Apply target account if provided
            if target_account_id:
                tx.account_id = target_account_id
            
            # Handle category from import metadata if present
            # (This will be set by importers that extract category information)
            if hasattr(tx, '_import_category') and tx._import_category:
                category_id = entity_service.get_or_create_category(
                    tx._import_category,
                    tx.type
                )
                if category_id:
                    tx.category_id = category_id
            elif not tx.category_id:
                # Auto-infer category from description when not explicitly provided
                inferred_name = category_inferrer.infer_category(tx.description, tx.type)
                if inferred_name:
                    category_id = entity_service.get_or_create_category(
                        inferred_name,
                        tx.type,
                        color=category_inferrer.get_category_color(inferred_name)
                    )
                    if category_id:
                        tx.category_id = category_id
            
            # Handle account from import metadata if present
            # (This will be set by importers that extract account information)
            if hasattr(tx, '_import_account') and tx._import_account and not target_account_id:
                account_id = entity_service.get_or_create_account(
                    tx._import_account,
                    currency=currency
                )
                if account_id:
                    tx.account_id = account_id
            
            # Handle destination account for transfers (from Money Manager's category column)
            if hasattr(tx, '_import_destination_account') and tx._import_destination_account:
                dest_account_id = entity_service.get_or_create_account(
                    tx._import_destination_account,
                    currency=currency
                )
                if dest_account_id:
                    tx.destination_account_id = dest_account_id
        
        # Import transactions
        imported_count = 0
        failed_count = 0
        import_errors = []
        
        for idx, tx in enumerate(final_transactions):
            try:
                self.tx_service.create_transaction(tx, owner_id)
                imported_count += 1
            except HTTPException as e:
                failed_count += 1
                import_errors.append({
                    "row": idx + 1,
                    "message": e.detail,
                    "transaction": {
                        "date": tx.date.isoformat() if tx.date else None,
                        "amount": tx.amount,
                        "description": tx.description
                    }
                })
                logger.warning(f"Failed to import transaction {idx + 1}: {e.detail}")
            except Exception as e:
                failed_count += 1
                error_msg = str(e)
                import_errors.append({
                    "row": idx + 1,
                    "message": error_msg,
                    "transaction": {
                        "date": tx.date.isoformat() if tx.date else None,
                        "amount": tx.amount,
                        "description": tx.description
                    }
                })
                logger.exception(f"Unexpected error importing transaction {idx + 1}")
        
        # Build response
        response = {
            "message": f"Successfully imported {imported_count} transactions",
            "count": imported_count,
            "source": importer.name,
            "total_parsed": len(import_result.transactions),
            "duplicates_skipped": duplicate_count,
            "failed": failed_count,
            "parse_errors": import_result.errors[:10],  # Limit to first 10
            "parse_warnings": import_result.warnings[:10],
            "import_errors": import_errors[:10],
            "metadata": import_result.metadata
        }
        
        if len(import_result.errors) > 10:
            response["parse_errors_truncated"] = True
        
        return response
    
    def _auto_detect_importer(self, content: bytes, filename: Optional[str] = None, password: Optional[str] = None):
        """
        Auto-detect the appropriate importer for the file.
        
        Returns:
            Importer instance or None if not detected
        """
        # Try each importer's can_handle method
        for importer_name, importer in self.importers.items():
            try:
                if importer.can_handle(content, filename, password=password):
                    logger.info(f"Auto-detected importer: {importer_name}")
                    return importer
            except Exception as e:
                logger.warning(f"Error checking importer {importer_name}: {e}")
                continue
        
        return None
    
    def get_supported_formats(self) -> Dict[str, Any]:
        """Get list of supported import formats and their details."""
        formats = {}
        
        for name, importer in self.importers.items():
            formats[name] = {
                "name": importer.name,
                "supported_formats": importer.supported_formats,
                "description": self._get_importer_description(name)
            }
        
        return formats
    
    def _get_importer_description(self, importer_name: str) -> str:
        """Get human-readable description for importer."""
        descriptions = {
            "chase": "Chase Bank CSV/Excel transaction files",
            "bank_of_america": "Bank of America CSV/Excel transaction files",
            "wells_fargo": "Wells Fargo CSV/Excel transaction files",
            "generic_bank": "Generic bank CSV/Excel files (auto-detect columns)",
            "chase_credit": "Chase credit card PDF statements",
            "amex": "American Express credit card PDF statements",
            "citi": "Citi credit card PDF statements",
            "capital_one": "Capital One credit card PDF statements",
            "generic_credit_card": "Generic credit card PDF statements",
            "money_manager": "Money Manager XLS/TSV export files",
            "hdfc_bank": "HDFC Bank savings/current account PDF statements"
        }
        
        return descriptions.get(importer_name, "Unknown format")
