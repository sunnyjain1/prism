import pytest
from unittest.mock import MagicMock, patch
from typing import Dict, List
import base64

# Mock the settings before importing GmailService
with patch.dict('os.environ', {
    'GOOGLE_CLIENT_ID': 'test_client_id',
    'GOOGLE_CLIENT_SECRET': 'test_client_secret'
}):
    from services.gmail_service import GmailService, _safe_b64decode


class MockGmailAPI:
    """Helper to mock the chained Google API client calls."""
    
    def __init__(self, messages: List[Dict], message_details: Dict[str, Dict]):
        self.messages = messages
        self.message_details = message_details
        
        self.mock_service = MagicMock()
        self.mock_users = MagicMock()
        self.mock_messages_api = MagicMock()
        self.mock_attachments_api = MagicMock()

        # Connect the chains
        self.mock_service.users.return_value = self.mock_users
        self.mock_users.messages.return_value = self.mock_messages_api
        self.mock_messages_api.attachments.return_value = self.mock_attachments_api
        
        # Setup list()
        mock_list_req = MagicMock()
        mock_list_req.execute.return_value = {"messages": self.messages}
        self.mock_messages_api.list.return_value = mock_list_req
        
        # Setup get()
        def mock_get(userId, id, format):
            req = MagicMock()
            req.execute.return_value = self.message_details.get(id, {})
            return req
        self.mock_messages_api.get = mock_get
        
        # Setup attachments().get()
        def mock_attachment_get(userId, messageId, id):
            req = MagicMock()
            # return a dummy base64 url-safe string "test"
            req.execute.return_value = {"data": "dGVzdA=="}
            return req
        self.mock_attachments_api.get = mock_attachment_get


@patch('services.gmail_service.build')
@patch('services.gmail_service.Credentials')
def test_get_latest_attachment_regex(mock_credentials, mock_build):
    """Test that get_latest_attachment correctly filters by subject_pattern regex."""
    
    # 1. Setup mock data
    msg_list = [{"id": "msg1"}, {"id": "msg2"}, {"id": "msg3"}]
    
    msg_details = {
        "msg1": {
            # This message represents a match but is older (comes last)
            "id": "msg1",
            "payload": {
                "headers": [{"name": "Subject", "value": "Account Statement Feb 2026"}],
                "filename": "statement_feb.pdf",
                "body": {"attachmentId": "att1"}
            }
        },
        "msg2": {
            # This message should fail the regex
            "id": "msg2",
            "payload": {
                "headers": [{"name": "Subject", "value": "Security Alert: Login from new device"}],
                "filename": "alert.pdf",
                "body": {"attachmentId": "att2"}
            }
        },
        "msg3": {
            # This message represents the newest match (comes first)
            "id": "msg3",
            "payload": {
                "headers": [{"name": "Subject", "value": "Account Statement Mar 2026"}],
                "filename": "statement_mar.pdf",
                "body": {"attachmentId": "att3"}
            }
        }
    }
    
    # 2. Inject mock into GmailService
    mock_api = MockGmailAPI(messages=[msg_list[2], msg_list[1], msg_list[0]], message_details=msg_details)
    mock_build.return_value = mock_api.mock_service
    
    # Needs a random refresh token since credentials are mocked anyway
    gmail = GmailService(refresh_token="dummy_token")
    
    # 3. Test without regex - should return the first attachment it hits (msg3)
    att_no_regex = gmail.get_latest_attachment(query="from:bank")
    assert att_no_regex is not None
    assert att_no_regex[0] == "statement_mar.pdf"


@patch('services.gmail_service.build')
@patch('services.gmail_service.Credentials')
def test_get_attachments_inline_data(mock_credentials, mock_build):
    """
    Test that get_attachments correctly handles small attachments whose data is
    embedded inline in body.data (no separate attachmentId).
    """
    inline_content = b"PDF content here"
    # Gmail returns base64url without padding for inline data
    inline_b64 = base64.urlsafe_b64encode(inline_content).decode().rstrip("=")

    msg_details = {
        "msg_inline": {
            "id": "msg_inline",
            "payload": {
                "parts": [
                    {
                        "filename": "statement_inline.pdf",
                        "body": {
                            # Inline data — no attachmentId
                            "data": inline_b64,
                            "size": len(inline_content),
                        }
                    }
                ]
            }
        }
    }

    mock_api = MockGmailAPI(messages=[{"id": "msg_inline"}], message_details=msg_details)
    mock_build.return_value = mock_api.mock_service

    gmail = GmailService(refresh_token="dummy_token")
    attachments = gmail.get_attachments("msg_inline")

    assert len(attachments) == 1
    assert attachments[0][0] == "statement_inline.pdf"
    assert attachments[0][1] == inline_content


def test_safe_b64decode_with_padding():
    """Test _safe_b64decode handles strings with and without padding."""
    original = b"hello world"
    # Correctly padded
    padded = base64.urlsafe_b64encode(original).decode()
    assert _safe_b64decode(padded) == original

    # Strip padding (as Gmail API sometimes does for inline data)
    unpadded = padded.rstrip("=")
    assert _safe_b64decode(unpadded) == original
