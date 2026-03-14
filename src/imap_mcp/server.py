"""
IMAP MCP Server - MCP Protocol Interface

Provides email management capabilities via the MCP (Model Context Protocol).
"""

import os
import imaplib
import email
import base64
from email.parser import Parser
from email.policy import default
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# SMTP imports
from .smtp import SMTPConfig, SMTPClient, Attachment, get_smtp_client, reset_smtp_client
from .smtp.operations import send_email, send_reply, send_forward


@dataclass
class IMAPConfig:
    """IMAP configuration from environment variables."""
    host: str
    port: int
    user: str
    password: str
    ssl: bool = True

    @classmethod
    def from_env(cls) -> "IMAPConfig":
        """Create config from environment variables."""
        return cls(
            host=os.getenv("IMAP_HOST", "imap.example.com"),
            port=int(os.getenv("IMAP_PORT", "993")),
            user=os.getenv("EMAIL_USER", ""),
            password=os.getenv("EMAIL_PASSWORD", ""),
            ssl=os.getenv("IMAP_SSL", "true").lower() == "true",
        )


class IMAPClient:
    """IMAP client wrapper with connection management."""

    def __init__(self, config: IMAPConfig):
        self.config = config
        self._connection: Optional[imaplib.IMAP4_SSL] = None
        self._connection_plain: Optional[imaplib.IMAP4] = None

    def connect(self) -> None:
        """Establish IMAP connection."""
        try:
            if self.config.ssl:
                self._connection = imaplib.IMAP4_SSL(
                    host=self.config.host,
                    port=self.config.port,
                )
            else:
                self._connection_plain = imaplib.IMAP4(
                    host=self.config.host,
                    port=self.config.port,
                )
                self._connection = self._connection_plain

            self._connection.login(self.config.user, self.config.password)
        except imaplib.IMAP4.error as e:
            raise Exception(f"IMAP connection failed: {str(e)}")

    def disconnect(self) -> None:
        """Close IMAP connection."""
        if self._connection:
            try:
                self._connection.logout()
            except Exception:
                pass
            self._connection = None
            self._connection_plain = None

    def _ensure_connected(self) -> imaplib.IMAP4:
        """Ensure connection is active."""
        if self._connection is None:
            self.connect()
        return self._connection

    def _check_status(self, status: Any, data: Any, context: str) -> None:
        """Check IMAP status and raise on error."""
        if status != b"OK" and status != "OK":
            raise Exception(f"{context}: {data}")

    def list_folders(self) -> List[Dict[str, str]]:
        """List all folders."""
        conn = self._ensure_connected()
        status, folders = conn.list()
        self._check_status(status, folders, "Failed to list folders")

        result = []
        for folder in folders:
            if folder:
                parts = folder.decode().split('"')
                if len(parts) >= 3:
                    result.append({
                        "flags": parts[0].strip(),
                        "delimiter": parts[1],
                        "name": parts[2].strip(),
                    })
        return result

    def create_folder(self, folder_name: str) -> Dict[str, Any]:
        """Create a new folder."""
        conn = self._ensure_connected()
        status, data = conn.create(folder_name)
        self._check_status(status, data, "Failed to create folder")
        return {"success": True, "folder": folder_name}

    def delete_folder(self, folder_name: str) -> Dict[str, Any]:
        """Delete a folder."""
        conn = self._ensure_connected()
        status, data = conn.delete(folder_name)
        self._check_status(status, data, "Failed to delete folder")
        return {"success": True, "folder": folder_name}

    def rename_folder(self, old_name: str, new_name: str) -> Dict[str, Any]:
        """Rename a folder."""
        conn = self._ensure_connected()
        status, data = conn.rename(old_name, new_name)
        self._check_status(status, data, "Failed to rename folder")
        return {"success": True, "old_name": old_name, "new_name": new_name}

    def search_emails(
        self,
        folder: str = "INBOX",
        criteria: str = "ALL",
        conditions: Dict[str, Any] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Search emails with criteria.
        
        Args:
            folder: 邮箱文件夹
            criteria: IMAP 搜索条件字符串 (如 "UNSEEN", "FROM xxx@xx.com")
            conditions: 高级搜索条件字典 (如 {"unseen": True, "from": "xxx@xx.com"})
            limit: 返回结果数量限制
        """
        conn = self._ensure_connected()
        conn.select(folder)

        # 如果提供了 conditions，转换为 IMAP 搜索条件
        if conditions:
            criteria_parts = []
            for key, value in conditions.items():
                key_lower = key.lower()
                if key_lower == 'unseen' and value:
                    criteria_parts.append('UNSEEN')
                elif key_lower == 'seen' and value:
                    criteria_parts.append('SEEN')
                elif key_lower == 'flagged' and value:
                    criteria_parts.append('FLAGGED')
                elif key_lower == 'from':
                    criteria_parts.extend(['FROM', str(value)])
                elif key_lower == 'to':
                    criteria_parts.extend(['TO', str(value)])
                elif key_lower == 'subject':
                    criteria_parts.extend(['SUBJECT', str(value)])
                elif key_lower == 'since':
                    criteria_parts.extend(['SINCE', str(value)])
                elif key_lower == 'before':
                    criteria_parts.extend(['BEFORE', str(value)])
            criteria = ' '.join(criteria_parts) if criteria_parts else 'ALL'

        status, message_ids = conn.search(None, criteria)
        self._check_status(status, message_ids, "Search failed")

        ids = message_ids[0].split()
        ids = ids[-limit:] if len(ids) > limit else ids

        result = []
        for msg_id in ids:
            status, msg_data = conn.fetch(msg_id, "(UID FLAGS ENVELOPE)")
            if (status == b"OK" or status == "OK") and msg_data:
                envelope = msg_data[0]
                if isinstance(envelope, tuple):
                    msg = email.message_from_bytes(
                        envelope[1], policy=default
                    )
                    result.append({
                        "id": msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                        "uid": self._get_uid(msg_data),
                        "subject": msg.get("Subject", ""),
                        "from": msg.get("From", ""),
                        "to": msg.get("To", ""),
                        "date": msg.get("Date", ""),
                        "flags": self._parse_flags(msg_data),
                    })

        return result

    def _get_uid(self, msg_data: Any) -> Optional[str]:
        """Extract UID from message data."""
        for item in msg_data:
            if isinstance(item, tuple):
                if b"UID" in item[0]:
                    return item[1].decode() if isinstance(item[1], bytes) else str(item[1])
        return None

    def _parse_flags(self, msg_data: Any) -> List[str]:
        """Parse flags from message data."""
        for item in msg_data:
            if isinstance(item, tuple):
                if b"FLAGS" in item[0]:
                    flags_bytes = item[1]
                    if isinstance(flags_bytes, bytes):
                        flags_str = flags_bytes.decode()
                        return flags_str.strip("()").split()
                    return []
        return []

    def get_email(
        self,
        folder: str = "INBOX",
        message_id: Optional[str] = None,
        uid: Optional[str] = None,
        include_body: bool = True,
    ) -> Dict[str, Any]:
        """Get email details by message ID or UID."""
        conn = self._ensure_connected()
        conn.select(folder)

        if uid:
            query = f"UID {uid}"
        else:
            query = message_id

        status, msg_data = conn.fetch(query, "(UID FLAGS ENVELOPE BODY)" if include_body else "(UID FLAGS ENVELOPE)")
        self._check_status(status, msg_data, "Failed to fetch email")

        if not msg_data or not msg_data[0]:
            raise Exception("Email not found")

        envelope = msg_data[0]
        if isinstance(envelope, tuple):
            msg = email.message_from_bytes(
                envelope[1], policy=default
            )

            result = {
                "id": message_id or uid,
                "uid": self._get_uid(msg_data),
                "subject": msg.get("Subject", ""),
                "from": msg.get("From", ""),
                "to": msg.get("To", ""),
                "cc": msg.get("Cc", ""),
                "date": msg.get("Date", ""),
                "flags": self._parse_flags(msg_data),
                "body_text": "",
                "body_html": "",
                "attachments": [],
            }

            if include_body:
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        if content_type == "text/plain" and not result["body_text"]:
                            result["body_text"] = self._get_part_content(part)
                        elif content_type == "text/html" and not result["body_html"]:
                            result["body_html"] = self._get_part_content(part)
                        if part.get_content_disposition() == "attachment":
                            result["attachments"].append({
                                "filename": part.get_filename() or "unknown",
                                "content_type": content_type,
                            })
                else:
                    result["body_text"] = self._get_part_content(msg)

            return result

        raise Exception("Failed to parse email")

    def _get_part_content(self, part) -> str:
        """Get content from email part."""
        try:
            charset = part.get_content_charset() or "utf-8"
            content = part.get_payload(decode=True)
            if content:
                return content.decode(charset, errors="replace")
        except Exception:
            pass
        return ""

    def mark_read(
        self,
        folder: str = "INBOX",
        message_id: Optional[str] = None,
        uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Mark email as read (SEEN)."""
        return self._set_flag(folder, message_id, uid, "+FLAGS", "\\Seen")

    def mark_unread(
        self,
        folder: str = "INBOX",
        message_id: Optional[str] = None,
        uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Mark email as unread (remove SEEN flag)."""
        return self._set_flag(folder, message_id, uid, "-FLAGS", "\\Seen")

    def mark_flagged(
        self,
        folder: str = "INBOX",
        message_id: Optional[str] = None,
        uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Mark email as flagged (starred)."""
        return self._set_flag(folder, message_id, uid, "+FLAGS", "\\Flagged")

    def unmark_flagged(
        self,
        folder: str = "INBOX",
        message_id: Optional[str] = None,
        uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Unmark email as flagged."""
        return self._set_flag(folder, message_id, uid, "-FLAGS", "\\Flagged")

    def _set_flag(
        self,
        folder: str,
        message_id: Optional[str],
        uid: Optional[str],
        mode: str,
        flag: str,
    ) -> Dict[str, Any]:
        """Set or unset a flag on an email."""
        conn = self._ensure_connected()
        conn.select(folder)

        if uid:
            query = f"UID {uid}"
        else:
            query = message_id

        status, data = conn.store(query, mode, flag)
        self._check_status(status, data, "Failed to set flag")

        return {
            "success": True,
            "message_id": message_id,
            "uid": uid,
            "flag": flag,
            "mode": mode,
        }

    def move_email(
        self,
        source_folder: str,
        target_folder: str,
        message_id: Optional[str] = None,
        uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Move email to another folder."""
        conn = self._ensure_connected()
        conn.select(source_folder)

        if uid:
            query = f"UID {uid}"
        else:
            query = message_id

        status, data = conn.move(query, target_folder)
        self._check_status(status, data, "Failed to move email")

        return {
            "success": True,
            "source_folder": source_folder,
            "target_folder": target_folder,
            "message_id": message_id,
            "uid": uid,
        }

    def copy_email(
        self,
        source_folder: str,
        target_folder: str,
        message_id: Optional[str] = None,
        uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Copy email to another folder."""
        conn = self._ensure_connected()
        conn.select(source_folder)

        if uid:
            query = f"UID {uid}"
        else:
            query = message_id

        status, data = conn.copy(query, target_folder)
        self._check_status(status, data, "Failed to copy email")

        return {
            "success": True,
            "source_folder": source_folder,
            "target_folder": target_folder,
            "message_id": message_id,
            "uid": uid,
        }

    def delete_email(
        self,
        folder: str = "INBOX",
        message_id: Optional[str] = None,
        uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delete email (mark as Deleted)."""
        conn = self._ensure_connected()
        conn.select(folder)

        if uid:
            query = f"UID {uid}"
        else:
            query = message_id

        status, data = conn.store(query, "+FLAGS", "\\Deleted")
        self._check_status(status, data, "Failed to delete email")

        # Expunge to permanently delete
        conn.expunge()

        return {
            "success": True,
            "folder": folder,
            "message_id": message_id,
            "uid": uid,
        }

    def get_current_date(self) -> str:
        """Get current date in ISO format."""
        return datetime.now().isoformat()


# Global client instance
_imap_client: Optional[IMAPClient] = None


def get_imap_client() -> IMAPClient:
    """Get or create IMAP client instance."""
    global _imap_client
    if _imap_client is None:
        config = IMAPConfig.from_env()
        _imap_client = IMAPClient(config)
    return _imap_client


def reset_imap_client() -> None:
    """Reset IMAP client (for testing)."""
    global _imap_client
    if _imap_client:
        _imap_client.disconnect()
        _imap_client = None


# Create MCP Server
app = Server("imap-mcp-server")


@app.list_tools()
async def list_tools() -> List[Tool]:
    """List all available tools."""
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
        # SMTP Tools
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


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> List[TextContent]:
    """Handle tool calls."""
    try:
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
            result = client.search_emails(
                folder=arguments.get("folder", "INBOX"),
                criteria=arguments.get("criteria", "ALL"),
                limit=arguments.get("limit", 10),
            )
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

        # SMTP Tools
        elif name == "send_email":
            smtp_client = get_smtp_client()
            
            # Parse attachments
            attachments = []
            for att in arguments.get("attachments", []):
                attachments.append(Attachment(
                    filename=att["filename"],
                    content_type=att.get("content_type", "application/octet-stream"),
                    data=base64.b64decode(att["data_base64"]),
                ))
            
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
            smtp_client = get_smtp_client()
            
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
            smtp_client = get_smtp_client()
            
            # Optionally fetch original email if folder and message_id provided
            original_email_data = None
            folder = arguments.get("original_folder")
            msg_id = arguments.get("original_message_id")
            
            if folder and msg_id:
                try:
                    original_email_data = client.get_email(
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
                original_folder=folder,
                original_message_id=msg_id,
                body_text=arguments.get("body_text"),
                body_html=arguments.get("body_html"),
            )
            return [TextContent(type="text", text=str(result))]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    """Main entry point for the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())


def run():
    """Synchronous entry point for console script."""
    import asyncio
    asyncio.run(main())