"""search_emails: text criterion + SINCE must not return 0 hits (cache path)."""

from __future__ import annotations

import ast

import pytest

import mail_mcp.tools as tools

from .test_seen_regression import _call, _mail, _sync, imap  # noqa: F401 (fixture)


@pytest.mark.parametrize(
    "criteria",
    [
        'SUBJECT "Speicherkontingent" SINCE "08-Oct-2026"',
        'FROM "google" SINCE "08-Oct-2026"',
        "FROM google SINCE 01-Sep-2026",
        "SUBJECT Speicherkontingent SINCE 01-Sep-2026",
    ],
)
async def test_text_plus_since_is_not_empty(imap, criteria):  # noqa: F811
    imap.add(_mail("Speicherkontingent fast voll", "x").replace(b"absender@", b"google@"))
    _sync(imap)
    hits = ast.literal_eval(await _call("search_emails", criteria=criteria))
    assert len(hits) == 1
    assert "Speicherkontingent" in hits[0]["subject"]


def test_single_text_criterion_still_served_from_cache(imap):  # noqa: F811
    imap.add(_mail("Speicherkontingent", "x"))
    _sync(imap)
    store = imap.store
    assert tools._db_search(store, 'SUBJECT "Speicherkontingent"', "INBOX", 10)
    assert tools._db_search(store, "SUBJECT Speicherkontingent", "INBOX", 10)
    # combined criteria are handed to IMAP
    assert tools._db_search(store, "SUBJECT x SINCE 01-Sep-2026", "INBOX", 10) is None
    assert tools._db_search(store, 'FROM "a" SUBJECT "b"', "INBOX", 10) is None


async def test_db_search_emails_accepts_dates(imap):  # noqa: F811
    imap.add(_mail("Termin 01-Sep-2026", "Treffen am 01-Sep-2026"))
    _sync(imap)
    hits = ast.literal_eval(await _call("db_search_emails", query="01-Sep-2026"))
    assert len(hits) == 1
