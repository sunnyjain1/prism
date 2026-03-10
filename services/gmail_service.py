"""
Gmail API service for searching emails and downloading attachments.
"""
import base64
import re
import logging
from typing import Optional, List, Dict, Tuple
from datetime import datetime

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from core.config import settings
from core.encryption import decrypt_token

logger = logging.getLogger(__name__)


class GmailService:
    """Handles Gmail API interactions for fetching bank statements."""

    def __init__(self, refresh_token: str):
        """Initialize with a user's decrypted refresh token."""
        self.credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=settings.GMAIL_SCOPES
        )
        self.service = build("gmail", "v1", credentials=self.credentials)

    def search_messages(
        self, query: str, after_date: Optional[datetime] = None, max_results: int = 5
    ) -> List[Dict]:
        """
        Search Gmail for messages matching the query.

        Args:
            query: Gmail search query string
            after_date: Only return messages after this date
            max_results: Maximum number of messages to return

        Returns:
            List of message metadata dicts with 'id' and 'threadId'
        """
        if after_date:
            from datetime import timedelta
            # Gmail 'after' is exclusive of the date provided (date > after_date).
            # To include messages from the same day as after_date, we search from one day before.
            search_date = after_date - timedelta(days=1)
            date_str = search_date.strftime("%Y/%m/%d")
            query = f"{query} after:{date_str}"

        logger.info(f"Gmail search: {query}")

        try:
            response = self.service.users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()

            messages = response.get("messages", [])
            logger.info(f"Found {len(messages)} messages")
            return messages
        except Exception as e:
            logger.error(f"Gmail search failed: {e}")
            raise

    def get_message(self, message_id: str) -> Dict:
        """Get full message details."""
        return self.service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

    def get_attachments(
        self, message_id: str, filename_pattern: Optional[str] = None
    ) -> List[Tuple[str, bytes]]:
        """
        Download attachments from a message.

        Args:
            message_id: Gmail message ID
            filename_pattern: Optional regex to filter attachments by filename

        Returns:
            List of (filename, content_bytes) tuples
        """
        message = self.get_message(message_id)
        attachments = []
        payload = message.get("payload", {})

        # Helper to recursively find parts with attachments
        def _extract_attachment_parts(parts: List[Dict]) -> List[Dict]:
            found = []
            for p in parts:
                if p.get("filename") and p.get("body", {}).get("attachmentId"):
                    found.append(p)
                if "parts" in p:
                    found.extend(_extract_attachment_parts(p["parts"]))
            return found

        # Gather all attachment parts (could be at root payload, or nested in parts)
        all_attachment_parts = []
        if payload.get("filename") and payload.get("body", {}).get("attachmentId"):
            all_attachment_parts.append(payload)
        if "parts" in payload:
            all_attachment_parts.extend(_extract_attachment_parts(payload["parts"]))

        for part in all_attachment_parts:
            filename = part.get("filename", "")

            # Filter by pattern if provided
            if filename_pattern:
                if not re.search(filename_pattern, filename, re.IGNORECASE):
                    continue

            attachment_id = part.get("body", {}).get("attachmentId")
            
            try:
                attachment = self.service.users().messages().attachments().get(
                    userId="me", messageId=message_id, id=attachment_id
                ).execute()

                data = base64.urlsafe_b64decode(attachment["data"])
                attachments.append((filename, data))
                logger.info(f"Downloaded attachment: {filename} ({len(data)} bytes)")
            except Exception as e:
                logger.error(f"Failed to download attachment {filename}: {e}")

        return attachments

    def get_latest_attachment(
        self, query: str, after_date: Optional[datetime] = None,
        filename_pattern: Optional[str] = None
    ) -> Optional[Tuple[str, bytes]]:
        """
        Convenience method: search for messages and return the latest attachment matching the pattern.

        Returns:
            (filename, content_bytes) or None
        """
        # Fetch up to 10 messages in case the most recent ones don't have the attachment
        messages = self.search_messages(query, after_date=after_date, max_results=10)
        if not messages:
            return None

        # Iterate through messages starting from the most recent
        for msg in messages:
            message_id = msg["id"]
            attachments = self.get_attachments(message_id, filename_pattern)
            
            if attachments:
                return attachments[0]
                
        logger.warning(f"No matching attachments found in the last {len(messages)} messages")
        return None
