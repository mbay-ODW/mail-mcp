"""Text extraction from mail attachments (PDF, Office, OpenDocument, text, HTML, mail).

The attachment never leaves the server: callers get plain text, page markers and
offsets so an agent can read a large document piece by piece instead of loading
the whole file into its context.

Only pure-Python parsers are used (pypdf, openpyxl, stdlib zip/XML), so the
image stays small. Scanned PDFs without a text layer are reported with
``needs_ocr=True``; OCR itself is left to Paperless (``transfer_to_paperless``).
"""

from __future__ import annotations

import csv
import email
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from email.policy import default as default_policy
from xml.etree import ElementTree as ET

from .text import html_to_text

logger = logging.getLogger(__name__)

# Limits that keep a single extraction bounded in time and memory.
MAX_PDF_PAGES = 1000
MAX_ZIP_MEMBER_BYTES = 64 * 1024 * 1024  # decompressed size of one XML part
MAX_SHEET_ROWS = 20000
MAX_SHEET_COLS = 200
MAX_TEXT_CHARS = 5_000_000

# A page with fewer visible characters counts as "no text" (scan / image only).
_EMPTY_PAGE_CHARS = 10


class ExtractionError(Exception):
    """The attachment could not be read as text."""


@dataclass
class Extracted:
    text: str
    kind: str
    # (page/sheet/slide number, character offset where it starts in ``text``)
    pages: list[tuple[int, int]] = field(default_factory=list)
    page_label: str = "Seite"
    needs_ocr: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)


# ---------------------------------------------------------------------------
# Type detection
# ---------------------------------------------------------------------------

_EXT_KIND = {
    "pdf": "pdf",
    "docx": "docx",
    "docm": "docx",
    "xlsx": "xlsx",
    "xlsm": "xlsx",
    "pptx": "pptx",
    "odt": "odt",
    "ods": "ods",
    "odp": "odp",
    "txt": "text",
    "text": "text",
    "log": "text",
    "md": "text",
    "csv": "csv",
    "tsv": "csv",
    "json": "text",
    "xml": "text",
    "ics": "text",
    "vcf": "text",
    "htm": "html",
    "html": "html",
    "eml": "eml",
}

_MIME_KIND = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/vnd.oasis.opendocument.presentation": "odp",
    "text/plain": "text",
    "text/csv": "csv",
    "text/html": "html",
    "message/rfc822": "eml",
}

UNSUPPORTED_HINT = (
    "No text extraction for this file type (e.g. images, legacy .doc/.xls, archives). "
    "Use transfer_to_paperless – Paperless runs OCR – and read the text there."
)


def detect_kind(data: bytes, filename: str | None, content_type: str | None) -> str | None:
    """Return the parser kind for an attachment, or None if unsupported."""
    if data[:5] == b"%PDF-":
        return "pdf"
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if ext in _EXT_KIND:
        return _EXT_KIND[ext]
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _MIME_KIND:
        return _MIME_KIND[ct]
    if data[:2] == b"PK":
        # Zip container without a telling name: look inside.
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
                if "word/document.xml" in names:
                    return "docx"
                if "xl/workbook.xml" in names:
                    return "xlsx"
                if "ppt/presentation.xml" in names:
                    return "pptx"
                if "mimetype" in names:
                    mt = zf.read("mimetype").decode("ascii", "ignore").strip()
                    return _MIME_KIND.get(mt)
        except zipfile.BadZipFile:
            return None
    if ct.startswith("text/"):
        return "text"
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_text(data: bytes, filename: str | None = None, content_type: str | None = None):
    """Extract plain text from an attachment. Raises ExtractionError."""
    kind = detect_kind(data, filename, content_type)
    if kind is None:
        raise ExtractionError(UNSUPPORTED_HINT)
    parser = _PARSERS[kind]
    try:
        result = parser(data)
    except ExtractionError:
        raise
    except Exception as exc:  # malformed files must not break the tool call
        logger.warning("extract_text(%s, %s) failed: %s", filename, kind, exc)
        raise ExtractionError(f"Could not read {kind} file: {exc}") from exc
    if len(result.text) > MAX_TEXT_CHARS:
        result.text = result.text[:MAX_TEXT_CHARS]
        result.pages = [p for p in result.pages if p[1] < MAX_TEXT_CHARS]
        result.warnings.append(f"Text cut at {MAX_TEXT_CHARS} characters.")
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _PagedText:
    """Builds text with page markers and records where each page starts."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.parts: list[str] = []
        self.pages: list[tuple[int, int]] = []
        self.length = 0

    def add_page(self, number: int, text: str, title: str | None = None) -> None:
        header = f"--- {self.label} {number}" + (f": {title}" if title else "") + " ---\n"
        sep = "\n\n" if self.parts else ""
        self.pages.append((number, self.length + len(sep)))
        chunk = sep + header + text.strip("\n")
        self.parts.append(chunk)
        self.length += len(chunk)

    def text(self) -> str:
        return "".join(self.parts)


def _decode_text(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    for enc in ("utf-8", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _zip_xml(zf: zipfile.ZipFile, name: str) -> ET.Element:
    info = zf.getinfo(name)
    if info.file_size > MAX_ZIP_MEMBER_BYTES:
        raise ExtractionError(f"{name} is too large to extract ({info.file_size} bytes).")
    return ET.fromstring(zf.read(name))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _pdf(data: bytes) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except PdfReadError as exc:
        raise ExtractionError(f"Not a readable PDF: {exc}") from exc
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise ExtractionError("PDF is password protected.")
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"PDF is encrypted and cannot be opened: {exc}") from exc

    total = len(reader.pages)
    out = _PagedText("Seite")
    warnings: list[str] = []
    empty_pages = 0
    for i, page in enumerate(reader.pages, start=1):
        if i > MAX_PDF_PAGES:
            warnings.append(f"Only the first {MAX_PDF_PAGES} of {total} pages were read.")
            break
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # one broken page should not lose the rest
            text = ""
            warnings.append(f"Page {i} could not be read: {exc}")
        text = _tidy(text)
        if len(re.sub(r"\s", "", text)) < _EMPTY_PAGE_CHARS:
            empty_pages += 1
        out.add_page(i, text)

    read_pages = min(total, MAX_PDF_PAGES)
    # Scanned documents: most pages carry no text layer at all.
    needs_ocr = read_pages > 0 and empty_pages * 2 > read_pages
    if needs_ocr:
        warnings.append(
            "PDF has (almost) no text layer – probably scanned. Use transfer_to_paperless "
            "for OCR and read the text in Paperless."
        )
    elif empty_pages:
        warnings.append(f"{empty_pages} page(s) without text (images/scans?).")
    return Extracted(out.text(), "pdf", out.pages, "Seite", needs_ocr, warnings)


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_block(elem: ET.Element, lines: list[str]) -> None:
    for child in elem:
        tag = _local(child.tag)
        if tag == "p":
            lines.append(_docx_paragraph(child))
        elif tag == "tbl":
            for row in child.iter(f"{_W}tr"):
                cells = []
                for cell in row.findall(f"{_W}tc"):
                    cell_lines: list[str] = []
                    _docx_block(cell, cell_lines)
                    cells.append(" ".join(x for x in cell_lines if x))
                lines.append("\t".join(cells))
            lines.append("")
        elif tag in ("sdt", "sdtContent", "customXml"):
            _docx_block(child, lines)


def _docx_paragraph(p: ET.Element) -> str:
    parts: list[str] = []
    for node in p.iter():
        tag = _local(node.tag)
        if tag == "t" and node.text:
            parts.append(node.text)
        elif tag == "tab":
            parts.append("\t")
        elif tag in ("br", "cr"):
            parts.append("\n")
    return "".join(parts)


def _docx(data: bytes) -> Extracted:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        root = _zip_xml(zf, "word/document.xml")
        body = root.find(f"{_W}body")
        lines: list[str] = []
        if body is not None:
            _docx_block(body, lines)
        extra = []
        for name in sorted(zf.namelist()):
            if re.fullmatch(r"word/(footnotes|endnotes)\.xml", name):
                notes: list[str] = []
                for p in _zip_xml(zf, name).iter(f"{_W}p"):
                    t = _docx_paragraph(p)
                    if t.strip():
                        notes.append(t)
                if notes:
                    extra.append("\n".join(notes))
    text = _tidy("\n".join(lines))
    if extra:
        text += "\n\n--- Fußnoten ---\n" + _tidy("\n".join(extra))
    return Extracted(text, "docx")


_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _pptx(data: bytes) -> Extracted:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        slides = sorted(
            (n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)),
        )
        out = _PagedText("Folie")
        for i, name in enumerate(slides, start=1):
            root = _zip_xml(zf, name)
            paras = []
            for p in root.iter(f"{_A}p"):
                t = "".join(node.text or "" for node in p.iter(f"{_A}t"))
                if t.strip():
                    paras.append(t)
            out.add_page(i, "\n".join(paras))
    return Extracted(out.text(), "pptx", out.pages, "Folie")


_ODF_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_ODF_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_ODF_DRAW = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"


def _odf_inline(elem: ET.Element) -> str:
    """Text of an ODF paragraph, honouring spaces, tabs and line breaks."""
    parts = [elem.text or ""]
    for child in elem:
        tag = _local(child.tag)
        if tag == "s":
            parts.append(" " * int(child.get(f"{{{_ODF_TEXT}}}c", "1")))
        elif tag == "tab":
            parts.append("\t")
        elif tag == "line-break":
            parts.append("\n")
        elif tag not in ("note", "annotation"):
            parts.append(_odf_inline(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _odf_paragraphs(elem: ET.Element, lines: list[str]) -> None:
    for child in elem:
        tag = _local(child.tag)
        if tag in ("p", "h"):
            lines.append(_odf_inline(child))
        elif tag == "table":
            for row in child.iter(f"{{{_ODF_TABLE}}}table-row"):
                cells = []
                for cell in row:
                    if _local(cell.tag) not in ("table-cell", "covered-table-cell"):
                        continue
                    cell_lines: list[str] = []
                    _odf_paragraphs(cell, cell_lines)
                    cells.append(" ".join(x for x in cell_lines if x))
                lines.append("\t".join(cells).rstrip("\t"))
            lines.append("")
        else:
            _odf_paragraphs(child, lines)


def _odt(data: bytes) -> Extracted:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        root = _zip_xml(zf, "content.xml")
    lines: list[str] = []
    for body in root.iter():
        if _local(body.tag) == "text" and body.tag.startswith(
            "{urn:oasis:names:tc:opendocument:xmlns:office"
        ):
            _odf_paragraphs(body, lines)
    return Extracted(_tidy("\n".join(lines)), "odt")


def _ods(data: bytes) -> Extracted:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        root = _zip_xml(zf, "content.xml")
    out = _PagedText("Blatt")
    warnings: list[str] = []
    rep_col = f"{{{_ODF_TABLE}}}number-columns-repeated"
    rep_row = f"{{{_ODF_TABLE}}}number-rows-repeated"
    for n, table in enumerate(root.iter(f"{{{_ODF_TABLE}}}table"), start=1):
        rows: list[str] = []
        row_count = 0
        for row in table.iter(f"{{{_ODF_TABLE}}}table-row"):
            cells: list[str] = []
            for cell in row:
                if _local(cell.tag) not in ("table-cell", "covered-table-cell"):
                    continue
                lines: list[str] = []
                _odf_paragraphs(cell, lines)
                value = " ".join(x for x in lines if x)
                repeat = min(int(cell.get(rep_col, "1")), MAX_SHEET_COLS)
                cells.extend([value] * repeat)
                if len(cells) >= MAX_SHEET_COLS:
                    break
            line = "\t".join(cells[:MAX_SHEET_COLS]).rstrip("\t")
            # Repeated empty rows pad sheets to 1M rows; only real content counts.
            repeat = int(row.get(rep_row, "1")) if line else 1
            for _ in range(min(repeat, MAX_SHEET_ROWS)):
                rows.append(line)
                row_count += 1
            if row_count >= MAX_SHEET_ROWS:
                warnings.append(f"Sheet {n}: only the first {MAX_SHEET_ROWS} rows were read.")
                break
        while rows and not rows[-1]:
            rows.pop()
        out.add_page(n, "\n".join(rows), table.get(f"{{{_ODF_TABLE}}}name"))
    return Extracted(out.text(), "ods", out.pages, "Blatt", warnings=warnings)


def _odp(data: bytes) -> Extracted:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        root = _zip_xml(zf, "content.xml")
    out = _PagedText("Folie")
    for n, page in enumerate(root.iter(f"{{{_ODF_DRAW}}}page"), start=1):
        lines: list[str] = []
        _odf_paragraphs(page, lines)
        out.add_page(n, _tidy("\n".join(lines)), page.get(f"{{{_ODF_DRAW}}}name"))
    return Extracted(out.text(), "odp", out.pages, "Folie")


def _xlsx(data: bytes) -> Extracted:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = _PagedText("Blatt")
    warnings: list[str] = []
    try:
        for n, ws in enumerate(wb.worksheets, start=1):
            rows: list[str] = []
            for r, row in enumerate(ws.iter_rows(values_only=True), start=1):
                if r > MAX_SHEET_ROWS:
                    warnings.append(f"Sheet {ws.title}: only the first {MAX_SHEET_ROWS} rows.")
                    break
                cells = ["" if v is None else str(v) for v in row[:MAX_SHEET_COLS]]
                rows.append("\t".join(cells).rstrip("\t"))
            while rows and not rows[-1]:
                rows.pop()
            out.add_page(n, "\n".join(rows), ws.title)
    finally:
        wb.close()
    return Extracted(out.text(), "xlsx", out.pages, "Blatt", warnings=warnings)


def _plain(data: bytes) -> Extracted:
    return Extracted(_tidy(_decode_text(data)), "text")


def _csv(data: bytes) -> Extracted:
    text = _decode_text(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t|")
        rows = ["\t".join(r) for r in csv.reader(io.StringIO(text), dialect)]
        return Extracted("\n".join(rows).strip(), "csv")
    except csv.Error:
        return Extracted(text.strip(), "csv")


def _html(data: bytes) -> Extracted:
    return Extracted(html_to_text(_decode_text(data)), "html")


def _eml(data: bytes) -> Extracted:
    msg = email.message_from_bytes(data, policy=default_policy)
    head = "\n".join(f"{h}: {msg[h]}" for h in ("From", "To", "Cc", "Date", "Subject") if msg[h])
    plain, html, names = "", "", []
    for part in msg.walk():
        if part.is_multipart():
            continue
        fname = part.get_filename()
        if fname:
            names.append(fname)
            continue
        ct = part.get_content_type()
        try:
            content = part.get_content()
        except Exception:
            continue
        if ct == "text/plain" and not plain:
            plain = content
        elif ct == "text/html" and not html:
            html = content
    body = plain if plain.strip() else html_to_text(html)
    text = head + "\n\n" + _tidy(body)
    if names:
        text += "\n\n[Anhänge der weitergeleiteten Mail: " + ", ".join(names) + "]"
    return Extracted(text, "eml")


_PARSERS = {
    "pdf": _pdf,
    "docx": _docx,
    "xlsx": _xlsx,
    "pptx": _pptx,
    "odt": _odt,
    "ods": _ods,
    "odp": _odp,
    "text": _plain,
    "csv": _csv,
    "html": _html,
    "eml": _eml,
}


# ---------------------------------------------------------------------------
# Slicing for the tool response
# ---------------------------------------------------------------------------


def parse_page_spec(spec: str | int | None, page_count: int) -> list[int]:
    """'3', '2-5', '1,4-6' → sorted page numbers within 1..page_count."""
    if spec is None or spec == "":
        return []
    wanted: set[int] = set()
    for part in str(spec).replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo = int(a) if a else 1
            hi = int(b) if b else page_count
            wanted.update(range(max(lo, 1), min(hi, page_count) + 1))
        else:
            n = int(part)
            if 1 <= n <= page_count:
                wanted.add(n)
    return sorted(wanted)


def page_ranges(pages: list[tuple[int, int]], text_len: int) -> dict[int, tuple[int, int]]:
    """Map page number → (start, end) character range."""
    ranges = {}
    for i, (num, start) in enumerate(pages):
        end = pages[i + 1][1] if i + 1 < len(pages) else text_len
        ranges[num] = (start, end)
    return ranges


def page_at(pages: list[tuple[int, int]], offset: int) -> int | None:
    current = None
    for num, start in pages:
        if start > offset:
            break
        current = num
    return current


def find_snippets(
    text: str,
    query: str,
    pages: list[tuple[int, int]],
    context: int = 300,
    max_hits: int = 20,
) -> tuple[int, list[dict]]:
    """Case-insensitive search; returns (total hits, snippets around the first hits)."""
    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    if not terms:
        return 0, []
    pattern = re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)
    hits = list(pattern.finditer(text))
    snippets: list[dict] = []
    last_end = -1
    for m in hits:
        if len(snippets) >= max_hits:
            break
        start = max(0, m.start() - context)
        end = min(len(text), m.end() + context)
        if start <= last_end:  # merge overlapping windows
            snippets[-1]["snippet"] = text[snippets[-1]["offset"] : end]
            last_end = end
            continue
        snippets.append(
            {"offset": start, "page": page_at(pages, m.start()), "snippet": text[start:end]}
        )
        last_end = end
    return len(hits), snippets
