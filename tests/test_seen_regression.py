"""Regression tests: reading mail must never set \\Seen; long mails stay readable.

Runs the real tool handlers and the real background syncer against the
in-process IMAP server in ``imap_testserver.py`` (real sockets, real imaplib),
so no external service is needed in CI.
"""

from __future__ import annotations

import ast
from email.message import EmailMessage

import pytest

import mail_mcp.client as client_mod
import mail_mcp.db.store as store_mod
import mail_mcp.tools as tools
from mail_mcp.db.store import EmailStore
from mail_mcp.db.sync import EmailSyncer
from mail_mcp.operations.fetch import EmailFetch

from .imap_testserver import TestIMAPServer

SEEN = "\\Seen"


def _mail(subject: str, text: str | None = None, html: str | None = None, **kw) -> bytes:
    msg = EmailMessage()
    msg["From"] = "Absender <absender@example.org>"
    msg["To"] = "info@example.org"
    msg["Subject"] = subject
    msg["Date"] = "Tue, 03 Nov 2026 06:00:00 +0100"
    if text is not None:
        msg.set_content(text, charset=kw.get("charset", "utf-8"))
        if html is not None:
            msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(html or "", subtype="html")
    for name, data in kw.get("attachments", []):
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    return msg.as_bytes()


@pytest.fixture
def imap(monkeypatch, tmp_path):
    server = TestIMAPServer().start()
    monkeypatch.setenv("IMAP_HOST", "127.0.0.1")
    monkeypatch.setenv("IMAP_PORT", str(server.port))
    monkeypatch.setenv("IMAP_SSL", "false")
    monkeypatch.setenv("EMAIL_USER", "test")
    monkeypatch.setenv("EMAIL_PASSWORD", "test")
    client_mod.reset_imap_client()
    store = EmailStore(str(tmp_path / "mail.db"))
    monkeypatch.setattr(store_mod, "_store", store)
    monkeypatch.setattr(tools, "_DB_ENABLED", True)
    server.store = store
    yield server
    client_mod.reset_imap_client()
    server.stop()


async def _call(name: str, **arguments):
    result = await tools.handle_imap_tool(name, arguments)
    return result[0].text


def _sync(server) -> None:
    syncer = EmailSyncer(server.store, sync_interval=3600, sync_days=30)
    syncer._sync_all()
    syncer._reset_client()


def _no_body_fetch_without_peek(log: list[str]) -> None:
    for line in log:
        upper = line.upper()
        if " FETCH " not in upper:
            continue
        stripped = upper.replace("BODY.PEEK[", "")
        assert "BODY[" not in stripped, f"non-PEEK body fetch on the wire: {line}"
        assert "RFC822)" not in stripped and "RFC822 " not in stripped, line


# ---------------------------------------------------------------------------
# Harness self-check: the test server really implements implicit \Seen
# ---------------------------------------------------------------------------


def test_server_sets_seen_on_plain_body_fetch(imap):
    uid = imap.add(_mail("plain", "x"))
    conn = client_mod.get_imap_client()._ensure_connected()
    conn.select("INBOX")
    conn.uid("FETCH", str(uid), "(BODY[])")
    assert SEEN in imap.flags(uid)


def test_legacy_fetch_operation_does_not_set_seen(imap):
    """operations.fetch.EmailFetch used plain BODY[] before the fix."""
    uid = imap.add(_mail("legacy", "x"))
    conn = client_mod.get_imap_client()._ensure_connected()
    EmailFetch(conn).get_email("INBOX", 1)
    EmailFetch(conn).get_email("INBOX", 1, headers_only=True)
    assert SEEN not in imap.flags(uid)


# ---------------------------------------------------------------------------
# Every read tool and the syncer leave \Seen untouched
# ---------------------------------------------------------------------------


async def test_read_tools_and_sync_keep_mail_unread(imap):
    uid = imap.add(_mail("Rechnung", "Hallo Welt", attachments=[("rechnung.pdf", b"%PDF-1")]))
    assert imap.flags(uid) == set()

    steps = [
        ("search_emails IMAP", lambda: _call("search_emails", criteria=f"UID {uid}:*")),
        ("get_email body", lambda: _call("get_email", uid=str(uid), include_body=True)),
        ("get_email header", lambda: _call("get_email", uid=str(uid), include_body=False)),
        ("get_attachment", lambda: _call("get_attachment", uid=str(uid))),
        (
            "get_attachment data",
            lambda: _call("get_attachment", uid=str(uid), include_data=True),
        ),
        ("db_get_email (IMAP fallback)", lambda: _call("db_get_email", uid=uid)),
    ]
    for label, step in steps:
        await step()
        assert SEEN not in imap.flags(uid), f"{label} set \\Seen"

    _sync(imap)
    assert SEEN not in imap.flags(uid), "background sync set \\Seen"

    for label, step in [
        ("db_list_emails", lambda: _call("db_list_emails")),
        ("db_search_emails", lambda: _call("db_search_emails", query="Welt")),
        ("search_emails DB", lambda: _call("search_emails", criteria="ALL")),
        ("db_get_email (cache)", lambda: _call("db_get_email", uid=uid)),
    ]:
        await step()
        assert SEEN not in imap.flags(uid), f"{label} set \\Seen"

    client_mod.get_imap_client().get_attachment_bytes(folder="INBOX", uid=str(uid))
    assert SEEN not in imap.flags(uid), "get_attachment_bytes set \\Seen"

    _no_body_fetch_without_peek(imap.log)


async def test_mark_read_still_sets_seen(imap):
    uid = imap.add(_mail("lesen", "x"))
    await _call("get_email", uid=str(uid))  # leaves the mailbox EXAMINEd
    await _call("mark_read", uid=str(uid))
    assert SEEN in imap.flags(uid)
    await _call("mark_unread", uid=str(uid))
    assert SEEN not in imap.flags(uid)


async def test_seen_flag_is_reported_not_changed(imap):
    uid = imap.add(_mail("schon gelesen", "x"), flags={SEEN})
    out = await _call("get_email", uid=str(uid))
    assert "\\\\Seen" in out
    assert imap.flags(uid) == {SEEN}


def test_syncer_uses_its_own_connection(imap):
    shared = client_mod.get_imap_client()
    syncer = EmailSyncer(imap.store)
    assert syncer._get_client() is not shared
    syncer._reset_client()


# ---------------------------------------------------------------------------
# Full text: paging, HTML-only, charsets, attachments
# ---------------------------------------------------------------------------


def _page_all(server, uid: int, max_chars: int) -> tuple[str, list[dict]]:
    pages = []
    offset = 0
    store = server.store
    client = client_mod.get_imap_client()
    while True:
        page = tools._db_get_email(store, client, "INBOX", uid, offset, max_chars)
        pages.append(page)
        if not page["truncated"]:
            break
        offset = page["next_offset"]
    return "".join(p["body_text"] for p in pages), pages


async def test_long_mail_is_readable_in_pages(imap):
    unit = "Grüße aus Würzberg – äöüß € 😀. "
    long_text = (unit * 2000)[:60000] + "\nENDE"
    uid = imap.add(_mail("lang", long_text))
    _sync(imap)

    cached = imap.store.get_email_by_uid("INBOX", uid)
    assert len(cached["body_text"]) > 50000  # stored untruncated

    text, pages = _page_all(imap, uid, max_chars=7001)
    assert len(pages) > 5
    assert text == cached["body_text"]
    assert text.replace("\r\n", "\n").rstrip("\n") == long_text
    assert pages[0]["body_length"] == len(cached["body_text"])
    assert pages[-1]["next_offset"] is None

    # list tools make the cut visible
    hits = ast.literal_eval(await _call("db_search_emails", query="Würzberg"))
    assert hits[0]["body_truncated"] is True
    assert hits[0]["body_length"] == len(cached["body_text"])
    assert len(hits[0]["body_text"]) <= tools._LIST_BODY_PREVIEW + 1
    rows = ast.literal_eval(await _call("db_list_emails"))
    assert rows[0]["body_length"] == len(cached["body_text"])


async def test_html_only_mail_gets_readable_text(imap):
    html = (
        "<html><head><style>p{color:red}</style></head><body>"
        "<p>Ihre Rechnung&nbsp;Nr. 4711</p><div>Betrag: 12,50&euro;</div>"
        "<script>alert(1)</script></body></html>"
    )
    uid = imap.add(_mail("finom", html=html))

    live = ast.literal_eval(await _call("db_get_email", uid=uid))
    assert live["source"] == "imap"
    assert "Ihre Rechnung Nr. 4711" in live["body_text"]
    assert "Betrag: 12,50€" in live["body_text"]
    assert "alert" not in live["body_text"] and "color" not in live["body_text"]
    assert live["body_text_from_html"] is True

    _sync(imap)
    cached = ast.literal_eval(await _call("db_get_email", uid=uid))
    assert cached["source"] == "cache"
    assert "Ihre Rechnung Nr. 4711" in cached["body_text"]
    hits = ast.literal_eval(await _call("db_search_emails", query="Rechnung"))
    assert [h["uid"] for h in hits] == [uid]  # full-text index covers HTML-only mails


def test_existing_html_only_rows_are_backfilled(tmp_path):
    path = str(tmp_path / "old.db")
    store = EmailStore(path)
    store.upsert_email(
        "INBOX", 7, None, "alt", "a@x", "b@x", None, "", "", "<p>Hallo <b>Welt</b></p>"
    )
    store._local.conn.close()
    store._local.conn = None
    reopened = EmailStore(path)
    assert reopened.get_email_by_uid("INBOX", 7)["body_text"] == "Hallo Welt"
    assert reopened.search_fts("Welt")


async def test_mixed_charsets(imap):
    uid_latin = imap.add(_mail("latin1", "Größe: 5 m² - Schön", charset="iso-8859-1"))
    uid_utf8 = imap.add(_mail("utf8", "Ελληνικά und Türkçe: ğüşıöç"))
    _sync(imap)
    latin = ast.literal_eval(await _call("db_get_email", uid=uid_latin))
    utf8 = ast.literal_eval(await _call("db_get_email", uid=uid_utf8, max_chars=3))
    assert "Größe: 5 m²" in latin["body_text"]
    assert utf8["body_text"] == "Ελλ" and utf8["truncated"] is True


async def test_attachment_listed_and_fetchable(imap):
    uid = imap.add(_mail("anhang", "siehe Anhang", attachments=[("a.pdf", b"%PDF-1.4 x")]))
    _sync(imap)
    out = ast.literal_eval(await _call("db_get_email", uid=uid))
    assert out["attachments"] == [
        {"filename": "a.pdf", "content_type": "application/pdf", "size": 10}
    ]
    att = ast.literal_eval(await _call("get_attachment", uid=str(uid), include_data=True))
    assert att["filename"] == "a.pdf"
    # attachment text must not be mistaken for the body
    assert out["body_text"].strip() == "siehe Anhang"
    assert SEEN not in imap.flags(uid)
