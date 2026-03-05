"""
Sync orchestrator: coordinates Gmail fetch → importer → deduplication → DB import.
"""
import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from models import AccountSyncConfig, SyncStatus
from repositories.sync_repository import SyncRepository
from services.gmail_service import GmailService
from services.bulk_upload_service import BulkUploadService
from services.transaction_service import TransactionService
from services.deduplication_service import DeduplicationService

logger = logging.getLogger(__name__)


class SyncOrchestrator:
    """Orchestrates the full sync pipeline for a single account."""

    def __init__(self, db: Session):
        self.db = db
        self.sync_repo = SyncRepository(db)
        self.bulk_service = BulkUploadService(db)

    def sync_account(self, config: AccountSyncConfig) -> Dict[str, Any]:
        """
        Run the full sync pipeline for one account.

        Steps:
        1. Set status to 'syncing'
        2. Get user's Gmail refresh token
        3. Search Gmail for the latest statement
        4. Download the attachment
        5. Run the appropriate importer
        6. Deduplicate against existing transactions
        7. Import new transactions
        8. Update sync status

        Returns:
            Dict with sync results
        """
        result = {
            "account_id": config.account_id,
            "status": "failed",
            "transactions_imported": 0,
            "error": None
        }

        # Step 1: Set status to syncing
        self.sync_repo.set_sync_status(config, SyncStatus.syncing)

        try:
            # Step 2: Get Gmail refresh token
            refresh_token = self.sync_repo.get_decrypted_refresh_token(config.owner_id)
            if not refresh_token:
                raise Exception("Gmail not connected. Please connect Gmail in settings.")

            # Step 3 & 4: Search Gmail and download attachment
            gmail = GmailService(refresh_token)
            attachment = gmail.get_latest_attachment(
                query=config.gmail_search_query,
                after_date=config.last_synced_at,
                filename_pattern=config.attachment_filename_pattern
            )

            if not attachment:
                # No new statement found — mark as success with 0 transactions
                self.sync_repo.set_sync_status(config, SyncStatus.success, txn_count=0)
                result["status"] = "success"
                result["error"] = "No new statement found in Gmail"
                return result

            filename, file_content = attachment
            logger.info(f"Syncing account {config.account_id}: got {filename} ({len(file_content)} bytes)")

            # Step 5: Run importer
            importer = self.bulk_service.importers.get(config.importer_key)
            if not importer:
                raise Exception(f"Unknown importer: {config.importer_key}")

            import_result = importer.parse(file_content, filename)

            if not import_result.transactions:
                self.sync_repo.set_sync_status(
                    config, SyncStatus.success, txn_count=0
                )
                result["status"] = "success"
                result["error"] = f"No transactions parsed from {filename}"
                if import_result.errors:
                    result["error"] += f" ({len(import_result.errors)} parse errors)"
                return result

            # Step 6: Deduplicate
            dedup_service = DeduplicationService(self.db, config.owner_id)

            unique_in_batch = dedup_service.remove_duplicates_within_batch(
                import_result.transactions
            )
            final_transactions, cross_duplicates = dedup_service.find_duplicates(
                unique_in_batch
            )

            duplicates_skipped = len(import_result.transactions) - len(final_transactions)

            # Step 7: Import
            tx_service = TransactionService(self.db)
            imported_count = 0
            errors = []

            for tx in final_transactions:
                # Assign to the linked account
                tx.account_id = config.account_id
                try:
                    tx_service.create_transaction(tx, config.owner_id)
                    imported_count += 1
                except Exception as e:
                    errors.append(str(e))
                    logger.warning(f"Failed to import transaction: {e}")

            # Step 8: Update status
            self.sync_repo.set_sync_status(
                config, SyncStatus.success, txn_count=imported_count
            )

            result["status"] = "success"
            result["transactions_imported"] = imported_count
            result["duplicates_skipped"] = duplicates_skipped
            result["parse_errors"] = len(import_result.errors)
            result["import_errors"] = len(errors)

            logger.info(
                f"Sync complete for account {config.account_id}: "
                f"{imported_count} imported, {duplicates_skipped} duplicates skipped"
            )

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Sync failed for account {config.account_id}: {error_msg}")
            self.sync_repo.set_sync_status(
                config, SyncStatus.failed, error=error_msg
            )
            result["error"] = error_msg

        return result

    def sync_all_due(self) -> list:
        """Sync all accounts that are due for sync. Used by the scheduler."""
        due_configs = self.sync_repo.get_due_sync_configs()
        logger.info(f"Found {len(due_configs)} accounts due for sync")

        results = []
        for config in due_configs:
            result = self.sync_account(config)
            results.append(result)

        return results
