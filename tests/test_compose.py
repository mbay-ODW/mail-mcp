"""Tests for Spark-style reply/forward composition (``mail_mcp.compose``).

Covers the acceptance cases of the 22.10.2026 spec: quote in the HTML
part, German quote header with decoded name, no entities / encoded words
in the text part, signature order and de-duplication, MIME structure,
From display name and the Nextcloud / URL attachment sources.
"""

from __future__ import annotations

import base64
from email import message_from_bytes
from email.message import EmailMessage
from unittest.mock import MagicMock

import httpx
import pytest

from mail_mcp import compose, transfer
from mail_mcp.operations import drafts

SIG_HTML = (
    "<table><tr><td><p><b>Max Berater</b></p><p>Beraternummer: EB000000</p></td></tr></table>"
)
SIG_TEXT = "Max Berater\nBeraternummer: EB000000"
CFG = compose.ComposeConfig(
    from_name="Max Berater - Energieberatung Musterstadt",
    signature_html=SIG_HTML,
    signature_text=SIG_TEXT,
    signature_marker="Beraternummer: EB000000",
)
NO_SIG = compose.ComposeConfig()


def _sample_original(html_only: bool = True) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = "=?UTF-8?Q?J=C3=B6rg_M=C3=BCller?= <joerg.mueller@example.org>"
    msg["To"] = "berater@example.de"
    msg["Subject"] = "=?utf-8?B?QVc6IFJlOiBadXNhdHphbnRyYWcgRsO2cmRlcnVuZw==?="
    msg["Date"] = "Mon, 22 Jun 2026 11:32:19 +0000"
    msg["Message-ID"] = "<orig@example.org>"
    msg["References"] = "<first@x.de>"
    html = (
        "<html><head><style>p{color:red}</style><script>alert(1)</script></head>"
        "<body><div>Hallo Herr Berater,</div>"
        "<div>Hier im Anhang die Zusage für den Zusatz Antrag&nbsp;</div>"
        '<img src="cid:logo123"><div>Gruß Jörg</div></body></html>'
    )
    if html_only:
        msg.set_content(html, subtype="html")
    else:
        msg.set_content("Hallo Herr Berater,\nhier die Zusage.\n")
        msg.add_alternative(html, subtype="html")
    return msg


# ---------------------------------------------------------------------------
# Header helpers
# ---------------------------------------------------------------------------


def test_german_date_summer_and_winter():
    assert compose.german_date("Mon, 22 Jun 2026 11:32:19 +0000") == "22. Juni 2026, 13:32 +0200"
    assert compose.german_date("Tue, 03 Mar 2026 08:05:00 +0000") == "3. März 2026, 09:05 +0100"


def test_quote_header_decodes_name_and_localises_date():
    assert compose.quote_header(_sample_original()) == (
        "Am 22. Juni 2026, 13:32 +0200 schrieb Jörg Müller <joerg.mueller@example.org>:"
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("=?utf-8?B?QVc6IFJlOiBadXNhdHphbnRyYWcgRsO2cmRlcnVuZw==?=", "Re: Zusatzantrag Förderung"),
        ("Re: Re: hallo", "Re: hallo"),
        ("AW: Re: hallo", "Re: hallo"),
        ("", "Re: (kein Betreff)"),
    ],
)
def test_reply_subject(raw, expected):
    assert compose.reply_subject(raw) == expected


def test_forward_subject_dedups():
    assert compose.forward_subject("WG: Fwd: Angebot") == "Fwd: Angebot"


def test_html_to_text_decodes_entities_and_breaks():
    text = compose.html_to_text("<div>Zusage&nbsp;</div><p>A &amp; B<br>C</p><style>x{}</style>")
    assert "&nbsp;" not in text and "&amp;" not in text
    assert text == "Zusage\n\nA & B\nC"


# ---------------------------------------------------------------------------
# Reply composition
# ---------------------------------------------------------------------------


def _reply(original=None, **kw):
    kw.setdefault("body_text", "Test")
    kw.setdefault("body_html", "<div>Test</div>")
    kw.setdefault("cfg", CFG)
    return compose.compose_reply(original or _sample_original(), own_address="me@x.de", **kw)


def test_reply_quotes_in_html_and_text():
    c = _reply()
    assert 'name="messageReplySection"' in c.body_html
    assert "<blockquote" in c.body_html
    assert "Hier im Anhang die Zusage" in c.body_html
    # header/style/script/cid images of the original are not embedded
    assert "<script" not in c.body_html and "color:red" not in c.body_html
    assert "cid:" not in c.body_html
    assert (
        "Am 22. Juni 2026, 13:32 +0200 schrieb Jörg Müller &lt;joerg.mueller@example.org&gt;:"
        in (c.body_html)
    )
    # text part: decoded header, quoted body, no entities / encoded words
    assert (
        "Am 22. Juni 2026, 13:32 +0200 schrieb Jörg Müller <joerg.mueller@example.org>:"
        in c.body_text
    )
    assert "> Hier im Anhang die Zusage für den Zusatz Antrag" in c.body_text
    assert "&nbsp;" not in c.body_text and "=?UTF-8?" not in c.body_text


def test_reply_order_body_signature_quote():
    c = _reply()
    h = c.body_html
    assert h.index("messageBodySection") < h.index("messageSignatureSection")
    assert h.index("messageSignatureSection") < h.index("messageReplySection")
    assert h.startswith("<html>")
    t = c.body_text
    assert t.startswith("Test")
    assert t.index("Beraternummer") < t.index("Am 22. Juni")


def test_reply_threading_headers_and_recipient():
    c = _reply()
    assert c.headers["In-Reply-To"] == "<orig@example.org>"
    assert c.headers["References"] == "<first@x.de> <orig@example.org>"
    assert c.subject == "Re: Zusatzantrag Förderung"
    assert c.to and "joerg.mueller@example.org" in c.to[0]


def test_reply_does_not_duplicate_caller_sections():
    body_html = (
        '<div name="messageBodySection"><div dir="auto">Test</div></div>'
        '<div name="messageSignatureSection">eigene</div>'
        '<div name="messageReplySection">eigenes Zitat</div>'
    )
    c = _reply(body_html=body_html, body_text="Test\n\nBeraternummer: EB000000\n\n> alt")
    assert c.body_html.count("messageSignatureSection") == 1
    assert c.body_html.count("messageReplySection") == 1
    assert c.body_html.count("messageBodySection") == 1
    assert c.body_text.count("Beraternummer") == 1
    assert "Am 22. Juni" not in c.body_text


def test_signature_false_and_unconfigured():
    c = _reply(signature=False)
    assert "Beraternummer" not in c.body_html and "Beraternummer" not in c.body_text
    c = _reply(cfg=NO_SIG)
    assert "messageSignatureSection" not in c.body_html


def test_reply_text_only_original_is_escaped_in_html():
    orig = EmailMessage()
    orig["From"] = "a@b.de"
    orig["Date"] = "Mon, 22 Jun 2026 11:32:19 +0000"
    orig.set_content("1 < 2\nzweite Zeile")
    c = _reply(orig)
    assert "1 &lt; 2<br />" in c.body_html


def test_new_mail_text_only_without_signature_stays_plain():
    text, html = compose.assemble_bodies("Hallo", None, cfg=NO_SIG)
    assert text == "Hallo" and html is None


def test_new_mail_text_only_with_signature_gets_html():
    text, html = compose.assemble_bodies("Hallo", None, cfg=CFG)
    assert text == f"Hallo\n\n{SIG_TEXT}"
    assert "messageSignatureSection" in html and "Hallo" in html


def test_html_document_from_caller_gets_sections_before_body_end():
    text, html = compose.assemble_bodies(None, "<html><body><p>Hi</p></body></html>", cfg=CFG)
    assert html.index("messageSignatureSection") < html.index("</body>")
    assert text.startswith("Hi")


# ---------------------------------------------------------------------------
# MIME structure via save_reply_draft / save_draft
# ---------------------------------------------------------------------------


def _fake_conn(original: EmailMessage | None = None) -> MagicMock:
    conn = MagicMock()
    conn.list.return_value = ("OK", [b'(\\HasNoChildren \\Drafts) "." "INBOX.Drafts"'])
    conn.select.return_value = ("OK", [b"1"])
    if original is not None:
        conn.uid.return_value = ("OK", [(b"1 (UID 7391 BODY[] {1}", original.as_bytes()), b")"])
    conn.append.return_value = ("OK", [b"[APPENDUID 1 5879] OK"])
    return conn


def _stored(conn) -> EmailMessage:
    return message_from_bytes(conn.append.call_args[0][3])


def test_save_reply_draft_mime_is_alternative_with_display_name():
    conn = _fake_conn(_sample_original())
    res = drafts.save_reply_draft(
        connection=conn,
        sender="berater@example.de",
        sender_name=CFG.from_name,
        original_uid=7391,
        body_text="Test",
        body_html="<div>Test</div>",
        cfg=CFG,
    )
    assert res["uid"] == 5879
    msg = _stored(conn)
    assert msg.get_content_type() == "multipart/alternative"
    assert [p.get_content_type() for p in msg.get_payload()] == ["text/plain", "text/html"]
    # long headers are folded; unfold before comparing
    assert " ".join(msg["From"].split()) == (
        "Max Berater - Energieberatung Musterstadt <berater@example.de>"
    )
    assert msg["In-Reply-To"] == "<orig@example.org>"
    html = msg.get_payload()[1].get_payload(decode=True).decode()
    assert "messageReplySection" in html
    # original was fetched without setting \Seen
    assert conn.uid.call_args_list[0][0] == ("FETCH", "7391", "(BODY.PEEK[])")


def test_save_draft_plain_and_with_attachment():
    conn = _fake_conn()
    drafts.save_draft(connection=conn, sender="me@x.de", to=["a@b.de"], subject="s", body_text="x")
    assert _stored(conn).get_content_type() == "text/plain"

    conn = _fake_conn()
    drafts.save_draft(
        connection=conn,
        sender="me@x.de",
        to=["a@b.de"],
        subject="s",
        body_text="x",
        body_html="<div>x</div>",
        attachments=[
            {
                "filename": "FUE.pdf",
                "content_type": "application/pdf",
                "data_base64": base64.b64encode(b"%PDF").decode(),
            }
        ],
    )
    msg = _stored(conn)
    assert msg.get_content_type() == "multipart/mixed"
    assert [p.get_content_type() for p in msg.get_payload()] == [
        "multipart/alternative",
        "application/pdf",
    ]


def test_forward_quotes_and_carries_attachments():
    orig = _sample_original(html_only=False)
    orig.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="Zusage.pdf")
    c = compose.compose_forward(orig, to=["x@y.de"], body_text="Zur Info", cfg=CFG)
    # only forward prefixes are deduplicated, reply prefixes stay
    assert c.subject == "Fwd: AW: Re: Zusatzantrag Förderung"
    assert "Weitergeleitete Nachricht" in c.body_text and "Von: Jörg Müller" in c.body_text
    assert "messageReplySection" in c.body_html
    assert [a["filename"] for a in c.attachments] == ["Zusage.pdf"]


# ---------------------------------------------------------------------------
# attach_from: nextcloud / url
# ---------------------------------------------------------------------------


@pytest.fixture
def _transfer_env(monkeypatch):
    monkeypatch.setattr(transfer, "_cfg", None)
    monkeypatch.setenv("NEXTCLOUD_URL", "https://cloud.test")
    monkeypatch.setenv("NEXTCLOUD_USER", "berater")
    monkeypatch.setenv("NEXTCLOUD_PASSWORD", "app-pw")
    monkeypatch.setenv("ATTACH_FROM_MAX_MB", "1")


def _patch_httpx(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(transfer.httpx, "AsyncClient", factory)


async def test_nextcloud_attachment(monkeypatch, _transfer_env):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "text/plain"})

    _patch_httpx(monkeypatch, handler)
    out = await transfer.resolve_attach_from(
        [{"source": "nextcloud", "path": "/Projekte/1105 - Mueller/FUE_Mueller.pdf"}]
    )
    assert seen["url"] == (
        "https://cloud.test/remote.php/dav/files/berater/Projekte/1105%20-%20Mueller/FUE_Mueller.pdf"
    )
    assert seen["auth"].startswith("Basic ")
    assert out[0]["filename"] == "FUE_Mueller.pdf"
    assert out[0]["content_type"] == "application/pdf"
    assert base64.b64decode(out[0]["data_base64"]) == b"%PDF-1.7"


async def test_nextcloud_size_limit(monkeypatch, _transfer_env):
    _patch_httpx(monkeypatch, lambda r: httpx.Response(200, content=b"x" * (1024 * 1024 + 1)))
    with pytest.raises(ValueError, match="Größenlimit"):
        await transfer.resolve_attach_from([{"source": "nextcloud", "path": "a.pdf"}])


async def test_nextcloud_rejects_parent_paths(_transfer_env):
    with pytest.raises(ValueError, match="ungültiger Pfad"):
        await transfer.resolve_attach_from([{"source": "nextcloud", "path": "a/../../b"}])


@pytest.mark.parametrize("url", ["http://example.com/a.pdf", "https://127.0.0.1/a.pdf"])
async def test_url_source_blocks_non_https_and_internal(url, _transfer_env):
    with pytest.raises(ValueError):
        await transfer.resolve_attach_from([{"source": "url", "url": url}])
