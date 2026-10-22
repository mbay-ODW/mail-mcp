"""Draft email management operations.

Implements the *save / update / delete* lifecycle for IMAP drafts as well as
*reply* and *forward* variants that build the right In-Reply-To / References
headers and quote / attach the original message body.

All five functions ultimately go through the same MIME builder
(`smtp.operations.message.build_message`) and the same IMAP wrapper
(`EmailMove.append_email` for the upload, plus a UID-aware variant for
`save_*` so callers get the new draft's UID back).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from email.message import Message
from email.utils import make_msgid
from typing import Any

from .. import compose
from ..smtp import Attachment
from ..smtp.operations.message import build_message

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Drafts folder discovery
# -----------------------------------------------------------------------------

# Names we try in order when the IMAP server doesn't advertise SPECIAL-USE.
_DRAFT_FOLDER_FALLBACKS: list[str] = [
    "Drafts",
    "INBOX.Drafts",
    "INBOX/Drafts",
    "Entwürfe",
    "INBOX.Entwürfe",
    "[Gmail]/Drafts",
    "[Google Mail]/Drafts",
]


def find_drafts_folder(connection, override: str | None = None) -> str:
    """Resolve the drafts folder for the connected IMAP account.

    Resolution order:
      1. Explicit ``override`` argument (if given) – returned verbatim.
      2. RFC 6154 ``SPECIAL-USE`` ``\\Drafts`` flag, queried via
         ``LIST (SPECIAL-USE) "" "*"``. (Most modern servers: Dovecot,
         Cyrus, Gmail, Office 365 …)
      3. First match from the static fallback list that the server
         actually has.
      4. Final fallback: ``"INBOX.Drafts"`` (created on demand by some
         servers; raises a clear error if the actual append fails).
    """
    if override:
        return override

    try:
        typ, raw_response = connection.list('""', '"*"')
    except Exception:
        typ, raw_response = "NO", []

    available_folders: list[str] = []
    if typ == "OK" and raw_response:
        for entry in raw_response:
            if not entry:
                continue
            decoded = (
                entry.decode("utf-8", errors="replace") if isinstance(entry, bytes) else str(entry)
            )
            # `SPECIAL-USE` flags appear inside the LIST response as e.g.
            #   * LIST (\HasNoChildren \Drafts) "/" "Drafts"
            if "\\Drafts" in decoded:
                m = re.search(r'"([^"]+)"\s*$', decoded)
                if m:
                    return m.group(1)
            # Also collect plain folder names for fallback below.
            m_name = re.search(r'"([^"]+)"\s*$', decoded)
            if m_name:
                available_folders.append(m_name.group(1))

    for candidate in _DRAFT_FOLDER_FALLBACKS:
        if candidate in available_folders:
            return candidate

    return "INBOX.Drafts"


# -----------------------------------------------------------------------------
# UID-aware APPEND (RFC 4315 UIDPLUS)
# -----------------------------------------------------------------------------

_APPENDUID_RX = re.compile(rb"\bAPPENDUID\s+(\d+)\s+(\d+)", re.IGNORECASE)


@dataclass
class AppendResult:
    folder: str
    uid: int | None  # None if the server doesn't support UIDPLUS
    uidvalidity: int | None


def append_with_uid(
    connection,
    folder: str,
    message_bytes: bytes,
    flags: list[str] | None = None,
    internal_date: str | None = None,
) -> AppendResult:
    """`imaplib.IMAP4.append` wrapper that also returns the new UID.

    On UIDPLUS-capable servers the tagged OK response carries an
    ``[APPENDUID <uidvalidity> <uid>]`` response code (RFC 4315) which we
    extract here. Servers without UIDPLUS still get the message stored,
    just without a UID echo.
    """
    flag_str = "(" + " ".join(flags) + ")" if flags else None
    typ, response = connection.append(
        folder,
        flag_str,
        internal_date,
        message_bytes,
    )
    if typ != "OK":
        raise RuntimeError(f"IMAP APPEND to {folder!r} failed: {typ} {response!r}")

    uidvalidity: int | None = None
    uid: int | None = None
    for line in response or []:
        if not line:
            continue
        if isinstance(line, str):
            line = line.encode("latin-1", errors="replace")
        m = _APPENDUID_RX.search(line)
        if m:
            uidvalidity = int(m.group(1))
            uid = int(m.group(2))
            break

    return AppendResult(folder=folder, uid=uid, uidvalidity=uidvalidity)


# -----------------------------------------------------------------------------
# Public API – save / update / delete + reply / forward variants
# -----------------------------------------------------------------------------


def _ensure_folder_selected(connection, folder: str) -> None:
    """Select the folder so subsequent UID STORE/EXPUNGE work on the right one."""
    typ, _ = connection.select(folder)
    if typ != "OK":
        raise RuntimeError(f"Could not SELECT folder {folder!r}")


def _attach_message_id_and_date(message: Message, sender: str) -> None:
    """Add ``Message-ID`` and ``Date`` headers if missing."""
    if not message.get("Message-ID"):
        message["Message-ID"] = make_msgid(
            domain=(sender.split("@")[-1] if "@" in sender else None)
        )
    if not message.get("Date"):
        from email.utils import formatdate

        message["Date"] = formatdate(localtime=True)


def _attachments_from_dicts(raw: list[dict] | None) -> list[Attachment] | None:
    if not raw:
        return None
    import base64

    out: list[Attachment] = []
    for att in raw:
        out.append(
            Attachment(
                filename=att["filename"],
                content_type=att.get("content_type", "application/octet-stream"),
                data=base64.b64decode(att["data_base64"]),
            )
        )
    return out


def save_draft(
    *,
    connection,
    sender: str,
    to: list[str],
    subject: str,
    body_text: str | None = None,
    body_html: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[dict] | None = None,
    drafts_folder: str | None = None,
    flags: list[str] | None = None,
    internal_date: str | None = None,
    extra_headers: dict[str, str] | None = None,
    sender_name: str | None = None,
) -> dict[str, Any]:
    """Build a fresh MIME message and IMAP-APPEND it as a draft.

    Returns ``{"folder", "uid", "uidvalidity", "message_id"}``. ``uid`` is
    ``None`` on servers without UIDPLUS.
    """
    folder = find_drafts_folder(connection, drafts_folder)
    msg = build_message(
        sender=sender,
        to=to,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        cc=cc,
        bcc=bcc,
        attachments=_attachments_from_dicts(attachments),
        sender_name=sender_name,
    )
    if extra_headers:
        for k, v in extra_headers.items():
            if v:
                msg[k] = v
    _attach_message_id_and_date(msg, sender)

    # IMAP messages must use CRLF line endings (RFC 3501). Python's
    # compat32 generator emits bare LF, which – together with base64 – made
    # Spark's draft editor mis-segment the body. Normalise to CRLF so the
    # stored draft is byte-compatible with a Spark-composed message.
    raw = re.sub(rb"\r?\n", b"\r\n", msg.as_bytes())
    result = append_with_uid(
        connection,
        folder,
        raw,
        flags=flags or ["\\Draft"],
        internal_date=internal_date,
    )
    logger.info(
        "save_draft → folder=%s uid=%s message_id=%s size=%d",
        result.folder,
        result.uid,
        msg.get("Message-ID"),
        len(raw),
    )
    return {
        "folder": result.folder,
        "uid": result.uid,
        "uidvalidity": result.uidvalidity,
        "message_id": msg.get("Message-ID"),
    }


def delete_draft(
    *,
    connection,
    uid: int,
    folder: str | None = None,
) -> dict[str, Any]:
    """Mark a draft ``\\Deleted`` and EXPUNGE it.

    Returns ``{"deleted": True}`` on success or ``{"deleted": False,
    "reason": "draft_not_found"}`` if the UID is not in the folder
    (idempotent: a second delete is harmless).
    """
    folder = find_drafts_folder(connection, folder)
    _ensure_folder_selected(connection, folder)

    # Verify the UID exists first – makes a repeat-delete idempotent.
    typ, data = connection.uid("SEARCH", None, f"UID {int(uid)}")
    if typ != "OK" or not data or not data[0]:
        return {"deleted": False, "reason": "draft_not_found", "folder": folder, "uid": uid}

    connection.uid("STORE", str(int(uid)), "+FLAGS.SILENT", "(\\Deleted)")
    connection.expunge()
    logger.info("delete_draft → folder=%s uid=%s", folder, uid)
    return {"deleted": True, "folder": folder, "uid": uid}


def update_draft(
    *,
    connection,
    uid: int,
    sender: str,
    to: list[str],
    subject: str,
    body_text: str | None = None,
    body_html: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[dict] | None = None,
    folder: str | None = None,
    flags: list[str] | None = None,
    internal_date: str | None = None,
    sender_name: str | None = None,
) -> dict[str, Any]:
    """Replace an existing draft.

    IMAP has no in-place edit, so this is APPEND new + STORE \\Deleted +
    EXPUNGE the old. Returns the *new* UID.
    """
    folder = find_drafts_folder(connection, folder)

    new_result = save_draft(
        connection=connection,
        sender=sender,
        to=to,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        cc=cc,
        bcc=bcc,
        attachments=attachments,
        drafts_folder=folder,
        flags=flags,
        internal_date=internal_date,
        sender_name=sender_name,
    )
    delete_draft(connection=connection, uid=uid, folder=folder)
    new_result["replaced_uid"] = uid
    return new_result


# -----------------------------------------------------------------------------
# Reply / forward drafts (composition lives in ..compose, shared with send)
# -----------------------------------------------------------------------------

# Kept as module-level names for callers/tests that import them from here.
_decode_subject = compose.decode_mime_header
_strip_re_prefix = compose.strip_reply_prefixes
_strip_fwd_prefix = compose.strip_forward_prefixes
_references_for_reply = compose.references_for_reply
_fetch_original_raw = compose.fetch_original


def _save_composed(
    connection,
    sender: str,
    composed: compose.Composed,
    *,
    sender_name: str | None,
    drafts_folder: str | None,
    flags: list[str] | None,
) -> dict[str, Any]:
    return save_draft(
        connection=connection,
        sender=sender,
        sender_name=sender_name,
        to=composed.to,
        cc=composed.cc,
        bcc=composed.bcc,
        subject=composed.subject,
        body_text=composed.body_text,
        body_html=composed.body_html,
        attachments=composed.attachments,
        drafts_folder=drafts_folder,
        flags=flags,
        extra_headers=composed.headers,
    )


def save_reply_draft(
    *,
    connection,
    sender: str,
    original_uid: int,
    original_folder: str = "INBOX",
    body_text: str | None = None,
    body_html: str | None = None,
    reply_all: bool = False,
    include_quote: bool = True,
    signature: bool = True,
    attachments: list[dict] | None = None,
    drafts_folder: str | None = None,
    flags: list[str] | None = None,
    sender_name: str | None = None,
    cfg: compose.ComposeConfig | None = None,
) -> dict[str, Any]:
    """Save a properly-threaded reply as a draft.

    The quote goes into both the text and the HTML part (Spark shows the
    HTML part), followed by the configured signature – see ``compose``.
    """
    original = compose.fetch_original(connection, original_folder, original_uid)
    composed = compose.compose_reply(
        original,
        own_address=sender,
        body_text=body_text,
        body_html=body_html,
        reply_all=reply_all,
        include_quote=include_quote,
        signature=signature,
        attachments=attachments,
        cfg=cfg,
    )
    return _save_composed(
        connection,
        sender,
        composed,
        sender_name=sender_name,
        drafts_folder=drafts_folder,
        flags=flags,
    )


def save_forward_draft(
    *,
    connection,
    sender: str,
    original_uid: int,
    original_folder: str,
    to: list[str],
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    body_text: str | None = None,
    body_html: str | None = None,
    forward_attachments: bool = True,
    additional_attachments: list[dict] | None = None,
    signature: bool = True,
    drafts_folder: str | None = None,
    flags: list[str] | None = None,
    sender_name: str | None = None,
    cfg: compose.ComposeConfig | None = None,
) -> dict[str, Any]:
    """Save a forwarded copy of an existing email as a draft."""
    original = compose.fetch_original(connection, original_folder, original_uid)
    composed = compose.compose_forward(
        original,
        to=to,
        cc=cc,
        bcc=bcc,
        body_text=body_text,
        body_html=body_html,
        forward_attachments=forward_attachments,
        attachments=additional_attachments,
        signature=signature,
        cfg=cfg,
    )
    return _save_composed(
        connection,
        sender,
        composed,
        sender_name=sender_name,
        drafts_folder=drafts_folder,
        flags=flags,
    )


# -----------------------------------------------------------------------------
# send_draft helpers: load a stored draft, file the sent copy
# -----------------------------------------------------------------------------

_SENT_FOLDER_FALLBACKS: list[str] = [
    "Sent",
    "INBOX.Sent",
    "INBOX/Sent",
    "Gesendet",
    "INBOX.Gesendet",
    "Sent Items",
    "Gesendete Objekte",
    "[Gmail]/Sent Mail",
]


def find_sent_folder(connection) -> str:
    """Resolve the Sent folder via SPECIAL-USE ``\\Sent`` or common names."""
    try:
        typ, raw_response = connection.list('""', '"*"')
    except Exception:
        typ, raw_response = "NO", []
    available: list[str] = []
    if typ == "OK" and raw_response:
        for entry in raw_response:
            if not entry:
                continue
            decoded = (
                entry.decode("utf-8", errors="replace") if isinstance(entry, bytes) else str(entry)
            )
            m = re.search(r'"([^"]+)"\s*$', decoded)
            if not m:
                continue
            if "\\Sent" in decoded:
                return m.group(1)
            available.append(m.group(1))
    for candidate in _SENT_FOLDER_FALLBACKS:
        if candidate in available:
            return candidate
    return "INBOX.Sent"


def load_draft(connection, uid: int, folder: str | None = None) -> tuple[str, Message]:
    """Fetch a stored draft by UID. Returns ``(folder, message)``."""
    folder = find_drafts_folder(connection, folder)
    return folder, compose.fetch_original(connection, folder, uid)


def append_to_sent(connection, raw: bytes) -> str:
    """File a copy of a sent message in the Sent folder (flag ``\\Seen``)."""
    folder = find_sent_folder(connection)
    raw = re.sub(rb"\r?\n", b"\r\n", raw)
    append_with_uid(connection, folder, raw, flags=["\\Seen"])
    return folder


__all__ = [
    "AppendResult",
    "append_with_uid",
    "find_drafts_folder",
    "save_draft",
    "update_draft",
    "delete_draft",
    "save_reply_draft",
    "save_forward_draft",
    "find_sent_folder",
    "load_draft",
    "append_to_sent",
]
