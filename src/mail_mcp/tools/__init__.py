"""MCP Tools definitions and handlers for IMAP operations."""

import base64
import os

from mcp.types import TextContent, Tool

from ..client import get_imap_client
from ..db import get_email_store
from ..smtp import Attachment, get_smtp_client
from ..smtp.operations import send_email, send_forward, send_reply

_DB_ENABLED = os.getenv("EMAIL_DB_ENABLED", "false").lower() == "true"


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
                "anyOf": [
                    {"required": ["message_id"]},
                    {"required": ["uid"]},
                ],
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
                "anyOf": [
                    {"required": ["message_id"]},
                    {"required": ["uid"]},
                ],
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
                "anyOf": [
                    {"required": ["message_id"]},
                    {"required": ["uid"]},
                ],
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
                "anyOf": [
                    {"required": ["message_id"]},
                    {"required": ["uid"]},
                ],
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
                "anyOf": [
                    {"required": ["message_id"]},
                    {"required": ["uid"]},
                ],
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
                "anyOf": [
                    {"required": ["message_id"]},
                    {"required": ["uid"]},
                ],
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
                "anyOf": [
                    {"required": ["message_id"]},
                    {"required": ["uid"]},
                ],
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
                "anyOf": [
                    {"required": ["message_id"]},
                    {"required": ["uid"]},
                ],
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
                "Fetch an email attachment as base64-encoded binary data. "
                "Use get_email first to obtain the UID and attachment filenames, "
                "then call this tool to retrieve the actual file content."
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
                            "Exact filename of the attachment to retrieve. "
                            "If omitted, the first attachment in the email is returned."
                        ),
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
            description="Send an email with optional HTML body and attachments",
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
    return tools


async def handle_imap_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle IMAP tool calls."""
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

        # DB-first: serve from local cache when available
        if _DB_ENABLED:
            store = get_email_store()
            if store and uid:
                try:
                    db_result = store.get_attachment_by_uid(
                        folder=folder,
                        uid=int(uid),
                        filename=filename,
                    )
                    if db_result is not None:
                        return [TextContent(type="text", text=str(db_result))]
                except Exception:
                    pass  # Fall back to live IMAP

        # Live IMAP fallback
        result = client.get_attachment(folder=folder, uid=uid, filename=filename)
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
        # Parse attachments
        attachments = []
        for att in arguments.get("attachments", []):
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

    return None  # Not an SMTP tool


__all__ = [
    "get_imap_tools",
    "get_smtp_tools",
    "get_all_tools",
    "handle_imap_tool",
    "handle_smtp_tool",
]
