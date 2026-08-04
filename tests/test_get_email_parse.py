"""Regression tests for FETCH-response UID/flags parsing.

Bug (nebenbefund of the mark_flagged report): `get_email` returned swapped
fields — the `uid` field held the raw RFC822 headers and `flags` held
tokenised header words. Cause: `_get_uid`/`_parse_flags` found "UID"/"FLAGS"
in the metadata prefix `item[0]` but then returned `item[1]` (the raw
message body).
"""

from __future__ import annotations

from mail_mcp.client import IMAPClient
from mail_mcp.config import IMAPConfig


def _client():
    return IMAPClient(IMAPConfig(host="h", port=993, user="u", password="p"))


# A realistic imaplib UID-FETCH response: (prefix, raw_rfc822) tuple + closing paren.
RAW = b"Subject: Neue Zahlung\r\nFrom: finom@x\r\n\r\nUID 999 FLAGS in the body text"
MSG_DATA = [
    (b"123 (UID 7778 FLAGS (\\Seen \\Flagged) BODY[] {%d}" % len(RAW), RAW),
    b")",
]


def test_get_uid_reads_number_from_prefix_not_body():
    assert _client()._get_uid(MSG_DATA) == "7778"


def test_parse_flags_reads_flag_list_from_prefix_not_body():
    assert _client()._parse_flags(MSG_DATA) == ["\\Seen", "\\Flagged"]


def test_parse_flags_empty_flag_list():
    data = [(b"1 (UID 5 FLAGS () BODY[] {3}", b"abc"), b")"]
    assert _client()._parse_flags(data) == []


def test_get_uid_missing_returns_none():
    data = [(b"1 (FLAGS (\\Seen) BODY[] {3}", b"abc"), b")"]
    assert _client()._get_uid(data) is None


def test_parse_flags_missing_returns_empty():
    data = [(b"1 (UID 5 BODY[] {3}", b"abc"), b")"]
    assert _client()._parse_flags(data) == []


def test_uid_not_confused_by_uid_word_in_body():
    """The literal 'UID 999' inside the message body must be ignored."""
    assert _client()._get_uid(MSG_DATA) == "7778"  # 7778 from prefix, not 999
