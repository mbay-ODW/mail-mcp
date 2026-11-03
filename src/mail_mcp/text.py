"""Plain-text helpers for mail bodies (HTML → text, paging)."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
    "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
    "table", "tr", "ul",
}  # fmt: skip
_SKIP_TAGS = {"head", "script", "style", "template", "title", "noscript"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._pre_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "pre":
            self._pre_depth += 1
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")
        if tag in ("td", "th"):
            self._parts.append("\t")
        if tag == "li":
            self._parts.append("- ")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "pre" and self._pre_depth:
            self._pre_depth -= 1
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if not self._pre_depth:
            data = re.sub(r"\s+", " ", data)
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str | None) -> str:
    """Convert an HTML mail body into readable plain text (stdlib only)."""
    if not html:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
        text = parser.text()
    except Exception:
        text = unescape(re.sub(r"<[^>]+>", " ", html))
    text = text.replace("\xa0", " ")
    lines = [line.strip(" \t") for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def page_text(text: str, offset: int = 0, max_chars: int = 20000) -> dict:
    """Return one page of ``text``, counted in characters (never splits a code point)."""
    total = len(text)
    offset = max(0, int(offset or 0))
    max_chars = max(1, int(max_chars or 1))
    chunk = text[offset : offset + max_chars]
    end = offset + len(chunk)
    truncated = end < total
    return {
        "body_text": chunk,
        "body_length": total,
        "offset": offset,
        "truncated": truncated,
        "next_offset": end if truncated else None,
    }
