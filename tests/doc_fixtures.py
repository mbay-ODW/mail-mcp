"""Small, dependency-free builders for test documents (PDF, DOCX, ODT, ODS, PPTX)."""

from __future__ import annotations

import io
import zipfile


def _pdf_escape(line: str) -> bytes:
    raw = line.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def make_pdf(pages: list[list[str] | None]) -> bytes:
    """PDF with one page per entry; each entry is a list of text lines.

    ``None`` creates a page without any text (like a scanned image page).
    Text uses Helvetica with WinAnsiEncoding, so German umlauts work.
    """
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    pages_id = len(objects) + 1 + 2 * len(pages)  # reserved after content/page objects
    page_ids = []
    for lines in pages:
        if lines:
            ops = [b"BT /F1 11 Tf 14 TL 50 800 Td"]
            for line in lines:
                ops.append(b"(" + _pdf_escape(line) + b") Tj T*")
            ops.append(b"ET")
            stream = b"\n".join(ops)
        else:
            stream = b"0.9 g 50 50 400 700 re f"  # grey box, no text
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] "
                b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                % (pages_id, font, content)
            )
        )
    kids = b" ".join(b"%d 0 R" % i for i in page_ids)
    assert add(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids))) == pages_id
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(
        b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, catalog, xref)
    )
    return out.getvalue()


def _zip(files: dict[str, str], mimetype: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if mimetype:
            zf.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    if table:
        rows = "".join(
            "<w:tr>"
            + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row)
            + "</w:tr>"
            for row in table
        )
        body += f"<w:tbl>{rows}</w:tbl>"
    doc = f'<?xml version="1.0" encoding="UTF-8"?><w:document {_W}><w:body>{body}</w:body></w:document>'
    return _zip({"[Content_Types].xml": "<Types/>", "word/document.xml": doc})


_ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"'
)


def make_odt(paragraphs: list[str]) -> bytes:
    body = "".join(f"<text:p>{p}</text:p>" for p in paragraphs)
    content = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {_ODF_NS}>'
        f"<office:body><office:text>{body}</office:text></office:body></office:document-content>"
    )
    return _zip({"content.xml": content}, "application/vnd.oasis.opendocument.text")


def make_ods(sheets: dict[str, list[list[str]]]) -> bytes:
    tables = ""
    for name, rows in sheets.items():
        xml_rows = "".join(
            "<table:table-row>"
            + "".join(f"<table:table-cell><text:p>{c}</text:p></table:table-cell>" for c in row)
            # LibreOffice pads every row with a huge repeated empty cell
            + '<table:table-cell table:number-columns-repeated="16378"/>'
            + "</table:table-row>"
            for row in rows
        )
        # ... and every sheet with ~1M repeated empty rows
        xml_rows += (
            '<table:table-row table:number-rows-repeated="1048000">'
            '<table:table-cell table:number-columns-repeated="16384"/></table:table-row>'
        )
        tables += f'<table:table table:name="{name}">{xml_rows}</table:table>'
    content = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {_ODF_NS}>'
        f"<office:body><office:spreadsheet>{tables}</office:spreadsheet></office:body>"
        "</office:document-content>"
    )
    return _zip({"content.xml": content}, "application/vnd.oasis.opendocument.spreadsheet")


def make_pptx(slides: list[list[str]]) -> bytes:
    ns = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    files = {"ppt/presentation.xml": "<p/>"}
    for i, paras in enumerate(slides, start=1):
        ps = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in paras)
        files[f"ppt/slides/slide{i}.xml"] = f"<sld {ns}><a:txBody>{ps}</a:txBody></sld>"
    return _zip(files)
