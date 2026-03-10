"""
Service for discovering bank and credit card accounts from Gmail messages.
"""
import logging
import re
from typing import List, Dict, Any
from services.gmail_service import GmailService

logger = logging.getLogger(__name__)

class AccountDiscoveryService:
    def __init__(self, refresh_token: str):
        self.gmail = GmailService(refresh_token)

    def discover_accounts(self) -> List[Dict[str, Any]]:
        """
        Search Gmail for common banking keywords and try to identify potential accounts.
        """
        keywords = ["statement", "bank", "credit card", "e-statement", "transaction alert"]
        query = " OR ".join([f'"{k}"' for k in keywords])
        
        # Search for messages in the last 60 days to be relevant
        messages = self.gmail.search_messages(query, max_results=50)
        
        discovered = {}
        
        # Common bank names and patterns
        bank_patterns = [
            (r"HDFC Bank", "HDFC Bank"),
            (r"ICICI Bank", "ICICI Bank"),
            (r"SBI", "State Bank of India"),
            (r"Axis Bank", "Axis Bank"),
            (r"Chase", "Chase"),
            (r"American Express|Amex", "American Express"),
            (r"Citi", "Citibank"),
            (r"HSBC", "HSBC"),
            (r"Standard Chartered", "Standard Chartered"),
            (r"Kotak", "Kotak Mahindra Bank")
        ]

        for msg_meta in messages:
            try:
                msg = self.gmail.get_message(msg_meta["id"])
                headers = msg.get("payload", {}).get("headers", [])
                subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
                sender = next((h["value"] for h in headers if h["name"] == "From"), "")
                
                text = f"{subject} {sender}"
                
                for pattern, bank_name in bank_patterns:
                    if re.search(pattern, text, re.IGNORECASE):
                        # Try to find if it's a credit card or statement
                        is_credit = bool(re.search(r"credit card|card", text, re.IGNORECASE))
                        
                        key = f"{bank_name}_{'credit' if is_credit else 'bank'}"
                        if key not in discovered:
                            discovered[key] = {
                                "name": bank_name if not is_credit else f"{bank_name} Credit Card",
                                "type": "credit" if is_credit else "checking",
                                "suggested_query": f"from:{sender.split('<')[-1].split('>')[0]} {bank_name}",
                                "sender": sender,
                                "count": 1
                            }
                        else:
                            discovered[key]["count"] += 1
            except Exception as e:
                logger.warning(f"Failed to process message for discovery: {e}")

        # Return sorted by count
        return sorted(discovered.values(), key=lambda x: x["count"], reverse=True)
