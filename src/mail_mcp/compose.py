"""Compose reply / forward / new messages the way Spark expects them.

Shared by the draft tools (IMAP APPEND) and the send tools (SMTP), so a
reply looks the same whether it is saved as a draft or sent directly.

What this module adds on top of the raw MIME builder:

* quote of the original in **both** parts – Spark renders the HTML part,
  so a quote that only lives in ``text/plain`` is invisible there;
* German quote header with decoded sender name and local time
  (``Am 22. Juni 2026, 13:32 +0200 schrieb Jörg Müller <…>:``);
* HTML→text conversion without leftover entities (``&nbsp;``);
* server-side signature from files (``SIGNATURE_HTML_FILE`` /
  ``SIGNATURE_TEXT_FILE``), because Spark does not insert its own
  signature into drafts created from outside;
* the Spark section layout (``messageBodySection`` /
  ``messageSignatureSection`` / ``messageReplySection``), skipping any
  section the caller already supplied.
"""

from __future__ import annotations

import html as html_lib
import logging
import os
import re
from dataclasses import dataclass, field
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.utils import formataddr, getaddresses, parsedate_to_datetime
from functools import lru_cache
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Europe/Berlin")
_MONTHS = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]

_BLOCKQUOTE_STYLE = (
    "border-left-color: grey; border-left-width: thin; border-left-style: solid; "
    "margin: 5px 5px; padding-left: 10px;"
)

SIGNATURE_SECTION = 'name="messageSignatureSection"'
REPLY_SECTION = 'name="messageReplySection"'
BODY_SECTION = 'name="messageBodySection"'


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------


def _read_file(path: str) -> str:
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError as exc:
        logger.warning("Signaturdatei %s nicht lesbar: %s", path, exc)
        return ""


@dataclass(frozen=True)
class ComposeConfig:
    """Per-instance settings, read once from the environment.

    Environment variables:
        FROM_NAME            – display name for the From header
        SIGNATURE_HTML_FILE  – HTML signature (inserted as messageSignatureSection)
        SIGNATURE_TEXT_FILE  – plain-text signature for the text/plain part
        SIGNATURE_MARKER     – text that marks a signature already present in
                               body_text (default: the whole text signature)
    """

    from_name: str = ""
    signature_html: str = ""
    signature_text: str = ""
    signature_marker: str = ""

    @classmethod
    def from_env(cls) -> ComposeConfig:
        return cls(
            from_name=os.getenv("FROM_NAME", "").strip(),
            signature_html=_read_file(os.getenv("SIGNATURE_HTML_FILE", "")),
            signature_text=_read_file(os.getenv("SIGNATURE_TEXT_FILE", "")),
            signature_marker=os.getenv("SIGNATURE_MARKER", "").strip(),
        )

    @property
    def has_signature(self) -> bool:
        return bool(self.signature_html or self.signature_text)


@lru_cache(maxsize=1)
def get_compose_config() -> ComposeConfig:
    return ComposeConfig.from_env()


# -----------------------------------------------------------------------------
# Header helpers
# -----------------------------------------------------------------------------


def decode_mime_header(value: str | None) -> str:
    """Decode RFC 2047 encoded words (``=?UTF-8?Q?J=C3=B6rg?=``) to Unicode."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(str(value))))
    except (LookupError, UnicodeDecodeError, ValueError):
        return str(value)


_RE_ONLY_RX = re.compile(r"^(?:(?:re|aw|antw)\s*:\s*)+", re.IGNORECASE)
_FWD_ONLY_RX = re.compile(r"^(?:(?:fwd?|wg)\s*:\s*)+", re.IGNORECASE)


def strip_reply_prefixes(subject: str) -> str:
    """``Re: AW: Re: x`` → ``x`` (only reply prefixes)."""
    return _RE_ONLY_RX.sub("", subject).strip()


def strip_forward_prefixes(subject: str) -> str:
    """``Fwd: WG: x`` → ``x`` (only forward prefixes)."""
    return _FWD_ONLY_RX.sub("", subject).strip()


def reply_subject(original_subject: str | None) -> str:
    subject = strip_reply_prefixes(decode_mime_header(original_subject))
    return f"Re: {subject}" if subject else "Re: (kein Betreff)"


def forward_subject(original_subject: str | None) -> str:
    subject = strip_forward_prefixes(decode_mime_header(original_subject))
    return f"Fwd: {subject}" if subject else "Fwd: (kein Betreff)"


def format_address_list(value: str | None) -> str:
    """Decoded ``Name <addr>, …`` for display in quote headers."""
    if not value:
        return ""
    pairs = getaddresses([decode_mime_header(value)])
    out = []
    for name, addr in pairs:
        if name and addr:
            out.append(f"{name} <{addr}>")
        elif addr:
            out.append(addr)
    return ", ".join(out)


def german_date(date_header: str | None) -> str:
    """``Mon, 22 Jun 2026 11:32:19 +0000`` → ``22. Juni 2026, 13:32 +0200``."""
    if not date_header:
        return ""
    try:
        dt = parsedate_to_datetime(str(date_header))
    except (TypeError, ValueError):
        return str(date_header)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    local = dt.astimezone(_TZ)
    return f"{local.day}. {_MONTHS[local.month - 1]} {local.year}, {local:%H:%M %z}"


def quote_header(original: Message) -> str:
    date = german_date(original.get("Date"))
    sender = format_address_list(original.get("From")) or "unbekannt"
    return f"Am {date} schrieb {sender}:" if date else f"{sender} schrieb:"


# -----------------------------------------------------------------------------
# Body extraction / conversion
# -----------------------------------------------------------------------------


def _decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def extract_bodies(msg: Message) -> tuple[str, str]:
    """Return the first inline ``text/plain`` and ``text/html`` bodies."""
    text = html = ""
    for part in msg.walk():
        if part.is_multipart():
            continue
        if "attachment" in (part.get("Content-Disposition") or "").lower():
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain" and not text:
            text = _decode_part(part)
        elif ctype == "text/html" and not html:
            html = _decode_part(part)
    return text, html


_BLOCK_TAGS = {
    "p",
    "div",
    "tr",
    "li",
    "ul",
    "ol",
    "table",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "pre",
}
_SKIP_TAGS = {"script", "style", "head", "title"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "td":
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Strip tags, decode entities, turn block elements into line breaks."""
    if not html:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ").replace("\r", "")
    # HTML source line breaks are whitespace, not paragraph breaks.
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def text_to_html(text: str) -> str:
    return html_lib.escape(text).replace("\r\n", "\n").replace("\n", "<br />\n")


_BODY_RX = re.compile(r"<body\b[^>]*>(.*?)(?:</body\s*>|\Z)", re.IGNORECASE | re.DOTALL)
_STRIP_BLOCK_RX = re.compile(
    r"<(script|style|head|title)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)
_STRIP_TAG_RX = re.compile(r"</?(?:html|body|head|meta|link|base)\b[^>]*>|<!DOCTYPE[^>]*>", re.I)
_CID_IMG_RX = re.compile(r"<img\b[^>]*\bsrc\s*=\s*[\"']?cid:[^>]*>", re.IGNORECASE)


def html_fragment(html: str) -> str:
    """Body content of an HTML document, safe to embed in a quote."""
    m = _BODY_RX.search(html)
    inner = m.group(1) if m else html
    inner = _STRIP_BLOCK_RX.sub("", inner)
    inner = _STRIP_TAG_RX.sub("", inner)
    # Inline images of the original are not carried over – drop them
    # instead of leaving broken cid: links.
    inner = _CID_IMG_RX.sub("", inner)
    return inner.strip()


# -----------------------------------------------------------------------------
# Quote sections
# -----------------------------------------------------------------------------


def _original_html_fragment(original: Message) -> str:
    text, html = extract_bodies(original)
    if html:
        return html_fragment(html)
    return text_to_html(text.rstrip())


def _original_text(original: Message) -> str:
    text, html = extract_bodies(original)
    return (text or html_to_text(html)).rstrip()


def reply_quote_text(original: Message) -> str:
    body = _original_text(original)
    quoted = "\n".join(("> " + line) if line else ">" for line in body.splitlines())
    return f"{quote_header(original)}\n{quoted}" if quoted else quote_header(original)


def reply_quote_html(original: Message) -> str:
    header = html_lib.escape(quote_header(original))
    return (
        f"<div {REPLY_SECTION}>{header}<br />\n"
        f'<blockquote type="cite" style="{_BLOCKQUOTE_STYLE}">\n'
        f"{_original_html_fragment(original)}\n"
        "</blockquote></div>"
    )


def _forward_header_lines(original: Message) -> list[tuple[str, str]]:
    lines = [
        ("Von", format_address_list(original.get("From"))),
        ("Datum", german_date(original.get("Date"))),
        ("Betreff", decode_mime_header(original.get("Subject"))),
        ("An", format_address_list(original.get("To"))),
    ]
    if original.get("Cc"):
        lines.append(("Cc", format_address_list(original.get("Cc"))))
    return lines


_FORWARD_TITLE = "---------- Weitergeleitete Nachricht ----------"


def forward_quote_text(original: Message) -> str:
    head = "\n".join(f"{k}: {v}" for k, v in _forward_header_lines(original))
    return f"{_FORWARD_TITLE}\n{head}\n\n{_original_text(original)}"


def forward_quote_html(original: Message) -> str:
    head = "<br />\n".join(
        f"<b>{k}:</b> {html_lib.escape(v)}" for k, v in _forward_header_lines(original)
    )
    return (
        f"<div {REPLY_SECTION}>{_FORWARD_TITLE}<br />\n{head}<br />\n"
        f'<blockquote type="cite" style="{_BLOCKQUOTE_STYLE}">\n'
        f"{_original_html_fragment(original)}\n"
        "</blockquote></div>"
    )


# -----------------------------------------------------------------------------
# Body assembly
# -----------------------------------------------------------------------------


@dataclass
class Quote:
    text: str
    html: str


def _has_text_signature(body_text: str, cfg: ComposeConfig) -> bool:
    marker = cfg.signature_marker or cfg.signature_text
    return bool(marker) and marker in body_text


def _has_text_quote(body_text: str) -> bool:
    return any(line.startswith(">") for line in body_text.splitlines())


def assemble_bodies(
    body_text: str | None,
    body_html: str | None,
    *,
    signature: bool = True,
    quote: Quote | None = None,
    cfg: ComposeConfig | None = None,
) -> tuple[str | None, str | None]:
    """Combine body, signature and quote in Spark's order for both parts.

    Order: body → signature → quote. A section the caller already put in
    the body (detected via Spark's ``name="message…Section"`` markers or,
    for text, the signature marker / ``>``-quoted lines) is not added
    twice. An HTML part is created when the caller gave HTML or when
    there is an HTML signature/quote to show; otherwise the message stays
    plain text. A missing text part is derived from the HTML.
    """
    cfg = cfg or get_compose_config()
    body_text = body_text or ""
    body_html = body_html or ""

    html_has_sig = SIGNATURE_SECTION in body_html
    html_has_quote = REPLY_SECTION in body_html

    # --- text/plain ------------------------------------------------------
    text = body_text if body_text else html_to_text(body_html)
    text_parts = [text.rstrip()] if text.strip() else []
    if signature and cfg.signature_text and not (html_has_sig or _has_text_signature(text, cfg)):
        text_parts.append(cfg.signature_text)
    if quote and quote.text and not (html_has_quote or _has_text_quote(text)):
        text_parts.append(quote.text)
    final_text = "\n\n".join(text_parts)

    # --- text/html -------------------------------------------------------
    sig_html = cfg.signature_html or (
        text_to_html(cfg.signature_text) if cfg.signature_text else ""
    )
    add_sig_html = bool(signature and sig_html and not html_has_sig)
    add_quote_html = bool(quote and quote.html and not html_has_quote)

    # A text-only signature alone does not justify an HTML part.
    if not body_html and not add_quote_html and not (add_sig_html and cfg.signature_html):
        return final_text or None, None

    sections: list[str] = []
    if body_html and "<html" in body_html.lower():
        # Full document from the caller: insert our sections before </body>.
        extra = []
        if add_sig_html:
            extra.append(f"<div {SIGNATURE_SECTION}><br />{sig_html}</div>")
        if add_quote_html:
            extra.append(quote.html)  # type: ignore[union-attr]
        if not extra:
            return final_text or None, body_html
        joined = "\n".join(extra)
        m = re.search(r"</body\s*>", body_html, re.IGNORECASE)
        if m:
            return final_text or None, body_html[: m.start()] + joined + "\n" + body_html[
                m.start() :
            ]
        return final_text or None, body_html + "\n" + joined

    if body_html:
        inner = body_html
    else:
        inner = text_to_html(body_text) if body_text else ""
    if inner:
        if BODY_SECTION in inner:
            sections.append(inner)
        else:
            sections.append(f'<div {BODY_SECTION}><div dir="auto">{inner}</div></div>')
    if add_sig_html:
        sections.append(f"<div {SIGNATURE_SECTION}><br />{sig_html}</div>")
    if add_quote_html:
        sections.append(quote.html)  # type: ignore[union-attr]

    html_doc = (
        '<html><head><meta charset="utf-8"></head><body>\n'
        + "\n".join(sections)
        + "\n</body></html>"
    )
    return final_text or None, html_doc


# -----------------------------------------------------------------------------
# Reply / forward composition from an original message
# -----------------------------------------------------------------------------


def fetch_original(connection, folder: str, uid: int) -> Message:
    """Fetch an original message by UID (``imaplib`` connection)."""
    typ, _ = connection.select(folder)
    if typ != "OK":
        raise RuntimeError(f"Could not SELECT folder {folder!r}")
    typ, data = connection.uid("FETCH", str(int(uid)), "(BODY.PEEK[])")
    if typ != "OK" or not data:
        raise RuntimeError(f"Could not fetch UID {uid} from {folder!r}: {typ}")
    for entry in data:
        if isinstance(entry, tuple) and len(entry) >= 2:
            return message_from_bytes(entry[1])
    raise RuntimeError(f"UID {uid} not found in {folder!r}")


def find_uid_by_message_id(connection, folder: str, message_id: str) -> int:
    """Look up a message's UID by its ``Message-ID`` header."""
    typ, _ = connection.select(folder)
    if typ != "OK":
        raise RuntimeError(f"Could not SELECT folder {folder!r}")
    mid = message_id.strip()
    if not mid.startswith("<"):
        mid = f"<{mid}>"
    typ, data = connection.uid("SEARCH", None, "HEADER", "Message-ID", f'"{mid}"')
    uids = (data[0] or b"").split() if typ == "OK" and data else []
    if not uids:
        raise RuntimeError(f"Message-ID {mid} not found in {folder!r}")
    return int(uids[-1])


def references_for_reply(original: Message) -> str:
    """Previous ``References`` (or ``In-Reply-To``) + previous ``Message-ID``."""
    parts: list[str] = []
    prev_refs = original.get("References", "")
    if prev_refs:
        parts.extend(str(prev_refs).split())
    elif original.get("In-Reply-To"):
        parts.append(str(original["In-Reply-To"]).strip())
    msg_id = original.get("Message-ID")
    if msg_id and str(msg_id).strip() not in parts:
        parts.append(str(msg_id).strip())
    return " ".join(parts)


@dataclass
class Composed:
    to: list[str]
    subject: str
    body_text: str | None
    body_html: str | None
    cc: list[str] | None = None
    bcc: list[str] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    attachments: list[dict] | None = None


def compose_reply(
    original: Message,
    *,
    own_address: str,
    body_text: str | None,
    body_html: str | None,
    reply_all: bool = False,
    include_quote: bool = True,
    signature: bool = True,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    attachments: list[dict] | None = None,
    cfg: ComposeConfig | None = None,
) -> Composed:
    if not body_text and not body_html:
        raise ValueError("body_text or body_html is required")

    if to is None:
        reply_field = original.get("Reply-To") or original.get("From") or ""
        to = [
            formataddr((name, addr), charset="utf-8") if name else addr
            for name, addr in getaddresses([decode_mime_header(reply_field)])
            if addr
        ]
    if cc is None and reply_all:
        own = own_address.lower()
        to_addrs = {addr.lower() for _n, addr in getaddresses(to)}
        cc = [
            addr
            for _n, addr in getaddresses(original.get_all("To", []) + original.get_all("Cc", []))
            if addr and addr.lower() != own and addr.lower() not in to_addrs
        ] or None

    quote = (
        Quote(text=reply_quote_text(original), html=reply_quote_html(original))
        if include_quote
        else None
    )
    text, html = assemble_bodies(body_text, body_html, signature=signature, quote=quote, cfg=cfg)

    headers: dict[str, str] = {}
    if original.get("Message-ID"):
        headers["In-Reply-To"] = str(original["Message-ID"]).strip()
    refs = references_for_reply(original)
    if refs:
        headers["References"] = refs

    return Composed(
        to=to,
        cc=cc,
        subject=reply_subject(original.get("Subject")),
        body_text=text,
        body_html=html,
        headers=headers,
        attachments=attachments,
    )


def original_attachments(original: Message) -> list[dict]:
    """Attachments of the original as base64 attachment dicts."""
    import base64

    out: list[dict] = []
    if not original.is_multipart():
        return out
    for part in original.walk():
        if part.is_multipart():
            continue
        disp = (part.get("Content-Disposition") or "").lower()
        if "attachment" not in disp and not part.get_filename():
            continue
        data = part.get_payload(decode=True)
        if not data:
            continue
        out.append(
            {
                "filename": decode_mime_header(part.get_filename()) or "attachment.bin",
                "content_type": part.get_content_type(),
                "data_base64": base64.b64encode(data).decode("ascii"),
            }
        )
    return out


def compose_forward(
    original: Message,
    *,
    to: list[str],
    body_text: str | None = None,
    body_html: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    forward_attachments: bool = True,
    attachments: list[dict] | None = None,
    signature: bool = True,
    cfg: ComposeConfig | None = None,
) -> Composed:
    quote = Quote(text=forward_quote_text(original), html=forward_quote_html(original))
    text, html = assemble_bodies(body_text, body_html, signature=signature, quote=quote, cfg=cfg)
    atts = (original_attachments(original) if forward_attachments else []) + list(attachments or [])
    headers: dict[str, str] = {}
    refs = references_for_reply(original)
    if refs:
        headers["References"] = refs
    return Composed(
        to=to,
        cc=cc,
        bcc=bcc,
        subject=forward_subject(original.get("Subject")),
        body_text=text,
        body_html=html,
        headers=headers,
        attachments=atts or None,
    )


__all__ = [
    "ComposeConfig",
    "Composed",
    "Quote",
    "assemble_bodies",
    "compose_forward",
    "compose_reply",
    "decode_mime_header",
    "fetch_original",
    "find_uid_by_message_id",
    "forward_subject",
    "get_compose_config",
    "german_date",
    "html_to_text",
    "quote_header",
    "references_for_reply",
    "reply_subject",
]
