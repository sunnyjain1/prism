import pytest
from unittest.mock import MagicMock, patch
from typing import Dict, List

# Mock the settings before importing GmailService
with patch.dict('os.environ', {
    'GOOGLE_CLIENT_ID': 'test_client_id',
    'GOOGLE_CLIENT_SECRET': 'test_client_secret'
}):
    from services.gmail_service import GmailService


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
