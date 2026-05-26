"""
Gmail API service for searching emails and downloading attachments.
"""
import base64
import re
import logging
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from core.config import settings
from core.encryption import decrypt_token

logger = logging.getLogger(__name__)


def _safe_b64decode(data: str) -> bytes:
    """Base64url-decode a string, adding padding if necessary."""
    # Strip any existing padding, then re-add the exact amount needed
    data = data.rstrip("=")
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


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

    def _apply_date_filters(
        self,
        query: str,
        after_date: Optional[datetime] = None,
        before_date: Optional[datetime] = None,
    ) -> str:
        if after_date:
            # Gmail 'after' is exclusive of the date provided (date > after_date).
            # To include messages from the same day as after_date, we search from one day before.
            search_date = after_date - timedelta(days=1)
            query = f"{query} after:{search_date.strftime('%Y/%m/%d')}"

        if before_date:
            # Gmail 'before' is exclusive of the date provided (date < before_date).
            # To include messages from the same day as before_date, we search up to one day after.
            before_adjusted = before_date + timedelta(days=1)
            query = f"{query} before:{before_adjusted.strftime('%Y/%m/%d')}"

        return query

    def search_messages(
        self,
        query: str,
        after_date: Optional[datetime] = None,
        before_date: Optional[datetime] = None,
        max_results: int = 5,
    ) -> List[Dict]:
        """
        Search Gmail for messages matching the query.

        Args:
            query: Gmail search query string
            after_date: Only return messages after this date
            before_date: Only return messages on or before this date
            max_results: Maximum number of messages to return

        Returns:
            List of message metadata dicts with 'id' and 'threadId'
        """
        query = self._apply_date_filters(
            query,
            after_date=after_date,
            before_date=before_date,
        )

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

    def search_all_messages(
        self,
        query: str,
        after_date: Optional[datetime] = None,
        before_date: Optional[datetime] = None,
    ) -> List[Dict]:
        """
        Paginated Gmail search that returns **all** matching messages.

        Unlike :meth:`search_messages`, this method follows ``nextPageToken``
        cursors so it can retrieve thousands of messages needed for a
        multi-year historical sync.

        Args:
            query: Gmail search query string
            after_date: Only return messages after this date
            before_date: Only return messages on or before this date

        Returns:
            List of message metadata dicts with 'id' and 'threadId'
        """
        full_query = self._apply_date_filters(
            query,
            after_date=after_date,
            before_date=before_date,
        )

        logger.info(f"Gmail paginated search: {full_query}")

        all_messages: List[Dict] = []
        page_token = None

        try:
            while True:
                params: Dict = {"userId": "me", "q": full_query, "maxResults": 100}
                if page_token:
                    params["pageToken"] = page_token

                response = self.service.users().messages().list(**params).execute()
                messages = response.get("messages", [])
                all_messages.extend(messages)

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

        except Exception as e:
            logger.error(f"Gmail paginated search failed: {e}")
            raise

        logger.info(f"Paginated search found {len(all_messages)} total messages")
        return all_messages

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

        # Helper to recursively find parts with attachments.
        # Gmail stores large attachments via a separate attachmentId resource, and small
        # attachments (typically < 25 KB) inline as base64url data in body.data.
        def _extract_attachment_parts(parts: List[Dict]) -> List[Dict]:
            found = []
            for p in parts:
                body = p.get("body", {})
                if p.get("filename") and (body.get("attachmentId") or body.get("data")):
                    found.append(p)
                if "parts" in p:
                    found.extend(_extract_attachment_parts(p["parts"]))
            return found

        # Gather all attachment parts (could be at root payload, or nested in parts)
        all_attachment_parts = []
        root_body = payload.get("body", {})
        if payload.get("filename") and (root_body.get("attachmentId") or root_body.get("data")):
            all_attachment_parts.append(payload)
        if "parts" in payload:
            all_attachment_parts.extend(_extract_attachment_parts(payload["parts"]))

        for part in all_attachment_parts:
            filename = part.get("filename", "")

            # Filter by pattern if provided
            if filename_pattern:
                if not re.search(filename_pattern, filename, re.IGNORECASE):
                    continue

            body = part.get("body", {})
            attachment_id = body.get("attachmentId")
            inline_data = body.get("data")

            try:
                if attachment_id:
                    # Large attachment: fetch via the attachments API
                    attachment = self.service.users().messages().attachments().get(
                        userId="me", messageId=message_id, id=attachment_id
                    ).execute()
                    raw = attachment["data"]
                elif inline_data:
                    # Small attachment: data embedded directly in the message part
                    raw = inline_data
                else:
                    continue

                data = _safe_b64decode(raw)
                attachments.append((filename, data))
                logger.info(f"Downloaded attachment: {filename} ({len(data)} bytes)")
            except Exception as e:
                logger.error(f"Failed to download attachment {filename}: {e}")

        return attachments

    def get_latest_attachment(
        self,
        query: str,
        after_date: Optional[datetime] = None,
        before_date: Optional[datetime] = None,
        filename_pattern: Optional[str] = None,
    ) -> Optional[Tuple[str, bytes]]:
        """
        Convenience method: search for messages and return the latest attachment matching the pattern.

        Returns:
            (filename, content_bytes) or None
        """
        # Fetch up to 10 messages in case the most recent ones don't have the attachment
        messages = self.search_messages(
            query,
            after_date=after_date,
            before_date=before_date,
            max_results=10,
        )
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

    def get_all_attachments_since(
        self,
        query: str,
        after_date: Optional[datetime] = None,
        before_date: Optional[datetime] = None,
        filename_pattern: Optional[str] = None,
    ) -> List[Tuple[str, bytes]]:
        """
        Return **all** attachments found since ``after_date``.

        Uses the paginated :meth:`search_all_messages` so it can handle
        multi-year historical syncs without hitting the ``max_results`` cap.

        Args:
            query: Gmail search query string
            after_date: Only consider messages after this date
            before_date: Only consider messages on or before this date
            filename_pattern: Optional regex to filter attachments by filename

        Returns:
            List of (filename, content_bytes) tuples, oldest-first ordering
            is not guaranteed (Gmail returns newest-first by default).
        """
        messages = self.search_all_messages(
            query,
            after_date=after_date,
            before_date=before_date,
        )
        if not messages:
            return []

        all_attachments: List[Tuple[str, bytes]] = []
        for msg in messages:
            message_id = msg["id"]
            try:
                attachments = self.get_attachments(message_id, filename_pattern)
                all_attachments.extend(attachments)
            except Exception as e:
                logger.warning(f"Skipping message {message_id} due to error: {e}")

        logger.info(
            f"Historical search found {len(all_attachments)} attachments "
            f"across {len(messages)} messages"
        )
        return all_attachments
