"""MCP Tools definitions and handlers for IMAP operations."""

import base64
import os

from mcp.types import TextContent, Tool

from ..client import get_imap_client
from ..config import TransferConfig
from ..db import get_email_store
from ..smtp import Attachment, get_smtp_client
from ..smtp.operations import send_email, send_forward, send_reply

_DB_ENABLED = os.getenv("EMAIL_DB_ENABLED", "false").lower() == "true"
_transfer_cfg = TransferConfig.from_env()
_ATTACHMENT_MAX_BYTES = _transfer_cfg.attachment_max_size_kb * 1024

# Shared schema fragment for the ``attach_from`` parameter exposed by
# send_email / save_draft / update_draft / save_reply_draft / save_forward_draft.
# It lets callers reference documents stored in external systems (currently
# Paperless-ngx; HERO is stubbed for future support). The server fetches the
# binary directly from the source and attaches it as a normal MIME part – no
# bytes ever traverse Claude's context window, and the recipient does not
# need access to the source system.
_ATTACH_FROM_SCHEMA: dict = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "enum": ["paperless"],
                "description": (
                    "Source system holding the document. Currently only "
                    "'paperless' is wired up; 'hero' is reserved for future use."
                ),
            },
            "id": {
                "type": "integer",
                "description": "Document primary key in the source system.",
            },
            "filename": {
                "type": "string",
                "description": (
                    "Optional filename override. Defaults to the filename "
                    "stored in the source system (e.g. Paperless's "
                    "original_file_name or Content-Disposition)."
                ),
            },
            "as_original": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Paperless only: fetch the originally uploaded file "
                    "instead of Paperless's post-OCR archive PDF (default)."
                ),
            },
        },
        "required": ["source", "id"],
    },
    "description": (
        "References to documents in external systems (Paperless-ngx). The "
        "server downloads each one directly and attaches it as a normal "
        "MIME attachment – no binary data passes through the LLM context, "
        "and recipients do not need access to the source system."
    ),
}


def _db_search(store, criteria: str, folder: str, limit: int) -> list[dict] | None:
    """Translate simple IMAP criteria string to a DB query.

    Returns a list of result dicts, or None if the criteria can't be
    served from the DB (caller should fall back to live IMAP).
    """
    import re as _re

    c = criteria.strip().upper()

    # --- flag / status criteria ---
    if c == "ALL":
        return store.list_emails(folder=folder, limit=limit)
    if c == "UNSEEN":
        return store.list_emails(folder=folder, limit=limit, unread_only=True)
    if c == "SEEN":
        rows = store.list_emails(folder=folder, limit=limit)
        return [r for r in rows if r.get("is_read")]
    if c == "FLAGGED":
        rows = store.list_emails(folder=folder, limit=limit)
        return [r for r in rows if r.get("is_flagged")]
    if c == "UNFLAGGED":
        rows = store.list_emails(folder=folder, limit=limit)
        return [r for r in rows if not r.get("is_flagged")]

    # --- field searches: FROM x / TO x / SUBJECT x ---
    m = _re.match(r"^(FROM|TO|SUBJECT)\s+(.+)$", criteria.strip(), _re.IGNORECASE)
    if m:
        field_map = {"FROM": "from_addr", "TO": "to_addr", "SUBJECT": "subject"}
        fts_field = field_map[m.group(1).upper()]
        value = m.group(2).strip().strip('"')
        # Use FTS5 field filter for precision
        fts_query = f'{fts_field}:"{value}"'
        results = store.search_fts(
            fts_query, folder=folder if folder != "INBOX" else None, limit=limit
        )
        if folder == "INBOX":
            results = [r for r in results if r.get("folder") == "INBOX"]
        return results

    # Criteria we don't support (DATE ranges, UID ranges, complex AND/OR, etc.)
    # → return None so caller falls back to IMAP
    return None


def get_transfer_tools() -> list[Tool]:
    """Get transfer tool definitions (only when external services are configured)."""
    tools = []
    if _transfer_cfg.paperless_enabled:
        tools.append(
            Tool(
                name="transfer_to_paperless",
                description=(
                    "Fetch an email attachment directly from IMAP and upload it to "
                    "Paperless-ngx – no binary data passes through Claude's context. "
                    "Returns the Paperless task ID."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "folder": {
                            "type": "string",
                            "description": "Folder containing the email (default: INBOX)",
                            "default": "INBOX",
                        },
                        "uid": {
                            "type": "string",
                            "description": "Unique ID (UID) of the email",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Attachment filename. Omit to use the first attachment.",
                        },
                        "title": {
                            "type": "string",
                            "description": "Document title in Paperless (default: filename)",
                        },
                        "correspondent_id": {
                            "type": "integer",
                            "description": "Paperless correspondent ID (optional)",
                        },
                        "document_type_id": {
                            "type": "integer",
                            "description": "Paperless document type ID (optional)",
                        },
                        "tag_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "List of Paperless tag IDs (optional)",
                        },
                    },
                    "required": ["uid"],
                },
            )
        )
    if _transfer_cfg.hero_enabled:
        tools.append(
            Tool(
                name="transfer_to_hero",
                description=(
                    "Fetch an email attachment from IMAP and upload it to a HERO "
                    "project_match's document storage – binary data is streamed "
                    "server-to-server, never through Claude's context. "
                    "Internally runs HERO's two-step upload: "
                    "(1) POST to /api/external/v1/file-uploads → uuid, "
                    "(2) GraphQL upload_document mutation with file_upload_uuid + "
                    "target=project_match. "
                    "Use this for attachments of any size; the 50 KB limit on "
                    "get_attachment(include_data=true) does NOT apply here."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "folder": {
                            "type": "string",
                            "description": "Folder containing the email (default: INBOX)",
                            "default": "INBOX",
                        },
                        "uid": {
                            "type": "string",
                            "description": "Unique ID (UID) of the email",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Attachment filename. Omit to use the first attachment.",
                        },
                        "project_id": {
                            "type": "string",
                            "description": (
                                "HERO project_match.id (numeric, e.g. '10295003'). "
                                "Use the hero-mcp tool hero_get_projects to look it up."
                            ),
                        },
                    },
                    "required": ["uid", "project_id"],
                },
            )
        )
    return tools


def get_imap_tools() -> list[Tool]:
    """Get all IMAP-related tool definitions."""
    return [
        Tool(
            name="list_folders",
            description="List all email folders",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="create_folder",
            description="Create a new email folder",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder_name": {
                        "type": "string",
                        "description": "Name of the folder to create",
                    },
                },
                "required": ["folder_name"],
            },
        ),
        Tool(
            name="delete_folder",
            description="Delete an email folder",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder_name": {
                        "type": "string",
                        "description": "Name of the folder to delete",
                    },
                },
                "required": ["folder_name"],
            },
        ),
        Tool(
            name="rename_folder",
            description="Rename an email folder",
            inputSchema={
                "type": "object",
                "properties": {
                    "old_name": {
                        "type": "string",
                        "description": "Current folder name",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "New folder name",
                    },
                },
                "required": ["old_name", "new_name"],
            },
        ),
        Tool(
            name="search_emails",
            description="Search emails with criteria",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Folder to search in (default: INBOX)",
                        "default": "INBOX",
                    },
                    "criteria": {
                        "type": "string",
                        "description": "IMAP search criteria (e.g., 'ALL', 'UNSEEN', 'FROM sender@example.com', 'SUBJECT urgent')",
                        "default": "ALL",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 10)",
                        "default": 10,
                    },
                },
            },
        ),
        Tool(
            name="get_email",
            description="Get detailed email information",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Folder containing the email (default: INBOX)",
                        "default": "INBOX",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message ID (sequence number)",
                    },
                    "uid": {
                        "type": "string",
                        "description": "Unique ID of the message",
                    },
                    "include_body": {
                        "type": "boolean",
                        "description": "Include email body (default: true)",
                        "default": True,
                    },
                },
            },
        ),
        Tool(
            name="mark_read",
            description="Mark email as read (seen)",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Folder containing the email (default: INBOX)",
                        "default": "INBOX",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message ID (sequence number)",
                    },
                    "uid": {
                        "type": "string",
                        "description": "Unique ID of the message",
                    },
                },
            },
        ),
        Tool(
            name="mark_unread",
            description="Mark email as unread (remove seen flag)",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Folder containing the email (default: INBOX)",
                        "default": "INBOX",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message ID (sequence number)",
                    },
                    "uid": {
                        "type": "string",
                        "description": "Unique ID of the message",
                    },
                },
            },
        ),
        Tool(
            name="mark_flagged",
            description="Mark email as flagged (starred)",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Folder containing the email (default: INBOX)",
                        "default": "INBOX",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message ID (sequence number)",
                    },
                    "uid": {
                        "type": "string",
                        "description": "Unique ID of the message",
                    },
                },
            },
        ),
        Tool(
            name="unmark_flagged",
            description="Unmark email as flagged (remove starred)",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Folder containing the email (default: INBOX)",
                        "default": "INBOX",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message ID (sequence number)",
                    },
                    "uid": {
                        "type": "string",
                        "description": "Unique ID of the message",
                    },
                },
            },
        ),
        Tool(
            name="move_email",
            description="Move email to another folder",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_folder": {
                        "type": "string",
                        "description": "Source folder name",
                    },
                    "target_folder": {
                        "type": "string",
                        "description": "Target folder name",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message ID (sequence number)",
                    },
                    "uid": {
                        "type": "string",
                        "description": "Unique ID of the message",
                    },
                },
                "required": ["source_folder", "target_folder"],
            },
        ),
        Tool(
            name="copy_email",
            description="Copy email to another folder",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_folder": {
                        "type": "string",
                        "description": "Source folder name",
                    },
                    "target_folder": {
                        "type": "string",
                        "description": "Target folder name",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message ID (sequence number)",
                    },
                    "uid": {
                        "type": "string",
                        "description": "Unique ID of the message",
                    },
                },
                "required": ["source_folder", "target_folder"],
            },
        ),
        Tool(
            name="delete_email",
            description="Delete email (mark as deleted and expunge)",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Folder containing the email (default: INBOX)",
                        "default": "INBOX",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message ID (sequence number)",
                    },
                    "uid": {
                        "type": "string",
                        "description": "Unique ID of the message",
                    },
                },
            },
        ),
        Tool(
            name="get_current_date",
            description="Get current date and time",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_attachment",
            description=(
                "Fetch attachment metadata (filename, content_type, size). "
                "By default returns metadata only – no binary data – to avoid "
                "filling the context window. Set include_data=true only for small "
                f"files (≤ {_transfer_cfg.attachment_max_size_kb} KB). "
                "For larger files use transfer_to_paperless or transfer_to_hero."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Folder containing the email (default: INBOX)",
                        "default": "INBOX",
                    },
                    "uid": {
                        "type": "string",
                        "description": "Unique ID (UID) of the email",
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "Exact filename of the attachment. "
                            "If omitted, the first attachment is returned."
                        ),
                    },
                    "include_data": {
                        "type": "boolean",
                        "description": (
                            f"Return base64-encoded content (only for files ≤ "
                            f"{_transfer_cfg.attachment_max_size_kb} KB). "
                            "Default: false."
                        ),
                        "default": False,
                    },
                },
                "required": ["uid"],
            },
        ),
    ]


def get_smtp_tools() -> list[Tool]:
    """Get all SMTP-related tool definitions."""
    return [
        Tool(
            name="send_email",
            description=(
                "Send an email with optional HTML body and attachments. "
                "Use `attach_from` to attach documents stored in Paperless-ngx "
                "by ID – the server fetches the binary directly so no bytes "
                "pass through the LLM context."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of recipient email addresses",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject",
                    },
                    "body_text": {
                        "type": "string",
                        "description": "Plain text body",
                    },
                    "body_html": {
                        "type": "string",
                        "description": "HTML body",
                    },
                    "cc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "CC recipients",
                    },
                    "bcc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "BCC recipients",
                    },
                    "attachments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string"},
                                "content_type": {"type": "string"},
                                "data_base64": {"type": "string"},
                            },
                        },
                        "description": "Attachments (base64 encoded)",
                    },
                    "attach_from": _ATTACH_FROM_SCHEMA,
                },
                "required": ["to", "subject"],
            },
        ),
        Tool(
            name="send_reply",
            description="Reply to an email",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Recipient email addresses",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Reply subject (usually with Re:)",
                    },
                    "body_text": {
                        "type": "string",
                        "description": "Reply body text",
                    },
                    "body_html": {
                        "type": "string",
                        "description": "Reply body HTML",
                    },
                    "reply_to_message_id": {
                        "type": "string",
                        "description": "Original message ID to reply to",
                    },
                    "quote_original": {
                        "type": "boolean",
                        "description": "Quote original message (default: true)",
                        "default": True,
                    },
                },
                "required": ["to", "subject", "reply_to_message_id"],
            },
        ),
        Tool(
            name="send_forward",
            description="Forward an email to another recipient",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Forward recipient addresses",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Forward subject (usually with Fwd:)",
                    },
                    "original_folder": {
                        "type": "string",
                        "description": "Folder of original email (optional, if fetching original)",
                    },
                    "original_message_id": {
                        "type": "string",
                        "description": "Message ID of email to forward (optional, if fetching original)",
                    },
                    "body_text": {
                        "type": "string",
                        "description": "Additional comment for forward",
                    },
                    "body_html": {
                        "type": "string",
                        "description": "Additional HTML comment for forward",
                    },
                },
                "required": ["to", "subject"],
            },
        ),
        # ------------------------------------------------------------------
        # Draft management (IMAP APPEND, no SMTP).
        # Mirror of send_email / send_reply / send_forward but writing to
        # the IMAP Drafts folder so the user can review / edit / send the
        # message manually before it leaves the inbox.
        # ------------------------------------------------------------------
        Tool(
            name="save_draft",
            description=(
                "Save an email as a DRAFT in the IMAP Drafts folder (no send). "
                "Mirror of send_email – returns the new draft's UID + folder. "
                "Drafts folder is auto-detected via SPECIAL-USE; override with "
                "drafts_folder if your server doesn't advertise it."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of recipient email addresses",
                    },
                    "subject": {"type": "string", "description": "Email subject"},
                    "body_text": {"type": "string", "description": "Plain text body"},
                    "body_html": {"type": "string", "description": "HTML body"},
                    "cc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "CC recipients",
                    },
                    "bcc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "BCC recipients",
                    },
                    "attachments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string"},
                                "content_type": {"type": "string"},
                                "data_base64": {"type": "string"},
                            },
                        },
                        "description": "Attachments (base64 encoded)",
                    },
                    "attach_from": _ATTACH_FROM_SCHEMA,
                    "drafts_folder": {
                        "type": "string",
                        "description": (
                            "Optional override for the drafts folder name. "
                            "Default: auto-detect via IMAP SPECIAL-USE \\Drafts; "
                            "fallback INBOX.Drafts."
                        ),
                    },
                },
                "required": ["to", "subject"],
            },
        ),
        Tool(
            name="update_draft",
            description=(
                "Replace an existing draft with new content. Internally APPENDs "
                "a new draft and EXPUNGEs the old UID, so the returned UID is "
                "different from the input."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {
                        "type": "integer",
                        "description": "UID of the draft to replace",
                    },
                    "to": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "subject": {"type": "string"},
                    "body_text": {"type": "string"},
                    "body_html": {"type": "string"},
                    "cc": {"type": "array", "items": {"type": "string"}},
                    "bcc": {"type": "array", "items": {"type": "string"}},
                    "attachments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string"},
                                "content_type": {"type": "string"},
                                "data_base64": {"type": "string"},
                            },
                        },
                    },
                    "attach_from": _ATTACH_FROM_SCHEMA,
                    "drafts_folder": {"type": "string"},
                },
                "required": ["uid", "to", "subject"],
            },
        ),
        Tool(
            name="delete_draft",
            description=(
                "Permanently delete a draft (STORE \\Deleted + EXPUNGE). "
                "Idempotent: returns deleted=false / reason=draft_not_found if "
                "the UID is no longer in the folder."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {"type": "integer"},
                    "drafts_folder": {
                        "type": "string",
                        "description": "Folder containing the draft (default: auto-detected drafts folder)",
                    },
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="save_reply_draft",
            description=(
                "Save a properly-threaded reply as a DRAFT (no send). "
                "Sets In-Reply-To + References from the original message and "
                "prepends 'Re:' to the subject (deduplicating 'Re: Re:'). "
                "If reply_all=true, copies the original To+Cc to Cc (minus "
                "the user's own address)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "original_uid": {
                        "type": "integer",
                        "description": "UID of the email being replied to",
                    },
                    "original_folder": {
                        "type": "string",
                        "description": "Folder containing the original (default: INBOX)",
                        "default": "INBOX",
                    },
                    "body_text": {"type": "string"},
                    "body_html": {"type": "string"},
                    "reply_all": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, includes original To+Cc as Cc (minus self)",
                    },
                    "include_quote": {
                        "type": "boolean",
                        "default": True,
                        "description": "If true, append a quoted copy of the original body",
                    },
                    "attachments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string"},
                                "content_type": {"type": "string"},
                                "data_base64": {"type": "string"},
                            },
                        },
                    },
                    "attach_from": _ATTACH_FROM_SCHEMA,
                    "drafts_folder": {"type": "string"},
                },
                "required": ["original_uid"],
            },
        ),
        Tool(
            name="save_forward_draft",
            description=(
                "Save a forwarded copy as a DRAFT (no send). Subject is "
                "prefixed with 'Fwd:' and the original headers + body are "
                "embedded as a quoted block. By default the original "
                "attachments are carried over – set forward_attachments=false "
                "to drop them."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "original_uid": {"type": "integer"},
                    "original_folder": {
                        "type": "string",
                        "description": "Folder containing the original (default: INBOX)",
                        "default": "INBOX",
                    },
                    "to": {"type": "array", "items": {"type": "string"}},
                    "cc": {"type": "array", "items": {"type": "string"}},
                    "bcc": {"type": "array", "items": {"type": "string"}},
                    "body_text": {
                        "type": "string",
                        "description": "Optional preface text before the forwarded block",
                    },
                    "body_html": {"type": "string"},
                    "forward_attachments": {
                        "type": "boolean",
                        "default": True,
                        "description": "Carry over the original attachments (default true)",
                    },
                    "attach_from": _ATTACH_FROM_SCHEMA,
                    "additional_attachments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string"},
                                "content_type": {"type": "string"},
                                "data_base64": {"type": "string"},
                            },
                        },
                    },
                    "drafts_folder": {"type": "string"},
                },
                "required": ["original_uid", "to"],
            },
        ),
    ]


def get_db_tools() -> list[Tool]:
    """Get DB-backed tool definitions (only exposed when EMAIL_DB_ENABLED=true)."""
    return [
        Tool(
            name="db_search_emails",
            description=(
                "Full-text search across all locally cached emails (subject, sender, "
                "recipient, body). Much faster than IMAP search and works across all "
                "folders simultaneously. Requires EMAIL_DB_ENABLED=true."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "FTS5 search query. Supports: plain words, "
                            '"exact phrase", field:value (subject:, from_addr:, body_text:), '
                            "AND / OR / NOT operators."
                        ),
                    },
                    "folder": {
                        "type": "string",
                        "description": "Restrict search to a specific folder (optional)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 20)",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="db_list_emails",
            description=(
                "List emails from the local cache, newest first. "
                "Faster than search_emails for browsing. "
                "Requires EMAIL_DB_ENABLED=true."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Folder to list (optional – all folders if omitted)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of emails to return (default: 50)",
                        "default": 50,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Pagination offset (default: 0)",
                        "default": 0,
                    },
                    "unread_only": {
                        "type": "boolean",
                        "description": "Only return unread emails (default: false)",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="db_sync_status",
            description=(
                "Show the status of the local email cache: total email count, "
                "per-folder breakdown, and last sync timestamps. "
                "Requires EMAIL_DB_ENABLED=true."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


def get_all_tools() -> list[Tool]:
    """Get all tool definitions."""
    tools = get_imap_tools() + get_smtp_tools()
    if _DB_ENABLED:
        tools += get_db_tools()
    tools += get_transfer_tools()
    return tools


_REQUIRES_MSG_OR_UID = {
    "get_email",
    "mark_read",
    "mark_unread",
    "mark_flagged",
    "unmark_flagged",
    "move_email",
    "copy_email",
    "delete_email",
}


def _require_message_id_or_uid(name: str, arguments: dict) -> None:
    """Validate that either ``message_id`` or ``uid`` was supplied.

    The Anthropic Tools API rejects ``anyOf`` at the top level of an
    ``input_schema`` (see error `tools.<n>.custom.input_schema: input_schema
    does not support oneOf, allOf, or anyOf at the top level`), so the
    either-or constraint that used to live in the JSON Schema is now
    enforced here at call time.
    """
    if name not in _REQUIRES_MSG_OR_UID:
        return
    if not arguments.get("message_id") and not arguments.get("uid"):
        raise ValueError(
            f"{name}: either 'message_id' (sequence number) or 'uid' (unique id) must be provided"
        )


async def handle_imap_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle IMAP tool calls."""
    _require_message_id_or_uid(name, arguments)
    client = get_imap_client()

    if name == "list_folders":
        result = client.list_folders()
        return [TextContent(type="text", text=str(result))]

    elif name == "create_folder":
        result = client.create_folder(arguments["folder_name"])
        return [TextContent(type="text", text=str(result))]

    elif name == "delete_folder":
        result = client.delete_folder(arguments["folder_name"])
        return [TextContent(type="text", text=str(result))]

    elif name == "rename_folder":
        result = client.rename_folder(arguments["old_name"], arguments["new_name"])
        return [TextContent(type="text", text=str(result))]

    elif name == "search_emails":
        folder = arguments.get("folder", "INBOX")
        criteria = arguments.get("criteria", "ALL")
        limit = arguments.get("limit", 10)

        # DB-first: when cache is enabled, translate simple IMAP criteria to DB queries.
        # Falls back to live IMAP for criteria we can't translate.
        if _DB_ENABLED:
            store = get_email_store()
            db_result = _db_search(store, criteria, folder, limit) if store else None
            if db_result is not None:
                return [TextContent(type="text", text=str(db_result))]
            # Unsupported criteria – fall through to IMAP below

        result = client.search_emails(folder=folder, criteria=criteria, limit=limit)
        return [TextContent(type="text", text=str(result))]

    elif name == "get_email":
        result = client.get_email(
            folder=arguments.get("folder", "INBOX"),
            message_id=arguments.get("message_id"),
            uid=arguments.get("uid"),
            include_body=arguments.get("include_body", True),
        )
        return [TextContent(type="text", text=str(result))]

    elif name == "mark_read":
        result = client.mark_read(
            folder=arguments.get("folder", "INBOX"),
            message_id=arguments.get("message_id"),
            uid=arguments.get("uid"),
        )
        return [TextContent(type="text", text=str(result))]

    elif name == "mark_unread":
        result = client.mark_unread(
            folder=arguments.get("folder", "INBOX"),
            message_id=arguments.get("message_id"),
            uid=arguments.get("uid"),
        )
        return [TextContent(type="text", text=str(result))]

    elif name == "mark_flagged":
        result = client.mark_flagged(
            folder=arguments.get("folder", "INBOX"),
            message_id=arguments.get("message_id"),
            uid=arguments.get("uid"),
        )
        return [TextContent(type="text", text=str(result))]

    elif name == "unmark_flagged":
        result = client.unmark_flagged(
            folder=arguments.get("folder", "INBOX"),
            message_id=arguments.get("message_id"),
            uid=arguments.get("uid"),
        )
        return [TextContent(type="text", text=str(result))]

    elif name == "move_email":
        result = client.move_email(
            source_folder=arguments["source_folder"],
            target_folder=arguments["target_folder"],
            message_id=arguments.get("message_id"),
            uid=arguments.get("uid"),
        )
        return [TextContent(type="text", text=str(result))]

    elif name == "copy_email":
        result = client.copy_email(
            source_folder=arguments["source_folder"],
            target_folder=arguments["target_folder"],
            message_id=arguments.get("message_id"),
            uid=arguments.get("uid"),
        )
        return [TextContent(type="text", text=str(result))]

    elif name == "delete_email":
        result = client.delete_email(
            folder=arguments.get("folder", "INBOX"),
            message_id=arguments.get("message_id"),
            uid=arguments.get("uid"),
        )
        return [TextContent(type="text", text=str(result))]

    elif name == "get_current_date":
        result = client.get_current_date()
        return [TextContent(type="text", text=str(result))]

    elif name == "get_attachment":
        folder = arguments.get("folder", "INBOX")
        uid = arguments.get("uid")
        filename = arguments.get("filename")
        include_data = arguments.get("include_data", False)

        # DB-first: serve from local cache when available
        if _DB_ENABLED:
            store = get_email_store()
            if store and uid:
                try:
                    db_result = store.get_attachment_by_uid(
                        folder=folder,
                        uid=int(uid),
                        filename=filename,
                        include_data=include_data,
                        max_size_bytes=_ATTACHMENT_MAX_BYTES,
                    )
                    if db_result is not None:
                        return [TextContent(type="text", text=str(db_result))]
                except Exception:
                    pass  # Fall back to live IMAP

        # Live IMAP fallback
        result = client.get_attachment(
            folder=folder,
            uid=uid,
            filename=filename,
            include_data=include_data,
            max_size_bytes=_ATTACHMENT_MAX_BYTES,
        )
        return [TextContent(type="text", text=str(result))]

    elif name == "transfer_to_paperless":
        from ..transfer import upload_to_paperless

        folder = arguments.get("folder", "INBOX")
        uid = arguments.get("uid")
        filename = arguments.get("filename")

        # DB-first for bytes
        raw_data: bytes | None = None
        actual_filename = filename or "attachment"
        actual_content_type = "application/octet-stream"

        if _DB_ENABLED:
            store = get_email_store()
            if store and uid:
                try:
                    db_bytes = store.get_attachment_bytes_by_uid(
                        folder=folder, uid=int(uid), filename=filename
                    )
                    if db_bytes:
                        raw_data, actual_filename, actual_content_type = db_bytes
                except Exception:
                    pass

        if raw_data is None:
            raw_data, actual_filename, actual_content_type = client.get_attachment_bytes(
                folder=folder, uid=uid, filename=filename
            )

        result = await upload_to_paperless(
            data=raw_data,
            filename=actual_filename,
            content_type=actual_content_type,
            title=arguments.get("title"),
            correspondent_id=arguments.get("correspondent_id"),
            document_type_id=arguments.get("document_type_id"),
            tag_ids=arguments.get("tag_ids"),
        )
        return [TextContent(type="text", text=str(result))]

    elif name == "transfer_to_hero":
        from ..transfer import upload_to_hero

        folder = arguments.get("folder", "INBOX")
        uid = arguments.get("uid")
        filename = arguments.get("filename")

        raw_data = None
        actual_filename = filename or "attachment"
        actual_content_type = "application/octet-stream"

        if _DB_ENABLED:
            store = get_email_store()
            if store and uid:
                try:
                    db_bytes = store.get_attachment_bytes_by_uid(
                        folder=folder, uid=int(uid), filename=filename
                    )
                    if db_bytes:
                        raw_data, actual_filename, actual_content_type = db_bytes
                except Exception:
                    pass

        if raw_data is None:
            raw_data, actual_filename, actual_content_type = client.get_attachment_bytes(
                folder=folder, uid=uid, filename=filename
            )

        result = await upload_to_hero(
            data=raw_data,
            filename=actual_filename,
            content_type=actual_content_type,
            project_id=arguments["project_id"],
            category=arguments.get("category"),
        )
        return [TextContent(type="text", text=str(result))]

    # ------------------------------------------------------------------
    # DB-backed tools (only active when EMAIL_DB_ENABLED=true)
    # ------------------------------------------------------------------

    elif name == "db_search_emails":
        store = get_email_store()
        if store is None:
            return [TextContent(type="text", text="Error: EMAIL_DB_ENABLED is not set to true.")]
        results = store.search_fts(
            query=arguments["query"],
            folder=arguments.get("folder"),
            limit=arguments.get("limit", 20),
        )
        # Strip large body_html from results to keep output readable
        for r in results:
            r.pop("body_html", None)
            body = r.get("body_text") or ""
            r["body_text"] = body[:500] + "…" if len(body) > 500 else body
        return [TextContent(type="text", text=str(results))]

    elif name == "db_list_emails":
        store = get_email_store()
        if store is None:
            return [TextContent(type="text", text="Error: EMAIL_DB_ENABLED is not set to true.")]
        results = store.list_emails(
            folder=arguments.get("folder"),
            limit=arguments.get("limit", 50),
            offset=arguments.get("offset", 0),
            unread_only=arguments.get("unread_only", False),
        )
        return [TextContent(type="text", text=str(results))]

    elif name == "db_sync_status":
        store = get_email_store()
        if store is None:
            return [TextContent(type="text", text="Error: EMAIL_DB_ENABLED is not set to true.")]
        return [TextContent(type="text", text=str(store.get_stats()))]

    return None  # Not an IMAP tool


async def handle_smtp_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle SMTP tool calls."""
    imap_client = get_imap_client()
    smtp_client = get_smtp_client()

    if name == "send_email":
        # Resolve server-side attach_from references (e.g. Paperless doc IDs)
        # into base64-encoded attachment dicts, then merge with caller-supplied
        # inline attachments. The fetched bytes never traverse the LLM context.
        from ..transfer import resolve_attach_from

        attach_from_dicts = await resolve_attach_from(arguments.get("attach_from"))

        # Parse attachments (inline base64 from caller + resolved from sources)
        attachments = []
        for att in list(arguments.get("attachments", [])) + attach_from_dicts:
            attachments.append(
                Attachment(
                    filename=att["filename"],
                    content_type=att.get("content_type", "application/octet-stream"),
                    data=base64.b64decode(att["data_base64"]),
                )
            )

        result = send_email(
            client=smtp_client,
            to=arguments["to"],
            subject=arguments["subject"],
            body_text=arguments.get("body_text"),
            body_html=arguments.get("body_html"),
            cc=arguments.get("cc"),
            bcc=arguments.get("bcc"),
            attachments=attachments if attachments else None,
        )
        return [TextContent(type="text", text=str(result))]

    elif name == "send_reply":
        result = send_reply(
            client=smtp_client,
            to=arguments["to"],
            subject=arguments["subject"],
            body_text=arguments.get("body_text"),
            body_html=arguments.get("body_html"),
            reply_to_message_id=arguments.get("reply_to_message_id"),
            quote_original=arguments.get("quote_original", True),
        )
        return [TextContent(type="text", text=str(result))]

    elif name == "send_forward":
        # Optionally fetch original email if folder and message_id provided
        original_email_data = None
        folder = arguments.get("original_folder")
        msg_id = arguments.get("original_message_id")

        if folder and msg_id:
            try:
                original_email_data = imap_client.get_email(
                    folder=folder,
                    message_id=msg_id,
                    include_body=True,
                )
            except Exception:
                pass  # Continue without original email data

        result = send_forward(
            client=smtp_client,
            to=arguments["to"],
            subject=arguments["subject"],
            original_email_data=original_email_data,
            body_text=arguments.get("body_text"),
            body_html=arguments.get("body_html"),
        )
        return [TextContent(type="text", text=str(result))]

    # ---------------------------------------------------------------------
    # Draft management – APPENDs to the IMAP drafts folder, no SMTP send.
    # The drafts module needs the raw imaplib connection (for APPEND /
    # UID STORE / EXPUNGE), which we get from the IMAP client wrapper.
    # ---------------------------------------------------------------------
    elif name in (
        "save_draft",
        "update_draft",
        "delete_draft",
        "save_reply_draft",
        "save_forward_draft",
    ):
        from ..operations import drafts as draft_ops
        from ..transfer import resolve_attach_from

        connection = imap_client._ensure_connected()
        sender = imap_client.config.user

        # Resolve attach_from once per call. delete_draft has no attach_from
        # parameter, so we skip the lookup for it. The result is the standard
        # attachment-dict shape (base64), ready to be concatenated with the
        # caller's inline attachments list.
        attach_from_dicts: list[dict] = []
        if name != "delete_draft":
            attach_from_dicts = await resolve_attach_from(arguments.get("attach_from"))

        def _merge_attachments(key: str = "attachments") -> list[dict] | None:
            merged = list(arguments.get(key) or []) + attach_from_dicts
            return merged or None

        if name == "save_draft":
            result = draft_ops.save_draft(
                connection=connection,
                sender=sender,
                to=arguments["to"],
                subject=arguments["subject"],
                body_text=arguments.get("body_text"),
                body_html=arguments.get("body_html"),
                cc=arguments.get("cc"),
                bcc=arguments.get("bcc"),
                attachments=_merge_attachments(),
                drafts_folder=arguments.get("drafts_folder"),
            )
        elif name == "update_draft":
            result = draft_ops.update_draft(
                connection=connection,
                uid=int(arguments["uid"]),
                sender=sender,
                to=arguments["to"],
                subject=arguments["subject"],
                body_text=arguments.get("body_text"),
                body_html=arguments.get("body_html"),
                cc=arguments.get("cc"),
                bcc=arguments.get("bcc"),
                attachments=_merge_attachments(),
                folder=arguments.get("drafts_folder"),
            )
        elif name == "delete_draft":
            result = draft_ops.delete_draft(
                connection=connection,
                uid=int(arguments["uid"]),
                folder=arguments.get("drafts_folder"),
            )
        elif name == "save_reply_draft":
            result = draft_ops.save_reply_draft(
                connection=connection,
                sender=sender,
                original_uid=int(arguments["original_uid"]),
                original_folder=arguments.get("original_folder", "INBOX"),
                body_text=arguments.get("body_text"),
                body_html=arguments.get("body_html"),
                reply_all=arguments.get("reply_all", False),
                include_quote=arguments.get("include_quote", True),
                attachments=_merge_attachments(),
                drafts_folder=arguments.get("drafts_folder"),
            )
        elif name == "save_forward_draft":
            # For save_forward_draft, attach_from items go alongside the
            # explicit `additional_attachments` list rather than overwriting
            # the carried-over original attachments controlled by
            # `forward_attachments`.
            result = draft_ops.save_forward_draft(
                connection=connection,
                sender=sender,
                original_uid=int(arguments["original_uid"]),
                original_folder=arguments.get("original_folder", "INBOX"),
                to=arguments["to"],
                cc=arguments.get("cc"),
                bcc=arguments.get("bcc"),
                body_text=arguments.get("body_text"),
                body_html=arguments.get("body_html"),
                forward_attachments=arguments.get("forward_attachments", True),
                additional_attachments=_merge_attachments("additional_attachments"),
                drafts_folder=arguments.get("drafts_folder"),
            )
        else:  # pragma: no cover - exhaustive above
            return None
        return [TextContent(type="text", text=str(result))]

    return None  # Not an SMTP tool


__all__ = [
    "get_imap_tools",
    "get_smtp_tools",
    "get_all_tools",
    "handle_imap_tool",
    "handle_smtp_tool",
]
