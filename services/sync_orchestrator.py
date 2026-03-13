"""
Sync orchestrator: coordinates Gmail fetch → importer → deduplication → DB import.
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime
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

        If the account has never been synced and ``config.sync_start_date`` is
        set, a historical (bulk) sync is performed that fetches **all**
        attachments since that date.  Otherwise the standard incremental sync
        is used, which only fetches the single most-recent attachment.

        Steps:
        1. Set status to 'syncing'
        2. Get user's Gmail refresh token
        3. Search Gmail for statement(s)
        4. Download the attachment(s)
        5. Run the appropriate importer for each attachment
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
            try:
                refresh_token = self.sync_repo.get_decrypted_refresh_token(config.owner_id)
            except (ValueError, Exception) as decrypt_err:
                raise Exception(
                    f"Failed to decrypt Gmail token: {decrypt_err}. "
                    "Please disconnect and reconnect Gmail in Sync Settings."
                )
            if not refresh_token:
                raise Exception("Gmail not connected. Please connect Gmail in settings.")

            gmail = GmailService(refresh_token)

            try:
                pdf_password = self.sync_repo.get_decrypted_pdf_password(config)
            except (ValueError, Exception) as decrypt_err:
                raise Exception(
                    f"Failed to decrypt PDF password: {decrypt_err}. "
                    "Please re-save your PDF password in Sync Settings."
                )

            # Decide between historical (bulk) sync and incremental sync.
            # Historical sync is triggered on the very first run when the user
            # has provided a sync_start_date for fetching older data.
            is_first_run = config.last_synced_at is None
            use_historical = is_first_run and config.sync_start_date is not None

            if use_historical:
                result = self._run_historical_sync(
                    config, gmail, pdf_password, result
                )
            else:
                result = self._run_incremental_sync(
                    config, gmail, pdf_password, result
                )

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Sync failed for account {config.account_id}: {error_msg}")
            self.sync_repo.set_sync_status(
                config, SyncStatus.failed, error=error_msg
            )
            result["error"] = error_msg

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_incremental_sync(
        self, config: AccountSyncConfig, gmail: GmailService,
        pdf_password: Optional[str], result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Fetch the single most-recent attachment and import it."""

        attachment = gmail.get_latest_attachment(
            query=config.gmail_search_query,
            after_date=config.last_synced_at,
            filename_pattern=config.attachment_filename_pattern
        )

        if not attachment:
            self.sync_repo.set_sync_status(config, SyncStatus.success, txn_count=0, update_timestamp=False)
            result["status"] = "success"
            result["error"] = "No new statement found in Gmail"
            return result

        filename, file_content = attachment
        logger.info(f"Syncing account {config.account_id}: got {filename} ({len(file_content)} bytes)")

        imported_count, duplicates_skipped, parse_errors, import_errors = self._import_attachment(
            config, filename, file_content, pdf_password
        )

        self.sync_repo.set_sync_status(config, SyncStatus.success, txn_count=imported_count)

        result["status"] = "success"
        result["transactions_imported"] = imported_count
        result["duplicates_skipped"] = duplicates_skipped
        result["parse_errors"] = parse_errors
        result["import_errors"] = import_errors

        logger.info(
            f"Incremental sync complete for account {config.account_id}: "
            f"{imported_count} imported, {duplicates_skipped} duplicates skipped"
        )
        return result

    def _run_historical_sync(
        self, config: AccountSyncConfig, gmail: GmailService,
        pdf_password: Optional[str], result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Fetch **all** attachments since ``config.sync_start_date`` and import them.

        This is used when a user sets a historical start date so that years of
        old bank statements can be imported in a single (async) operation.
        """
        since_date = config.sync_start_date
        logger.info(
            f"Starting historical sync for account {config.account_id} "
            f"since {since_date.isoformat()}"
        )

        attachments = gmail.get_all_attachments_since(
            query=config.gmail_search_query,
            after_date=since_date,
            filename_pattern=config.attachment_filename_pattern
        )

        if not attachments:
            self.sync_repo.set_sync_status(config, SyncStatus.success, txn_count=0)
            result["status"] = "success"
            result["error"] = f"No statements found in Gmail since {since_date.date()}"
            return result

        logger.info(
            f"Historical sync: found {len(attachments)} attachment(s) for account {config.account_id}"
        )

        total_imported = 0
        total_duplicates = 0
        total_parse_errors = 0
        total_import_errors = 0

        for filename, file_content in attachments:
            try:
                imported, dupes, p_errors, i_errors = self._import_attachment(
                    config, filename, file_content, pdf_password
                )
                total_imported += imported
                total_duplicates += dupes
                total_parse_errors += p_errors
                total_import_errors += i_errors
            except Exception as e:
                logger.warning(
                    f"Skipping attachment '{filename}' for account "
                    f"{config.account_id}: {e}"
                )
                total_import_errors += 1

        self.sync_repo.set_sync_status(config, SyncStatus.success, txn_count=total_imported)

        result["status"] = "success"
        result["transactions_imported"] = total_imported
        result["duplicates_skipped"] = total_duplicates
        result["parse_errors"] = total_parse_errors
        result["import_errors"] = total_import_errors
        result["attachments_processed"] = len(attachments)

        logger.info(
            f"Historical sync complete for account {config.account_id}: "
            f"{len(attachments)} attachments, {total_imported} imported, "
            f"{total_duplicates} duplicates skipped"
        )
        return result

    def _import_attachment(
        self, config: AccountSyncConfig, filename: str,
        file_content: bytes, pdf_password: Optional[str]
    ):
        """
        Parse a single attachment, deduplicate, and import transactions.

        Returns:
            Tuple of (imported_count, duplicates_skipped, parse_errors, import_errors)
        """
        importer = self.bulk_service.importers.get(config.importer_key)
        if not importer:
            raise Exception(f"Unknown importer: {config.importer_key}")

        import_result = importer.parse(file_content, filename, password=pdf_password)

        if not import_result.transactions:
            parse_errors = len(import_result.errors) if import_result.errors else 0
            return 0, 0, parse_errors, 0

        dedup_service = DeduplicationService(self.db, config.owner_id)
        unique_in_batch = dedup_service.remove_duplicates_within_batch(import_result.transactions)
        final_transactions, _ = dedup_service.find_duplicates(unique_in_batch)

        duplicates_skipped = len(import_result.transactions) - len(final_transactions)

        tx_service = TransactionService(self.db)
        imported_count = 0
        import_errors_list = []

        for tx in final_transactions:
            tx.account_id = config.account_id
            try:
                tx_service.create_transaction(tx, config.owner_id)
                imported_count += 1
            except Exception as e:
                import_errors_list.append(str(e))
                logger.warning(f"Failed to import transaction: {e}")

        return imported_count, duplicates_skipped, len(import_result.errors), len(import_errors_list)

    def sync_all_due(self) -> list:
        """Sync all accounts that are due for sync. Used by the scheduler."""
        due_configs = self.sync_repo.get_due_sync_configs()
        logger.info(f"Found {len(due_configs)} accounts due for sync")

        results = []
        for config in due_configs:
            result = self.sync_account(config)
            results.append(result)

        return results
