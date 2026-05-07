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
from email import message_from_bytes
from email.message import Message
from email.utils import make_msgid
from typing import Any

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
    )
    if extra_headers:
        for k, v in extra_headers.items():
            if v:
                msg[k] = v
    _attach_message_id_and_date(msg, sender)

    raw = msg.as_bytes()
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
    )
    delete_draft(connection=connection, uid=uid, folder=folder)
    new_result["replaced_uid"] = uid
    return new_result


# -----------------------------------------------------------------------------
# Reply / forward draft helpers
# -----------------------------------------------------------------------------


def _strip_re_prefix(subject: str) -> str:
    """Collapse leading ``Re: Re: …`` to a single ``Re:`` for dedup."""
    return re.sub(r"^(?:re:\s*)+", "", subject, flags=re.IGNORECASE).strip()


def _strip_fwd_prefix(subject: str) -> str:
    return re.sub(r"^(?:fwd?:\s*)+", "", subject, flags=re.IGNORECASE).strip()


def _fetch_original_raw(connection, folder: str, uid: int) -> Message:
    _ensure_folder_selected(connection, folder)
    typ, data = connection.uid("FETCH", str(int(uid)), "(RFC822)")
    if typ != "OK" or not data:
        raise RuntimeError(f"Could not fetch UID {uid} from {folder!r}: {typ}")
    raw_bytes: bytes | None = None
    for entry in data:
        if isinstance(entry, tuple) and len(entry) >= 2:
            raw_bytes = entry[1]
            break
    if raw_bytes is None:
        raise RuntimeError(f"FETCH UID {uid} returned no RFC822 body")
    return message_from_bytes(raw_bytes)


def _references_for_reply(original: Message) -> str:
    """Build the RFC 5322 ``References`` header for a reply.

    Standard rule: previous ``References`` + previous ``Message-ID``,
    falling back to the previous ``In-Reply-To`` if no ``References``.
    """
    parts: list[str] = []
    prev_refs = original.get("References", "")
    if prev_refs:
        parts.extend(prev_refs.split())
    elif original.get("In-Reply-To"):
        parts.append(original["In-Reply-To"].strip())
    msg_id = original.get("Message-ID")
    if msg_id and msg_id not in parts:
        parts.append(msg_id.strip())
    return " ".join(parts)


def _extract_text_body(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                try:
                    return payload.decode(charset, errors="replace")
                except LookupError:
                    return payload.decode("utf-8", errors="replace")
        # fallback: html stripped of tags
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                try:
                    html = payload.decode(charset, errors="replace")
                except LookupError:
                    html = payload.decode("utf-8", errors="replace")
                return re.sub(r"<[^>]+>", "", html)
        return ""
    payload = msg.get_payload(decode=True) or b""
    charset = msg.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _quote_block(orig: Message) -> str:
    body = _extract_text_body(orig).rstrip()
    if not body:
        return ""
    quoted = "\n".join("> " + line for line in body.splitlines())
    header = f"Am {orig.get('Date', '')} schrieb {orig.get('From', '')}:\n"
    return header + quoted


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
    attachments: list[dict] | None = None,
    drafts_folder: str | None = None,
    flags: list[str] | None = None,
) -> dict[str, Any]:
    """Save a properly-threaded reply as a draft."""
    if not body_text and not body_html:
        raise ValueError("body_text or body_html is required")

    original = _fetch_original_raw(connection, original_folder, original_uid)
    orig_subject = original.get("Subject", "")
    subject = "Re: " + _strip_re_prefix(orig_subject) if orig_subject else "Re: (no subject)"

    # Recipients: To = original Reply-To/From, Cc = original To+Cc minus our own address (if reply_all).
    reply_to_field = original.get("Reply-To") or original.get("From") or ""
    to = [a.strip() for a in re.split(r"[,;]", reply_to_field) if a.strip()] or [reply_to_field]

    cc_list: list[str] | None = None
    if reply_all:
        from email.utils import getaddresses

        all_orig_recipients = getaddresses(original.get_all("To", []) + original.get_all("Cc", []))
        # Filter out our own address and the primary "to" addresses.
        own_lower = sender.lower()
        to_lower = {addr.split("<")[-1].strip(">").strip().lower() for addr in to}
        cc_addrs: list[str] = []
        for _name, addr in all_orig_recipients:
            if not addr:
                continue
            if addr.lower() == own_lower or addr.lower() in to_lower:
                continue
            cc_addrs.append(addr)
        cc_list = cc_addrs or None

    composed_text = body_text or ""
    if include_quote:
        quote = _quote_block(original)
        if quote:
            composed_text = (composed_text + "\n\n" + quote).strip()

    extra: dict[str, str] = {}
    msg_id = original.get("Message-ID")
    if msg_id:
        extra["In-Reply-To"] = msg_id
    refs = _references_for_reply(original)
    if refs:
        extra["References"] = refs

    return save_draft(
        connection=connection,
        sender=sender,
        to=to,
        subject=subject,
        body_text=composed_text or None,
        body_html=body_html,
        cc=cc_list,
        attachments=attachments,
        drafts_folder=drafts_folder,
        flags=flags,
        extra_headers=extra,
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
    drafts_folder: str | None = None,
    flags: list[str] | None = None,
) -> dict[str, Any]:
    """Save a forwarded copy of an existing email as a draft."""
    original = _fetch_original_raw(connection, original_folder, original_uid)

    orig_subject = original.get("Subject", "")
    subject = "Fwd: " + _strip_fwd_prefix(orig_subject) if orig_subject else "Fwd: (no subject)"

    # Build forwarded text – preface + RFC 5322 quoting of the original.
    intro = body_text or ""
    forwarded_block = (
        "\n\n---------- Weitergeleitete Nachricht ----------\n"
        f"Von: {original.get('From', '')}\n"
        f"Datum: {original.get('Date', '')}\n"
        f"Betreff: {orig_subject}\n"
        f"An: {original.get('To', '')}\n"
    )
    cc_orig = original.get("Cc")
    if cc_orig:
        forwarded_block += f"Cc: {cc_orig}\n"
    forwarded_block += "\n" + _extract_text_body(original)
    composed_text = (intro + forwarded_block).strip()

    # Collect attachments from the original (if requested) + caller-supplied extras.
    forward_atts: list[dict] = []
    if forward_attachments and original.is_multipart():
        import base64

        for part in original.walk():
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" not in disp and not part.get_filename():
                continue
            data = part.get_payload(decode=True)
            if not data:
                continue
            forward_atts.append(
                {
                    "filename": part.get_filename() or "attachment.bin",
                    "content_type": part.get_content_type(),
                    "data_base64": base64.b64encode(data).decode("ascii"),
                }
            )
    if additional_attachments:
        forward_atts.extend(additional_attachments)

    return save_draft(
        connection=connection,
        sender=sender,
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject,
        body_text=composed_text or None,
        body_html=body_html,
        attachments=forward_atts or None,
        drafts_folder=drafts_folder,
        flags=flags,
    )


__all__ = [
    "AppendResult",
    "append_with_uid",
    "find_drafts_folder",
    "save_draft",
    "update_draft",
    "delete_draft",
    "save_reply_draft",
    "save_forward_draft",
]
