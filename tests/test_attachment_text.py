"""get_attachment_text: extract attachment text server-side, read it in slices."""

from __future__ import annotations

import ast
import io
from email.message import EmailMessage

import pytest

import mail_mcp.tools as tools
from mail_mcp.extract import ExtractionError, extract_text, parse_page_spec

from .doc_fixtures import make_docx, make_ods, make_odt, make_pdf, make_pptx
from .test_seen_regression import SEEN, _call, _sync, imap  # noqa: F401 (fixture)


def _mail_with(*attachments: tuple[str, str, bytes]) -> bytes:
    msg = EmailMessage()
    msg["From"] = "absender@example.org"
    msg["To"] = "info@example.org"
    msg["Subject"] = "Unterlagen"
    msg.set_content("Anbei die Unterlagen.")
    for filename, ctype, data in attachments:
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


def _long_pdf(n_pages: int = 60) -> tuple[bytes, list[list[str]]]:
    pages = []
    for p in range(1, n_pages + 1):
        lines = [f"Seite {p} Zeile {i}: Wärmedämmung U-Wert 0,{p:02d} W/m²K" for i in range(40)]
        if p == 42:
            lines[10] = "Förderbetrag gesamt: 12.345,67 EUR (Zuschuss BEG EM)"
        pages.append(lines)
    return make_pdf(pages), pages


# ---------------------------------------------------------------------------
# Extraction per file type
# ---------------------------------------------------------------------------


def test_pdf_pages_and_umlauts():
    ex = extract_text(make_pdf([["Größe: 5 m²", "Straße 1"], ["Zweite Seite"]]), "a.pdf")
    assert ex.kind == "pdf" and ex.page_count == 2
    assert "Größe: 5 m²" in ex.text and "Straße 1" in ex.text
    assert ex.text.index("--- Seite 2 ---") == ex.pages[1][1]
    assert not ex.needs_ocr


def test_scanned_pdf_needs_ocr():
    ex = extract_text(make_pdf([None, None]), "scan.pdf")
    assert ex.needs_ocr is True
    assert any("transfer_to_paperless" in w for w in ex.warnings)


def test_pdf_detected_by_magic_bytes_without_name():
    ex = extract_text(make_pdf([["Hallo"]]), None, "application/octet-stream")
    assert ex.kind == "pdf"


def test_docx_paragraphs_and_table():
    data = make_docx(["Angebot Nr. 4711", "Fenstertausch"], [["Pos", "Preis"], ["1", "980 €"]])
    ex = extract_text(data, "angebot.docx")
    assert "Angebot Nr. 4711" in ex.text
    assert "1\t980 €" in ex.text


def test_odt():
    ex = extract_text(make_odt(["Löschkonzept", "Frist 10 Jahre"]), "konzept.odt")
    assert ex.text == "Löschkonzept\nFrist 10 Jahre"


def test_ods_ignores_padding_rows_and_columns():
    data = make_ods({"FLS 2025": [["Klient", "Stunden"], ["A", "12,5"]], "Leer": []})
    ex = extract_text(data, "fls.ods")
    assert ex.page_count == 2
    assert "--- Blatt 1: FLS 2025 ---\nKlient\tStunden\nA\t12,5" in ex.text
    assert len(ex.text) < 200  # the 1M padded rows/cols are not expanded


def test_xlsx():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Kosten"
    ws.append(["Gewerk", "Netto"])
    ws.append(["Dach", 12000])
    buf = io.BytesIO()
    wb.save(buf)
    ex = extract_text(buf.getvalue(), "kosten.xlsx")
    assert "--- Blatt 1: Kosten ---\nGewerk\tNetto\nDach\t12000" in ex.text


def test_pptx_slides():
    ex = extract_text(make_pptx([["Titel"], ["Folie zwei", "Punkt"]]), "v.pptx")
    assert ex.page_count == 2 and ex.page_label == "Folie"
    assert "--- Folie 2 ---\nFolie zwei\nPunkt" in ex.text


def test_csv_html_text_eml():
    assert extract_text(b"a;b\n1;2", "x.csv").text == "a\tb\n1\t2"
    assert extract_text(b"<p>Hallo&nbsp;Welt</p>", "x.html").text == "Hallo Welt"
    assert extract_text("Grüße".encode("cp1252"), "x.txt").text == "Grüße"
    inner = EmailMessage()
    inner["Subject"] = "Weitergeleitet"
    inner["From"] = "x@example.org"
    inner.set_content("Innerer Text")
    ex = extract_text(inner.as_bytes(), "fwd.eml")
    assert "Subject: Weitergeleitet" in ex.text and "Innerer Text" in ex.text


def test_unsupported_and_broken_files():
    with pytest.raises(ExtractionError, match="transfer_to_paperless"):
        extract_text(b"\x89PNG\r\n\x1a\n....", "foto.png", "image/png")
    with pytest.raises(ExtractionError):
        extract_text(b"%PDF-1.4 kaputt", "kaputt.pdf")
    with pytest.raises(ExtractionError):
        extract_text(b"PK\x03\x04 kein zip", "x.docx")


def test_parse_page_spec():
    assert parse_page_spec("3", 10) == [3]
    assert parse_page_spec("2-4,7", 10) == [2, 3, 4, 7]
    assert parse_page_spec("8-", 10) == [8, 9, 10]
    assert parse_page_spec("12", 10) == []


# ---------------------------------------------------------------------------
# Tool: slices, pages, search, cache, no \Seen
# ---------------------------------------------------------------------------


async def test_large_pdf_read_in_slices_pages_and_search(imap):  # noqa: F811
    pdf, _ = _long_pdf(60)
    uid = imap.add(
        _mail_with(
            ("foto.jpg", "image/jpeg", b"\xff\xd8\xff"),
            ("Foerderbescheid.pdf", "application/pdf", pdf),
        )
    )

    first = ast.literal_eval(
        await _call("get_attachment_text", uid=str(uid), filename="Foerderbescheid.pdf")
    )
    assert first["source"] == "imap" and first["kind"] == "pdf"
    assert first["page_count"] == 60 and first["truncated"] is True
    assert len(first["text"]) == 15000 < first["text_length"]
    assert first["attachments"] == ["foto.jpg", "Foerderbescheid.pdf"]

    # read everything in slices and compare with a one-shot extraction
    full = extract_text(pdf, "Foerderbescheid.pdf").text
    chunks, offset = [], 0
    while offset is not None:
        page = ast.literal_eval(
            await _call(
                "get_attachment_text",
                uid=str(uid),
                filename="Foerderbescheid.pdf",
                offset=offset,
                max_chars=40000,
            )
        )
        chunks.append(page["text"])
        offset = page["next_offset"]
    assert "".join(chunks) == full

    p42 = ast.literal_eval(
        await _call("get_attachment_text", uid=str(uid), filename="Foerderbescheid.pdf", pages="42")
    )
    assert p42["text"].startswith("--- Seite 42 ---")
    assert "Seite 43" not in p42["text"] and p42["truncated"] is False

    hits = ast.literal_eval(
        await _call(
            "get_attachment_text",
            uid=str(uid),
            filename="Foerderbescheid.pdf",
            query="Förderbetrag",
        )
    )
    assert hits["total_hits"] == 1 and hits["hits"][0]["page"] == 42
    assert "12.345,67 EUR" in hits["hits"][0]["snippet"]
    assert "text" not in hits

    # an image attachment is reported, not parsed
    img = ast.literal_eval(await _call("get_attachment_text", uid=str(uid), filename="foto.jpg"))
    assert "transfer_to_paperless" in img["error"]

    assert SEEN not in imap.flags(uid)


async def test_text_is_cached_after_first_read(imap):  # noqa: F811
    uid = imap.add(_mail_with(("a.pdf", "application/pdf", make_pdf([["Eins"], ["Zwei"]]))))
    _sync(imap)
    first = ast.literal_eval(await _call("get_attachment_text", uid=str(uid)))
    assert first["source"] == "cache"  # bytes from the mail cache, parsed once
    again = ast.literal_eval(await _call("get_attachment_text", uid=str(uid), pages="2"))
    assert again["source"] == "text-cache"
    assert again["text"] == "--- Seite 2 ---\nZwei"
    assert SEEN not in imap.flags(uid)


async def test_unknown_filename_lists_attachments(imap):  # noqa: F811
    uid = imap.add(_mail_with(("a.pdf", "application/pdf", make_pdf([["x"]]))))
    out = ast.literal_eval(await _call("get_attachment_text", uid=str(uid), filename="b.pdf"))
    assert "No attachment 'b.pdf'" in out["error"] and out["attachments"] == ["a.pdf"]


async def test_size_limit(imap, monkeypatch):  # noqa: F811
    monkeypatch.setattr(tools, "_ATTACHMENT_TEXT_MAX_BYTES", 100)
    uid = imap.add(_mail_with(("a.pdf", "application/pdf", make_pdf([["x" * 200]]))))
    out = ast.literal_eval(await _call("get_attachment_text", uid=str(uid)))
    assert "transfer_to_paperless" in out["error"]


async def test_tool_listed_without_db(monkeypatch):
    monkeypatch.setattr(tools, "_DB_ENABLED", False)
    assert "get_attachment_text" in [t.name for t in tools.get_all_tools()]
