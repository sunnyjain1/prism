"""
Tests for the historical sync (sync_start_date) feature and async trigger endpoint.
"""
import pytest
from unittest.mock import MagicMock, patch, call
from typing import Dict, List
import base64
from datetime import date, datetime, timezone, timedelta

# Mock the settings before importing GmailService
with patch.dict('os.environ', {
    'GOOGLE_CLIENT_ID': 'test_client_id',
    'GOOGLE_CLIENT_SECRET': 'test_client_secret'
}):
    from services.gmail_service import GmailService


class MockGmailAPI:
    """Helper to mock the chained Google API client calls with pagination support."""

    def __init__(self, messages: List[Dict], message_details: Dict[str, Dict],
                 page_token_map: Dict[str, List[Dict]] = None):
        """
        Args:
            messages: First-page messages returned by list().
            message_details: Map of message_id -> full message dict.
            page_token_map: Optional map of page_token -> messages for pagination.
        """
        self.messages = messages
        self.message_details = message_details
        self.page_token_map = page_token_map or {}

        self.mock_service = MagicMock()
        mock_users = MagicMock()
        mock_messages_api = MagicMock()
        mock_attachments_api = MagicMock()

        self.mock_service.users.return_value = mock_users
        mock_users.messages.return_value = mock_messages_api
        mock_messages_api.attachments.return_value = mock_attachments_api

        # First page
        first_response = {"messages": self.messages}
        if self.page_token_map:
            # Signal that there are more pages
            first_next_token = list(self.page_token_map.keys())[0]
            first_response["nextPageToken"] = first_next_token

        def _list_side_effect(userId, q, maxResults, pageToken=None):
            req = MagicMock()
            if pageToken and pageToken in self.page_token_map:
                remaining_keys = list(self.page_token_map.keys())
                idx = remaining_keys.index(pageToken)
                resp = {"messages": self.page_token_map[pageToken]}
                # If there's a next page token after this one, add it
                if idx + 1 < len(remaining_keys):
                    resp["nextPageToken"] = remaining_keys[idx + 1]
                req.execute.return_value = resp
            else:
                req.execute.return_value = first_response
            return req

        mock_messages_api.list.side_effect = _list_side_effect

        def mock_get(userId, id, format):
            req = MagicMock()
            req.execute.return_value = self.message_details.get(id, {})
            return req
        mock_messages_api.get = mock_get

        def mock_attachment_get(userId, messageId, id):
            req = MagicMock()
            req.execute.return_value = {"data": "dGVzdA=="}
            return req
        mock_attachments_api.get = mock_attachment_get


def _make_message_with_attachment(msg_id: str, filename: str) -> Dict:
    """Helper to build a message dict with a single inline attachment."""
    content = f"content of {filename}".encode()
    inline_b64 = base64.urlsafe_b64encode(content).decode().rstrip("=")
    return {
        "id": msg_id,
        "payload": {
            "parts": [
                {
                    "filename": filename,
                    "body": {"data": inline_b64, "size": len(content)}
                }
            ]
        }
    }


# ─── search_all_messages ──────────────────────────────────────

@patch('services.gmail_service.build')
@patch('services.gmail_service.Credentials')
def test_search_all_messages_single_page(mock_credentials, mock_build):
    """search_all_messages returns all messages when there's only one page."""
    messages = [{"id": f"msg{i}"} for i in range(5)]
    mock_api = MockGmailAPI(messages=messages, message_details={})
    mock_build.return_value = mock_api.mock_service

    gmail = GmailService(refresh_token="dummy")
    result = gmail.search_all_messages(query="from:bank")

    assert len(result) == 5
    assert result == messages


@patch('services.gmail_service.build')
@patch('services.gmail_service.Credentials')
def test_search_all_messages_multiple_pages(mock_credentials, mock_build):
    """search_all_messages follows nextPageToken to collect messages from all pages."""
    page1 = [{"id": "msg1"}, {"id": "msg2"}]
    page2 = [{"id": "msg3"}, {"id": "msg4"}]

    mock_api = MockGmailAPI(
        messages=page1,
        message_details={},
        page_token_map={"page2_token": page2}
    )
    mock_build.return_value = mock_api.mock_service

    gmail = GmailService(refresh_token="dummy")
    result = gmail.search_all_messages(query="from:bank")

    assert len(result) == 4
    ids = [m["id"] for m in result]
    assert "msg1" in ids
    assert "msg3" in ids


@patch('services.gmail_service.build')
@patch('services.gmail_service.Credentials')
def test_search_all_messages_with_after_date(mock_credentials, mock_build):
    """search_all_messages includes an 'after:' filter when after_date is provided."""
    messages = [{"id": "msg1"}]
    mock_api = MockGmailAPI(messages=messages, message_details={})
    mock_build.return_value = mock_api.mock_service

    gmail = GmailService(refresh_token="dummy")
    after = datetime(2023, 1, 15, tzinfo=timezone.utc)
    gmail.search_all_messages(query="from:bank", after_date=after)

    # Verify the query passed to list() included an 'after:' filter
    list_call_kwargs = mock_api.mock_service.users().messages().list.call_args
    q_arg = list_call_kwargs[1].get("q") or list_call_kwargs[0][1]
    assert "after:" in q_arg


@patch('services.gmail_service.build')
@patch('services.gmail_service.Credentials')
def test_search_messages_with_before_date(mock_credentials, mock_build):
    """search_messages includes an inclusive 'before:' filter when before_date is provided."""
    messages = [{"id": "msg1"}]
    mock_api = MockGmailAPI(messages=messages, message_details={})
    mock_build.return_value = mock_api.mock_service

    gmail = GmailService(refresh_token="dummy")
    before = date(2023, 1, 15)
    gmail.search_messages(query="from:bank", before_date=before)

    list_call_kwargs = mock_api.mock_service.users().messages().list.call_args
    q_arg = list_call_kwargs[1].get("q") or list_call_kwargs[0][1]
    assert "before:2023/01/16" in q_arg


@patch('services.gmail_service.build')
@patch('services.gmail_service.Credentials')
def test_search_all_messages_with_before_date(mock_credentials, mock_build):
    """search_all_messages includes an inclusive 'before:' filter when before_date is provided."""
    messages = [{"id": "msg1"}]
    mock_api = MockGmailAPI(messages=messages, message_details={})
    mock_build.return_value = mock_api.mock_service

    gmail = GmailService(refresh_token="dummy")
    before = date(2023, 1, 15)
    gmail.search_all_messages(query="from:bank", before_date=before)

    list_call_kwargs = mock_api.mock_service.users().messages().list.call_args
    q_arg = list_call_kwargs[1].get("q") or list_call_kwargs[0][1]
    assert "before:2023/01/16" in q_arg


@patch('services.gmail_service.build')
@patch('services.gmail_service.Credentials')
def test_search_all_messages_empty(mock_credentials, mock_build):
    """search_all_messages returns empty list when no messages match."""
    mock_api = MockGmailAPI(messages=[], message_details={})
    mock_build.return_value = mock_api.mock_service

    gmail = GmailService(refresh_token="dummy")
    result = gmail.search_all_messages(query="from:nonexistent")

    assert result == []


# ─── get_all_attachments_since ────────────────────────────────

@patch('services.gmail_service.build')
@patch('services.gmail_service.Credentials')
def test_get_all_attachments_since_multiple_messages(mock_credentials, mock_build):
    """get_all_attachments_since collects attachments from every matching message."""
    msg_details = {
        "msg1": _make_message_with_attachment("msg1", "jan_statement.pdf"),
        "msg2": _make_message_with_attachment("msg2", "feb_statement.pdf"),
        "msg3": _make_message_with_attachment("msg3", "mar_statement.pdf"),
    }
    mock_api = MockGmailAPI(
        messages=[{"id": "msg1"}, {"id": "msg2"}, {"id": "msg3"}],
        message_details=msg_details
    )
    mock_build.return_value = mock_api.mock_service

    gmail = GmailService(refresh_token="dummy")
    after = datetime(2024, 1, 1, tzinfo=timezone.utc)
    attachments = gmail.get_all_attachments_since(query="from:bank", after_date=after)

    assert len(attachments) == 3
    filenames = {a[0] for a in attachments}
    assert "jan_statement.pdf" in filenames
    assert "feb_statement.pdf" in filenames
    assert "mar_statement.pdf" in filenames


@patch('services.gmail_service.build')
@patch('services.gmail_service.Credentials')
def test_get_all_attachments_since_empty(mock_credentials, mock_build):
    """get_all_attachments_since returns empty list when there are no messages."""
    mock_api = MockGmailAPI(messages=[], message_details={})
    mock_build.return_value = mock_api.mock_service

    gmail = GmailService(refresh_token="dummy")
    result = gmail.get_all_attachments_since(
        query="from:bank",
        after_date=datetime(2020, 1, 1, tzinfo=timezone.utc)
    )

    assert result == []


@patch('services.gmail_service.build')
@patch('services.gmail_service.Credentials')
def test_get_all_attachments_since_skips_failed_messages(mock_credentials, mock_build):
    """get_all_attachments_since skips messages that raise exceptions and continues."""
    msg_details = {
        "msg_ok": _make_message_with_attachment("msg_ok", "ok.pdf"),
        # msg_bad has no payload - triggers an error in get_attachments
        "msg_bad": {"id": "msg_bad"}
    }
    mock_api = MockGmailAPI(
        messages=[{"id": "msg_ok"}, {"id": "msg_bad"}],
        message_details=msg_details
    )
    mock_build.return_value = mock_api.mock_service

    gmail = GmailService(refresh_token="dummy")
    # Should not raise; should return the one good attachment
    attachments = gmail.get_all_attachments_since(query="from:bank")

    assert len(attachments) == 1
    assert attachments[0][0] == "ok.pdf"


@patch('services.gmail_service.build')
@patch('services.gmail_service.Credentials')
def test_get_all_attachments_since_filename_pattern(mock_credentials, mock_build):
    """get_all_attachments_since applies filename_pattern to filter results."""
    msg_details = {
        "msg1": _make_message_with_attachment("msg1", "statement_jan.pdf"),
        "msg2": _make_message_with_attachment("msg2", "receipt_jan.jpg"),
    }
    mock_api = MockGmailAPI(
        messages=[{"id": "msg1"}, {"id": "msg2"}],
        message_details=msg_details
    )
    mock_build.return_value = mock_api.mock_service

    gmail = GmailService(refresh_token="dummy")
    attachments = gmail.get_all_attachments_since(
        query="from:bank",
        filename_pattern=r"\.pdf$"
    )

    assert len(attachments) == 1
    assert attachments[0][0] == "statement_jan.pdf"


# ─── sync_start_date in SyncOrchestrator ─────────────────────

def _make_mock_config(
    account_id: str = "acc-1",
    owner_id: str = "user-1",
    last_synced_at=None,
    sync_start_date=None,
    sync_end_date=None,
    gmail_search_query: str = "from:bank",
    importer_key: str = "hdfc_pdf",
    attachment_filename_pattern=None
):
    config = MagicMock()
    config.account_id = account_id
    config.owner_id = owner_id
    config.last_synced_at = last_synced_at
    config.sync_start_date = sync_start_date
    config.sync_end_date = sync_end_date
    config.gmail_search_query = gmail_search_query
    config.importer_key = importer_key
    config.attachment_filename_pattern = attachment_filename_pattern
    config.encrypted_pdf_password = None
    return config


@patch('services.sync_orchestrator.GmailService')
@patch('services.sync_orchestrator.SyncRepository')
@patch('services.sync_orchestrator.BulkUploadService')
def test_sync_account_uses_historical_sync_on_first_run_with_start_date(
    mock_bulk_cls, mock_repo_cls, mock_gmail_cls
):
    """When last_synced_at is None and sync_start_date is set, historical sync is used."""
    from services.sync_orchestrator import SyncOrchestrator

    # Setup
    mock_repo = mock_repo_cls.return_value
    mock_repo.get_decrypted_refresh_token.return_value = "fake_token"
    mock_repo.get_decrypted_pdf_password.return_value = None

    mock_gmail = mock_gmail_cls.return_value
    # Historical path returns a list of attachments
    mock_gmail.get_all_attachments_since.return_value = []
    mock_gmail.get_latest_attachment.return_value = None

    config = _make_mock_config(
        last_synced_at=None,
        sync_start_date=datetime(2022, 1, 1, tzinfo=timezone.utc),
        sync_end_date=date(2022, 12, 31),
    )

    db = MagicMock()
    orchestrator = SyncOrchestrator(db)
    orchestrator.sync_account(config)

    # get_all_attachments_since should be called (historical path)
    mock_gmail.get_all_attachments_since.assert_called_once_with(
        query=config.gmail_search_query,
        after_date=config.sync_start_date,
        before_date=config.sync_end_date,
        filename_pattern=config.attachment_filename_pattern,
    )
    # get_latest_attachment should NOT be called
    mock_gmail.get_latest_attachment.assert_not_called()


@patch('services.sync_orchestrator.GmailService')
@patch('services.sync_orchestrator.SyncRepository')
@patch('services.sync_orchestrator.BulkUploadService')
def test_sync_account_uses_incremental_sync_on_first_run_without_start_date(
    mock_bulk_cls, mock_repo_cls, mock_gmail_cls
):
    """When last_synced_at is None and no sync_start_date, incremental sync is used."""
    from services.sync_orchestrator import SyncOrchestrator

    mock_repo = mock_repo_cls.return_value
    mock_repo.get_decrypted_refresh_token.return_value = "fake_token"
    mock_repo.get_decrypted_pdf_password.return_value = None

    mock_gmail = mock_gmail_cls.return_value
    mock_gmail.get_latest_attachment.return_value = None

    config = _make_mock_config(
        last_synced_at=None,
        sync_start_date=None,
        sync_end_date=date(2022, 12, 31),
    )

    db = MagicMock()
    orchestrator = SyncOrchestrator(db)
    orchestrator.sync_account(config)

    # Incremental path
    mock_gmail.get_latest_attachment.assert_called_once_with(
        query=config.gmail_search_query,
        after_date=config.last_synced_at,
        before_date=config.sync_end_date,
        filename_pattern=config.attachment_filename_pattern,
    )
    mock_gmail.get_all_attachments_since.assert_not_called()


@patch('services.sync_orchestrator.GmailService')
@patch('services.sync_orchestrator.SyncRepository')
@patch('services.sync_orchestrator.BulkUploadService')
def test_sync_account_uses_incremental_sync_on_subsequent_runs(
    mock_bulk_cls, mock_repo_cls, mock_gmail_cls
):
    """After the first sync, incremental sync is always used regardless of sync_start_date."""
    from services.sync_orchestrator import SyncOrchestrator

    mock_repo = mock_repo_cls.return_value
    mock_repo.get_decrypted_refresh_token.return_value = "fake_token"
    mock_repo.get_decrypted_pdf_password.return_value = None

    mock_gmail = mock_gmail_cls.return_value
    mock_gmail.get_latest_attachment.return_value = None

    config = _make_mock_config(
        last_synced_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        sync_start_date=datetime(2022, 1, 1, tzinfo=timezone.utc)  # set but should be ignored
    )

    db = MagicMock()
    orchestrator = SyncOrchestrator(db)
    orchestrator.sync_account(config)

    mock_gmail.get_latest_attachment.assert_called_once()
    mock_gmail.get_all_attachments_since.assert_not_called()
