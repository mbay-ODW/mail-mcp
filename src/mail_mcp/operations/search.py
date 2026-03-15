"""
Email search operations for IMAP MCP server.

Provides search functionality with support for various criteria:
- By subject, from, to, cc, bcc
- By date (before, since, on)
- By flag status (seen, answered, flagged, etc.)
- By body content
- Combined AND searches
"""

from datetime import date, datetime
from typing import Any


class EmailSearchError(Exception):
    """Base exception for email search operations."""

    pass


class EmailSearch:
    """
    Handles email search operations.

    Provides a high-level interface for searching emails using
    IMAP SEARCH command with various criteria.

    Attributes:
        _conn: IMAP connection instance
    """

    # IMAP search keys
    SEARCH_KEYS = {
        "subject": "SUBJECT",
        "from": "FROM",
        "to": "TO",
        "cc": "CC",
        "bcc": "BCC",
        "body": "BODY",
        "text": "TEXT",
        "since": "SINCE",
        "before": "BEFORE",
        "on": "ON",
        "since_date": "SINCE",
        "before_date": "BEFORE",
    }

    # Flag search keys
    FLAG_KEYS = {
        "seen": "SEEN",
        "answered": "ANSWERED",
        "flagged": "FLAGGED",
        "deleted": "DELETED",
        "draft": "DRAFT",
        "recent": "RECENT",
        "all": "ALL",
    }

    # Negated flag search keys
    NEG_FLAG_KEYS = {
        "unseen": "UNSEEN",
        "unanswered": "UNANSWERED",
        "unflagged": "UNFLAGGED",
        "undeleted": "UNDELETED",
    }

    def __init__(self, connection) -> None:
        """
        Initialize EmailSearch with an IMAP connection.

        Args:
            connection: An active IMAP connection
        """
        self._conn = connection

    def _format_date(self, date_value: str | date | datetime) -> str:
        """
        Format date for IMAP SEARCH command.

        Args:
            date_value: Date as string (YYYY-MM-DD), date, or datetime object

        Returns:
            Formatted date string (DD-Mon-YYYY)
        """
        if isinstance(date_value, datetime):
            date_obj = date_value.date()
        elif isinstance(date_value, date):
            date_obj = date_value
        elif isinstance(date_value, str):
            # Try to parse string date
            for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"]:
                try:
                    date_obj = datetime.strptime(date_value, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                # If parsing fails, assume it's already in correct format or return as-is
                return date_value
        else:
            raise EmailSearchError(f"Invalid date format: {date_value}")

        # Format as DD-Mon-YYYY (IMAP standard)
        months = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]
        return f"{date_obj.day:02d}-{months[date_obj.month - 1]}-{date_obj.year}"

    def _build_search_criteria(self, conditions: dict[str, Any]) -> list[str]:
        """
        Build IMAP search criteria from conditions dictionary.

        Args:
            conditions: Dictionary of search conditions

        Returns:
            List of IMAP search keys and values

        Raises:
            EmailSearchError: If conditions are invalid
        """
        criteria = []

        for key, value in conditions.items():
            key_lower = key.lower()

            # Handle ALL condition
            if key_lower == "all" and value:
                criteria.append("ALL")
                continue

            # Handle flag conditions (boolean)
            # 包括正向和反向 flag
            flag_keys = [
                "seen",
                "unseen",
                "answered",
                "unanswered",
                "flagged",
                "unflagged",
                "deleted",
                "undeleted",
                "draft",
                "undraft",
                "recent",
                "unread",
                "all",
            ]
            if key_lower in flag_keys:
                if value:  # True means search for this flag
                    if key_lower in self.FLAG_KEYS:
                        criteria.append(self.FLAG_KEYS[key_lower])
                    elif key_lower in self.NEG_FLAG_KEYS:
                        criteria.append(self.NEG_FLAG_KEYS[key_lower])
                    else:
                        criteria.append(key_lower.upper())
                else:  # False means search for negated flag
                    if key_lower in self.FLAG_KEYS:
                        criteria.extend(["NOT", self.FLAG_KEYS[key_lower]])
                    elif key_lower in self.NEG_FLAG_KEYS:
                        # unseen=False -> SEEN
                        neg_key = key_lower.replace("un", "")
                        if neg_key in self.FLAG_KEYS:
                            criteria.append(self.FLAG_KEYS[neg_key])
                    else:
                        criteria.extend(["NOT", key_lower.upper()])
                continue

            # Handle special conditions
            if key_lower == "uid":
                # Search by UID range or list
                if isinstance(value, list):
                    criteria.extend(value)
                elif isinstance(value, str):
                    criteria.append(value)
                continue

            if key_lower == "or":
                # OR condition: {'or': [(cond1, val1), (cond2, val2)]}
                if isinstance(value, list) and len(value) == 2:
                    criteria.append("OR")
                    criteria.extend(self._build_search_criteria({value[0]: value[1]}))
                continue

            # Handle date conditions
            if key_lower in ["since", "before", "on", "since_date", "before_date"]:
                search_key = self.SEARCH_KEYS.get(key_lower, key_lower.upper())
                formatted_date = self._format_date(value)
                criteria.extend([search_key, formatted_date])
                continue

            # Handle standard search keys
            if key_lower in self.SEARCH_KEYS:
                search_key = self.SEARCH_KEYS[key_lower]

                # Handle list values (OR search)
                if isinstance(value, list):
                    criteria.append("OR")
                    for v in value:
                        criteria.extend([search_key, str(v)])
                else:
                    criteria.extend([search_key, str(value)])
            else:
                # Unknown key - use as-is
                criteria.extend([key_upper if (key_upper := key.upper()) else key, str(value)])

        return criteria

    def search_emails(
        self, folder: str, conditions: dict[str, Any], charset: str | None = None
    ) -> list[int]:
        """
        Search for emails matching conditions.

        Args:
            folder: Folder to search in
            conditions: Dictionary of search conditions
                Supported keys:
                - subject, from, to, cc, bcc, body, text: Search in fields
                - since, before, on: Date conditions (YYYY-MM-DD or date object)
                - seen/unseen, answered/unanswered, flagged/unflagged, deleted/undeleted: Flag conditions
                - uid: UID search
            charset: Character set for search (default: None/UTF-8)

        Returns:
            List of email sequence numbers

        Raises:
            EmailSearchError: If search fails

        Example:
            >>> # Search for unread emails from a specific sender
            >>> results = search.search_emails('INBOX', {
            ...     'from': 'boss@example.com',
            ...     'unread': True
            ... })
            >>> print(results)
            [1, 5, 10]
        """
        if not folder:
            raise EmailSearchError("Folder name is required")

        if not conditions:
            raise EmailSearchError("At least one search condition is required")

        try:
            # Select the folder
            select_result = self._conn.select(folder)
            # 检查状态 (可能是 'OK' 或 b'OK'，阿里云可能返回邮件数量)
            status = select_result[0]
            # 阿里云邮箱返回邮件数量而不是 'OK'，需要检查数据是否存在
            if status not in ("OK", b"OK") and not isinstance(status, int):
                error_msg = (
                    select_result[1][0].decode("utf-8", errors="replace")
                    if select_result[1]
                    else "Unknown error"
                )
                raise EmailSearchError(f"Failed to select folder '{folder}': {error_msg}")

            # Build search criteria
            criteria = self._build_search_criteria(conditions)

            # Execute search
            response = self._conn.search(charset, *criteria)

            # 检查状态
            status = response[0]
            if status not in ("OK", b"OK"):
                error_msg = (
                    response[1][0].decode("utf-8", errors="replace")
                    if response[1]
                    else "Unknown error"
                )
                raise EmailSearchError(f"Search failed: {error_msg}")

            # Parse response
            return self._parse_search_response(response)

        except EmailSearchError:
            raise
        except Exception as e:
            raise EmailSearchError(f"Search failed: {str(e)}")

    def _parse_search_response(self, response: tuple) -> list[int]:
        """
        Parse IMAP SEARCH response into list of message numbers.

        Args:
            response: Tuple from IMAP search command

        Returns:
            List of message sequence numbers
        """
        if not response or len(response) < 2:
            return []

        # Get the data portion
        data = response[1]
        if not data:
            return []

        # Handle different response formats
        if isinstance(data[0], bytes):
            id_string = data[0].decode("utf-8", errors="replace")
        else:
            id_string = str(data[0])

        if not id_string.strip():
            return []

        # Parse space-separated IDs
        try:
            return [int(uid) for uid in id_string.split() if uid.isdigit()]
        except (ValueError, AttributeError):
            return []

    def search_by_text(self, folder: str, text: str, charset: str | None = None) -> list[int]:
        """
        Search for emails containing specific text.

        Convenience method that searches in all text fields.

        Args:
            folder: Folder to search in
            text: Text to search for
            charset: Character set for search

        Returns:
            List of email sequence numbers
        """
        return self.search_emails(folder, {"text": text}, charset)

    def search_by_sender(
        self, folder: str, sender: str, charset: str | None = None
    ) -> list[int]:
        """
        Search for emails from specific sender.

        Convenience method for searching by From address.

        Args:
            folder: Folder to search in
            sender: Sender email address or name
            charset: Character set for search

        Returns:
            List of email sequence numbers
        """
        return self.search_emails(folder, {"from": sender}, charset)

    def search_by_subject(
        self, folder: str, subject: str, charset: str | None = None
    ) -> list[int]:
        """
        Search for emails with specific subject.

        Args:
            folder: Folder to search in
            subject: Subject text to search for
            charset: Character set for search

        Returns:
            List of email sequence numbers
        """
        return self.search_emails(folder, {"subject": subject}, charset)

    def search_unread(self, folder: str, charset: str | None = None) -> list[int]:
        """
        Search for unread emails.

        Args:
            folder: Folder to search in
            charset: Character set for search

        Returns:
            List of email sequence numbers
        """
        return self.search_emails(folder, {"unread": True}, charset)

    def search_flagged(self, folder: str, charset: str | None = None) -> list[int]:
        """
        Search for flagged/starred emails.

        Args:
            folder: Folder to search in
            charset: Character set for search

        Returns:
            List of email sequence numbers
        """
        return self.search_emails(folder, {"flagged": True}, charset)


# Convenience functions
def search_emails(connection, folder: str, conditions: dict[str, Any]) -> list[int]:
    """
    Search for emails using connection.

    Args:
        connection: IMAP connection
        folder: Folder to search in
        conditions: Search conditions

    Returns:
        List of message sequence numbers
    """
    search = EmailSearch(connection)
    return search.search_emails(folder, conditions)


__all__ = [
    "EmailSearchError",
    "EmailSearch",
    "search_emails",
]
