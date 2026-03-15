"""
Pytest configuration and shared fixtures for mail-mcp-server tests.
"""

from unittest.mock import MagicMock

import pytest

# IMAP Response Constants
IMAP_OK = b"OK"
IMAP_NO = b"NO"
IMAP_BAD = b"BAD"


@pytest.fixture
def mock_imap_connection():
    """
    Create a basic mock IMAP connection with common methods.

    Returns:
        MagicMock: A mock IMAP connection with all common IMAP methods mocked.
    """
    conn = MagicMock()

    # Common IMAP responses
    conn.state = "AUTH"

    # List methods - return empty by default
    conn.list.return_value = (IMAP_OK, [])
    conn.lsub.return_value = (IMAP_OK, [])

    # Search methods
    conn.search.return_value = (IMAP_OK, [b""])

    # Fetch methods
    conn.fetch.return_value = (IMAP_OK, [])

    # Store methods
    conn.store.return_value = (IMAP_OK, [])

    # Folder operations
    conn.create.return_value = (IMAP_OK, [])
    conn.delete.return_value = (IMAP_OK, [])
    conn.rename.return_value = (IMAP_OK, [])
    conn.subscribe.return_value = (IMAP_OK, [])
    conn.unsubscribe.return_value = (IMAP_OK, [])
    conn.status.return_value = (IMAP_OK, [])

    # Move/Copy
    conn.move.return_value = (IMAP_OK, [])
    conn.copy.return_value = (IMAP_OK, [])

    # Expunge
    conn.expunge.return_value = (IMAP_OK, [])

    # Select
    conn.select.return_value = (IMAP_OK, [{"EXISTS": 0, "RECENT": 0, "UNSEEN": 0}])

    return conn


@pytest.fixture
def connected_imap_connection(mock_imap_connection):
    """
    Create a mock IMAP connection that appears to be connected and selected.

    Returns:
        MagicMock: A mock IMAP connection in selected state.
    """
    conn = mock_imap_connection
    conn.state = "SELECTED"
    conn.select.return_value = (IMAP_OK, [{"EXISTS": 100, "RECENT": 0, "UNSEEN": 10}])
    return conn


@pytest.fixture
def sample_email_headers():
    """
    Sample email headers for testing.

    Returns:
        bytes: Raw email headers in bytes format.
    """
    return (
        b"From: sender@example.com\r\n"
        b"To: receiver@example.com\r\n"
        b"Subject: Test Email\r\n"
        b"Date: Mon, 1 Jan 2024 12:00:00 +0000\r\n"
        b"Message-ID: <test123@example.com>\r\n"
        b"Content-Type: text/plain; charset=UTF-8\r\n"
        b"\r\n"
    )


@pytest.fixture
def sample_email_body():
    """
    Sample email with body for testing.

    Returns:
        bytes: Raw email with headers and body.
    """
    return (
        b"From: sender@example.com\r\n"
        b"To: receiver@example.com\r\n"
        b"Subject: Test Email\r\n"
        b"Date: Mon, 1 Jan 2024 12:00:00 +0000\r\n"
        b"Content-Type: text/plain; charset=UTF-8\r\n"
        b"\r\n"
        b"This is the email body.\r\n"
        b"Multiple lines of content.\r\n"
    )


@pytest.fixture
def folder_list_response():
    """
    Sample folder list response from IMAP LIST command.

    Returns:
        list: List of folder names as bytes.
    """
    return [
        b"INBOX",
        b"INBOX/Sent",
        b"INBOX/Drafts",
        b"INBOX/Trash",
        b"INBOX/Spam",
        b"Archive/2023",
        b"Archive/2024",
    ]


@pytest.fixture
def search_result_ids():
    """
    Sample search result UIDs.

    Returns:
        list: List of email UIDs as integers.
    """
    return [1, 2, 3, 5, 8, 13, 21]


def create_mock_search_response(uids: list) -> tuple:
    """
    Helper to create a mock IMAP search response.

    Args:
        uids: List of UID numbers to return.

    Returns:
        tuple: (response_code, [message_ids])
    """
    if not uids:
        return (IMAP_OK, [b""])

    id_str = b" ".join(str(uid).encode() for uid in uids)
    return (IMAP_OK, [id_str])


def create_mock_fetch_response(header_bytes: bytes, body_bytes: bytes | None = None) -> tuple:
    """
    Helper to create a mock IMAP fetch response.

    Args:
        header_bytes: Header data.
        body_bytes: Optional body data.

    Returns:
        tuple: Mock fetch response.
    """
    if body_bytes:
        full_data = header_bytes + b"\r\n" + body_bytes
        return (IMAP_OK, [(b"1 (BODY[] {" + str(len(full_data)).encode() + b"})", full_data)])
    else:
        return (
            IMAP_OK,
            [(b"1 (BODY[HEADER] {" + str(len(header_bytes)).encode() + b"})", header_bytes)],
        )
