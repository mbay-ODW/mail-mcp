"""Tests for the draft-management operations.

These tests exercise the small pure-Python helpers that don't need an
IMAP server: subject de-duplication, References-header construction,
APPENDUID parsing, drafts-folder resolution, and the headers-only path
of save_draft via a fake connection.
"""

from __future__ import annotations

from email.message import EmailMessage
from unittest.mock import MagicMock

import pytest

from mail_mcp.operations import drafts

# ---------------------------------------------------------------------------
# Subject prefix helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Re: hello", "hello"),
        ("Re:hello", "hello"),
        ("Re: Re: hello", "hello"),
        ("RE: re:  hello", "hello"),
        ("hello", "hello"),
        ("", ""),
    ],
)
def test_strip_re_prefix(raw, expected):
    assert drafts._strip_re_prefix(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Fwd: hello", "hello"),
        ("Fw: hello", "hello"),
        ("Fwd: Fwd: hello", "hello"),
        ("hello", "hello"),
    ],
)
def test_strip_fwd_prefix(raw, expected):
    assert drafts._strip_fwd_prefix(raw) == expected


# ---------------------------------------------------------------------------
# References header construction
# ---------------------------------------------------------------------------


def test_references_for_reply_chains_correctly():
    msg = EmailMessage()
    msg["Message-ID"] = "<m3@example.com>"
    msg["References"] = "<m1@example.com> <m2@example.com>"
    refs = drafts._references_for_reply(msg)
    assert refs.split() == [
        "<m1@example.com>",
        "<m2@example.com>",
        "<m3@example.com>",
    ]


def test_references_falls_back_to_in_reply_to():
    msg = EmailMessage()
    msg["Message-ID"] = "<m2@example.com>"
    msg["In-Reply-To"] = "<m1@example.com>"
    refs = drafts._references_for_reply(msg)
    assert refs.split() == ["<m1@example.com>", "<m2@example.com>"]


def test_references_first_reply_no_prior_chain():
    msg = EmailMessage()
    msg["Message-ID"] = "<m1@example.com>"
    refs = drafts._references_for_reply(msg)
    assert refs == "<m1@example.com>"


# ---------------------------------------------------------------------------
# APPENDUID parsing
# ---------------------------------------------------------------------------


def test_append_with_uid_parses_appenduid_response():
    """Real Dovecot response shape – APPENDUID inside the OK response code."""
    conn = MagicMock()
    conn.append.return_value = (
        "OK",
        [b"[APPENDUID 1700000000 42] Append completed."],
    )
    result = drafts.append_with_uid(conn, "INBOX.Drafts", b"raw mime bytes", flags=["\\Draft"])
    assert result == drafts.AppendResult(folder="INBOX.Drafts", uid=42, uidvalidity=1700000000)
    conn.append.assert_called_once_with("INBOX.Drafts", "(\\Draft)", None, b"raw mime bytes")


def test_append_with_uid_handles_server_without_uidplus():
    conn = MagicMock()
    conn.append.return_value = ("OK", [b"Append completed."])
    result = drafts.append_with_uid(conn, "Drafts", b"x")
    assert result.uid is None
    assert result.uidvalidity is None
    assert result.folder == "Drafts"


def test_append_with_uid_raises_on_no():
    conn = MagicMock()
    conn.append.return_value = ("NO", [b"quota exceeded"])
    with pytest.raises(RuntimeError, match="APPEND"):
        drafts.append_with_uid(conn, "Drafts", b"x")


# ---------------------------------------------------------------------------
# Drafts folder discovery
# ---------------------------------------------------------------------------


def _list_response(*lines):
    """Build a fake IMAP LIST response."""
    return ("OK", [line.encode() for line in lines])


def test_find_drafts_folder_uses_special_use_flag():
    conn = MagicMock()
    conn.list.return_value = _list_response(
        '(\\HasNoChildren) "/" "INBOX"',
        '(\\HasNoChildren \\Drafts) "/" "MyDrafts"',
        '(\\HasNoChildren \\Sent) "/" "Sent"',
    )
    assert drafts.find_drafts_folder(conn) == "MyDrafts"


def test_find_drafts_folder_falls_back_to_static_list():
    conn = MagicMock()
    conn.list.return_value = _list_response(
        '(\\HasNoChildren) "/" "INBOX"',
        '(\\HasNoChildren) "/" "Drafts"',  # no \Drafts flag, but matching name
    )
    assert drafts.find_drafts_folder(conn) == "Drafts"


def test_find_drafts_folder_explicit_override_wins():
    conn = MagicMock()
    # Even if the server advertises a different drafts folder, the override
    # is honoured verbatim.
    conn.list.return_value = _list_response(
        '(\\HasNoChildren \\Drafts) "/" "ServerDrafts"',
    )
    assert drafts.find_drafts_folder(conn, override="My/Drafts") == "My/Drafts"
    conn.list.assert_not_called()


def test_find_drafts_folder_default_when_nothing_matches():
    conn = MagicMock()
    conn.list.return_value = _list_response('(\\HasNoChildren) "/" "INBOX"')
    assert drafts.find_drafts_folder(conn) == "INBOX.Drafts"


# ---------------------------------------------------------------------------
# save_draft happy path (integration with the fakes above)
# ---------------------------------------------------------------------------


def test_save_draft_appends_with_draft_flag_and_returns_uid():
    conn = MagicMock()
    conn.list.return_value = _list_response('(\\HasNoChildren \\Drafts) "/" "Drafts"')
    conn.append.return_value = ("OK", [b"[APPENDUID 1 7] OK"])

    result = drafts.save_draft(
        connection=conn,
        sender="me@example.com",
        to=["alice@example.com"],
        subject="Hallo",
        body_text="Hi Alice",
    )

    assert result["folder"] == "Drafts"
    assert result["uid"] == 7
    assert result["uidvalidity"] == 1
    assert result["message_id"]  # auto-generated

    folder_arg, flags_arg, internal_arg, body_arg = conn.append.call_args[0]
    assert folder_arg == "Drafts"
    assert flags_arg == "(\\Draft)"
    assert internal_arg is None
    # Subject is wrapped through email.header.Header(...) – it ends up
    # as RFC 2047 encoded-word (`=?utf-8?q?Hallo?=`), the literal text
    # "Hallo" still appears inside the encoded segment though.
    assert b"Subject:" in body_arg and b"Hallo" in body_arg
    # Body text is base64-encoded inside the MIME part.
    import base64

    assert base64.b64encode(b"Hi Alice") in body_arg
    # Recipient + sender end up in the headers.
    assert b"alice@example.com" in body_arg
    assert b"me@example.com" in body_arg


def test_delete_draft_is_idempotent_when_uid_missing():
    conn = MagicMock()
    conn.list.return_value = _list_response('(\\HasNoChildren \\Drafts) "/" "Drafts"')
    conn.select.return_value = ("OK", [b""])
    # Empty SEARCH response → uid not present.
    conn.uid.return_value = ("OK", [b""])

    result = drafts.delete_draft(connection=conn, uid=999, folder="Drafts")
    assert result == {
        "deleted": False,
        "reason": "draft_not_found",
        "folder": "Drafts",
        "uid": 999,
    }
    # No STORE / EXPUNGE issued in the not-found case.
    conn.expunge.assert_not_called()


def test_delete_draft_marks_deleted_and_expunges():
    conn = MagicMock()
    conn.list.return_value = _list_response('(\\HasNoChildren \\Drafts) "/" "Drafts"')
    conn.select.return_value = ("OK", [b""])
    conn.uid.return_value = ("OK", [b"42"])

    result = drafts.delete_draft(connection=conn, uid=42, folder="Drafts")
    assert result["deleted"] is True
    conn.uid.assert_any_call("STORE", "42", "+FLAGS.SILENT", "(\\Deleted)")
    conn.expunge.assert_called_once()
