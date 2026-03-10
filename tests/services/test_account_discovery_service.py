import pytest
from unittest.mock import MagicMock, patch
from services.account_discovery_service import AccountDiscoveryService

def test_discover_accounts_empty():
    with patch('services.account_discovery_service.GmailService') as MockGmail:
        mock_gmail = MockGmail.return_value
        mock_gmail.search_messages.return_value = []
        
        service = AccountDiscoveryService("fake_token")
        results = service.discover_accounts()
        
        assert results == []

def test_discover_accounts_with_results():
    with patch('services.account_discovery_service.GmailService') as MockGmail:
        mock_gmail = MockGmail.return_value
        mock_gmail.search_messages.return_value = [{"id": "msg1"}, {"id": "msg2"}]
        
        # Mock messages
        msg1 = {
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Your HDFC Bank Statement"},
                    {"name": "From", "value": "alerts@hdfcbank.net"}
                ]
            }
        }
        msg2 = {
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "ICICI Bank Credit Card Alert"},
                    {"name": "From", "value": "creditcard@icicibank.com"}
                ]
            }
        }
        
        mock_gmail.get_message.side_effect = [msg1, msg2]
        
        service = AccountDiscoveryService("fake_token")
        results = service.discover_accounts()
        
        assert len(results) == 2
        # HDFC should be there
        hdfc = next(r for r in results if "HDFC" in r["name"])
        assert hdfc["type"] == "checking"
        assert "hdfcbank.net" in hdfc["suggested_query"]
        
        # ICICI Credit should be there
        icici = next(r for r in results if "ICICI" in r["name"])
        assert icici["type"] == "credit"
        assert "icicibank.com" in icici["suggested_query"]
