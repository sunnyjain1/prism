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
            date_str = after_date.strftime("%Y/%m/%d")
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

        parts = message.get("payload", {}).get("parts", [])
        for part in parts:
            filename = part.get("filename", "")
            if not filename:
                continue

            # Filter by pattern if provided
            if filename_pattern:
                if not re.search(filename_pattern, filename, re.IGNORECASE):
                    continue

            attachment_id = part.get("body", {}).get("attachmentId")
            if not attachment_id:
                continue

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
        Convenience method: search for messages and return the latest attachment.

        Returns:
            (filename, content_bytes) or None
        """
        messages = self.search_messages(query, after_date=after_date, max_results=1)
        if not messages:
            return None

        # Get the most recent message
        message_id = messages[0]["id"]
        attachments = self.get_attachments(message_id, filename_pattern)

        if not attachments:
            logger.warning(f"Message {message_id} has no matching attachments")
            return None

        return attachments[0]
