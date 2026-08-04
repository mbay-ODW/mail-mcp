"""Regression tests for UID-based STORE/COPY/MOVE/DELETE.

Bug: ``mark_flagged(uid=7778)`` failed with
``STORE command error: BAD [Invalid messageset]`` because the code issued
the *sequence-number* command ``conn.store("UID 7778", …)`` instead of
``conn.uid("STORE", "7778", …)``. The server read ``UID`` as the message
set and rejected it. The same flaw hit copy/move/delete, and ``move_email``
additionally called a non-existent ``conn.move``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mail_mcp.client import IMAPClient
from mail_mcp.config import IMAPConfig


def _client_with_mock_conn():
    client = IMAPClient(IMAPConfig(host="h", port=993, user="u", password="p"))
    conn = MagicMock(name="imap_conn")
    conn.noop.return_value = ("OK", [b""])
    conn.select.return_value = ("OK", [b"1"])
    conn.store.return_value = ("OK", [b"1 (FLAGS (\\Flagged))"])
    conn.uid.return_value = ("OK", [b"1 (FLAGS (\\Flagged))"])
    conn.copy.return_value = ("OK", [b""])
    conn.expunge.return_value = ("OK", [b"1"])
    client._connection = conn
    return client, conn


def test_mark_flagged_by_uid_issues_uid_store():
    """The exact reproduction from the bug report (UID 7778)."""
    client, conn = _client_with_mock_conn()
    result = client.mark_flagged(folder="INBOX", uid=7778)

    conn.uid.assert_called_once_with("STORE", "7778", "+FLAGS", "\\Flagged")
    # The broken sequence path must NOT be used for a UID.
    conn.store.assert_not_called()
    assert result["success"] is True


def test_mark_flagged_accepts_int_or_str_uid():
    for value in (7778, "7778"):
        client, conn = _client_with_mock_conn()
        client.mark_flagged(folder="INBOX", uid=value)
        conn.uid.assert_called_once_with("STORE", "7778", "+FLAGS", "\\Flagged")


def test_flag_helpers_use_correct_mode_and_flag():
    cases = [
        ("mark_read", "+FLAGS", "\\Seen"),
        ("mark_unread", "-FLAGS", "\\Seen"),
        ("mark_flagged", "+FLAGS", "\\Flagged"),
        ("unmark_flagged", "-FLAGS", "\\Flagged"),
    ]
    for method, mode, flag in cases:
        client, conn = _client_with_mock_conn()
        getattr(client, method)(folder="INBOX", uid=7778)
        conn.uid.assert_called_once_with("STORE", "7778", mode, flag)


def test_set_flag_by_message_id_uses_sequence_store():
    """Sequence-number path still uses the plain STORE (no 'UID' prefix)."""
    client, conn = _client_with_mock_conn()
    client.mark_flagged(folder="INBOX", message_id=42)
    conn.store.assert_called_once_with("42", "+FLAGS", "\\Flagged")
    conn.uid.assert_not_called()


def test_delete_email_by_uid_issues_uid_store_and_expunge():
    client, conn = _client_with_mock_conn()
    client.delete_email(folder="INBOX", uid=7778)
    conn.uid.assert_called_once_with("STORE", "7778", "+FLAGS", "\\Deleted")
    conn.expunge.assert_called_once()


def test_copy_email_by_uid_issues_uid_copy():
    client, conn = _client_with_mock_conn()
    client.copy_email(source_folder="INBOX", target_folder="Archive", uid=7778)
    conn.uid.assert_called_once_with("COPY", "7778", "Archive")


def test_move_email_by_uid_issues_uid_move():
    client, conn = _client_with_mock_conn()
    conn.uid.return_value = ("OK", [b""])
    client.move_email(source_folder="INBOX", target_folder="Archive", uid=7778)
    conn.uid.assert_called_once_with("MOVE", "7778", "Archive")


def test_move_email_by_message_id_emulates_with_copy_delete():
    client, conn = _client_with_mock_conn()
    client.move_email(source_folder="INBOX", target_folder="Archive", message_id=42)
    conn.copy.assert_called_once_with("42", "Archive")
    conn.store.assert_called_once_with("42", "+FLAGS", "\\Deleted")
    conn.expunge.assert_called_once()


def test_messageset_requires_a_target():
    with pytest.raises(Exception, match="uid or message_id"):
        IMAPClient._messageset(None, None)
