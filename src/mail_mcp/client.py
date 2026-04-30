"""IMAP Client module with connection management."""

import base64
import email
import imaplib
import re
import threading
from datetime import datetime
from email.policy import default
from typing import Any

from .config import IMAPConfig

# IMAP status constants
IMAP_OK = (b"OK", "OK")


class IMAPClient:
    """IMAP client wrapper with connection management."""

    def __init__(self, config: IMAPConfig):
        self.config = config
        self._connection: imaplib.IMAP4_SSL | None = None
        self._connection_plain: imaplib.IMAP4 | None = None

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
        if status not in IMAP_OK:
            raise Exception(f"{context}: {data}")

    # ==================== Folder Operations ====================

    def list_folders(self) -> list[dict[str, str]]:
        """List all folders."""
        conn = self._ensure_connected()
        status, folders = conn.list()
        self._check_status(status, folders, "Failed to list folders")

        result = []
        for folder in folders:
            if folder:
                parts = folder.decode().split('"')
                if len(parts) >= 3:
                    result.append(
                        {
                            "flags": parts[0].strip(),
                            "delimiter": parts[1],
                            "name": parts[2].strip(),
                        }
                    )
        return result

    def create_folder(self, folder_name: str) -> dict[str, Any]:
        """Create a new folder."""
        conn = self._ensure_connected()
        status, data = conn.create(folder_name)
        self._check_status(status, data, "Failed to create folder")
        return {"success": True, "folder": folder_name}

    def delete_folder(self, folder_name: str) -> dict[str, Any]:
        """Delete a folder."""
        conn = self._ensure_connected()
        status, data = conn.delete(folder_name)
        self._check_status(status, data, "Failed to delete folder")
        return {"success": True, "folder": folder_name}

    def rename_folder(self, old_name: str, new_name: str) -> dict[str, Any]:
        """Rename a folder."""
        conn = self._ensure_connected()
        status, data = conn.rename(old_name, new_name)
        self._check_status(status, data, "Failed to rename folder")
        return {"success": True, "old_name": old_name, "new_name": new_name}

    # ==================== Email Search ====================

    def search_emails(
        self,
        folder: str = "INBOX",
        criteria: str = "ALL",
        conditions: dict[str, Any] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
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
                if key_lower == "unseen" and value:
                    criteria_parts.append("UNSEEN")
                elif key_lower == "seen" and value:
                    criteria_parts.append("SEEN")
                elif key_lower == "flagged" and value:
                    criteria_parts.append("FLAGGED")
                elif key_lower == "from":
                    criteria_parts.extend(["FROM", str(value)])
                elif key_lower == "to":
                    criteria_parts.extend(["TO", str(value)])
                elif key_lower == "subject":
                    criteria_parts.extend(["SUBJECT", str(value)])
                elif key_lower == "since":
                    criteria_parts.extend(["SINCE", str(value)])
                elif key_lower == "before":
                    criteria_parts.extend(["BEFORE", str(value)])
            criteria = " ".join(criteria_parts) if criteria_parts else "ALL"

        status, message_ids = conn.search(None, criteria)
        self._check_status(status, message_ids, "Search failed")

        ids = message_ids[0].split()
        ids = ids[-limit:] if len(ids) > limit else ids

        if not ids:
            return []

        # Batch fetch for better performance - 使用 HEADER.FIELDS 获取需要的字段
        ids_str = b",".join(ids)
        # 使用 BODY.PEEK[HEADER.FIELDS ...] 批量获取邮件头
        status, fetch_data = conn.fetch(
            ids_str, "(UID FLAGS BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE)])"
        )

        result = []
        if status in IMAP_OK and fetch_data:
            # IMAP 批量 fetch 响应格式：
            # 每封邮件返回 2 条数据：
            # 1. tuple: (b'6911 (UID 9859 FLAGS (\Seen) BODY[...] {size}', b'邮件头数据')
            # 2. bytes: b')' 结束符
            for item in fetch_data:
                if isinstance(item, tuple) and len(item) >= 2:
                    try:
                        # 解析邮件头行: b'6911 (UID 9859 FLAGS (\Seen) BODY[...] {size}'
                        header_line = item[0].decode("utf-8", errors="replace")

                        # 提取消息 ID
                        msg_id_match = re.match(r"(\d+)\s+\(", header_line)
                        msg_id = msg_id_match.group(1) if msg_id_match else ""

                        # 提取 UID
                        uid_match = re.search(r"UID\s+(\d+)", header_line)
                        uid = uid_match.group(1) if uid_match else ""

                        # 提取 FLAGS
                        flags_match = re.search(r"FLAGS\s*\(([^)]*)\)", header_line)
                        flags = flags_match.group(1).split() if flags_match else []

                        # 解析邮件头数据
                        header_data = item[1]
                        if header_data:
                            header_msg = email.message_from_bytes(header_data, policy=default)
                            result.append(
                                {
                                    "id": msg_id,
                                    "uid": uid,
                                    "flags": flags,
                                    "subject": header_msg.get("Subject", ""),
                                    "from": header_msg.get("From", ""),
                                    "to": header_msg.get("To", ""),
                                    "date": header_msg.get("Date", ""),
                                }
                            )
                    except Exception:
                        pass

        return result

    def _extract_uid_from_header(self, header: bytes) -> str | None:
        """Extract UID from fetch response header."""
        match = re.search(rb"UID\s+(\d+)", header)
        return match.group(1).decode() if match else None

    def _extract_flags_from_header(self, header: bytes) -> list[str]:
        """Extract flags from fetch response header."""
        match = re.search(rb"FLAGS\s*\(([^)]*)\)", header)
        if match:
            flags_str = match.group(1).decode().strip()
            return flags_str.split() if flags_str else []
        return []

    # ==================== Email Fetch ====================

    def get_email(
        self,
        folder: str = "INBOX",
        message_id: str | None = None,
        uid: str | None = None,
        include_body: bool = True,
        include_attachment_data: bool = False,
    ) -> dict[str, Any]:
        """Get email details by message ID or UID."""
        conn = self._ensure_connected()
        conn.select(folder)

        # BODY.PEEK[] fetches the full raw RFC822 message without marking as read.
        # BODY[] (without PEEK) would mark the message as seen.
        # Avoid ENVELOPE + BODY (no brackets) – those return parsed/structural data
        # that cannot be passed directly to email.message_from_bytes().
        fetch_spec = "(UID FLAGS BODY.PEEK[])" if include_body else "(UID FLAGS BODY.PEEK[HEADER])"

        if uid:
            # UID FETCH requires conn.uid('FETCH', ...) – conn.fetch("UID x", ...) is invalid
            status, msg_data = conn.uid("FETCH", str(uid), fetch_spec)
        else:
            status, msg_data = conn.fetch(message_id, fetch_spec)

        self._check_status(status, msg_data, "Failed to fetch email")

        if not msg_data or not msg_data[0]:
            raise Exception("Email not found")

        # msg_data is a list; each multi-part response item is a tuple
        # (b'seqno (UID x FLAGS (...) BODY[] {size}', b'<raw bytes>')
        raw_item = next((item for item in msg_data if isinstance(item, tuple)), None)
        if raw_item is None:
            raise Exception("Email not found")

        envelope = raw_item
        if isinstance(envelope, tuple):
            msg = email.message_from_bytes(envelope[1], policy=default)

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
                            att: dict[str, Any] = {
                                "filename": part.get_filename() or "unknown",
                                "content_type": content_type,
                            }
                            if include_attachment_data:
                                raw = part.get_payload(decode=True)
                                if raw is not None:
                                    att["size"] = len(raw)
                                    att["data"] = raw
                            result["attachments"].append(att)
                else:
                    result["body_text"] = self._get_part_content(msg)

            return result

        raise Exception("Failed to parse email")

    def get_attachment(
        self,
        folder: str = "INBOX",
        uid: str | None = None,
        filename: str | None = None,
        include_data: bool = False,
        max_size_bytes: int = 51200,
    ) -> dict[str, Any]:
        """Fetch attachment metadata (and optionally binary data) from an email.

        By default returns only metadata (filename, content_type, size).
        Set include_data=True to also receive base64-encoded content, but only
        when the file is ≤ max_size_bytes (default 50 KB) to avoid overflowing
        Claude's context window.  For larger files use transfer_to_paperless /
        transfer_to_hero instead.
        """
        conn = self._ensure_connected()
        conn.select(folder)

        if not uid:
            raise ValueError("uid is required for get_attachment")

        status, msg_data = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
        self._check_status(status, msg_data, "Failed to fetch email for attachment")

        raw_item = next((item for item in msg_data if isinstance(item, tuple)), None)
        if raw_item is None:
            raise Exception(f"Email UID {uid} not found")

        msg = email.message_from_bytes(raw_item[1], policy=default)

        for part in msg.walk():
            part_filename = part.get_filename()
            if part_filename is None:
                continue
            if filename is not None and part_filename != filename:
                continue
            raw = part.get_payload(decode=True)
            if raw is None:
                continue

            result: dict[str, Any] = {
                "uid": uid,
                "filename": part_filename,
                "content_type": part.get_content_type(),
                "size": len(raw),
            }

            if include_data:
                if len(raw) <= max_size_bytes:
                    result["data_base64"] = base64.b64encode(raw).decode("ascii")
                else:
                    result["data_base64"] = None
                    result["warning"] = (
                        f"File too large ({len(raw) // 1024} KB > "
                        f"{max_size_bytes // 1024} KB limit). "
                        "Use transfer_to_paperless or transfer_to_hero instead."
                    )
            return result

        target = f"'{filename}'" if filename else "any attachment"
        raise Exception(f"No attachment {target} found in email UID {uid}")

    def get_attachment_bytes(
        self,
        folder: str = "INBOX",
        uid: str | None = None,
        filename: str | None = None,
    ) -> tuple[bytes, str, str]:
        """Fetch raw attachment bytes for server-side transfer.

        Returns (data, filename, content_type).  Never sends data to Claude.
        """
        conn = self._ensure_connected()
        conn.select(folder)

        if not uid:
            raise ValueError("uid is required")

        status, msg_data = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
        self._check_status(status, msg_data, "Failed to fetch email for transfer")

        raw_item = next((item for item in msg_data if isinstance(item, tuple)), None)
        if raw_item is None:
            raise Exception(f"Email UID {uid} not found")

        msg = email.message_from_bytes(raw_item[1], policy=default)

        for part in msg.walk():
            part_filename = part.get_filename()
            if part_filename is None:
                continue
            if filename is not None and part_filename != filename:
                continue
            raw = part.get_payload(decode=True)
            if raw is not None:
                return raw, part_filename, part.get_content_type()

        target = f"'{filename}'" if filename else "any attachment"
        raise Exception(f"No attachment {target} found in email UID {uid}")

    def _get_uid(self, msg_data: Any) -> str | None:
        """Extract UID from message data."""
        for item in msg_data:
            if isinstance(item, tuple):
                if b"UID" in item[0]:
                    return item[1].decode() if isinstance(item[1], bytes) else str(item[1])
        return None

    def _parse_flags(self, msg_data: Any) -> list[str]:
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

    # ==================== Email Flags ====================

    def mark_read(
        self,
        folder: str = "INBOX",
        message_id: str | None = None,
        uid: str | None = None,
    ) -> dict[str, Any]:
        """Mark email as read (SEEN)."""
        return self._set_flag(folder, message_id, uid, "+FLAGS", "\\Seen")

    def mark_unread(
        self,
        folder: str = "INBOX",
        message_id: str | None = None,
        uid: str | None = None,
    ) -> dict[str, Any]:
        """Mark email as unread (remove SEEN flag)."""
        return self._set_flag(folder, message_id, uid, "-FLAGS", "\\Seen")

    def mark_flagged(
        self,
        folder: str = "INBOX",
        message_id: str | None = None,
        uid: str | None = None,
    ) -> dict[str, Any]:
        """Mark email as flagged (starred)."""
        return self._set_flag(folder, message_id, uid, "+FLAGS", "\\Flagged")

    def unmark_flagged(
        self,
        folder: str = "INBOX",
        message_id: str | None = None,
        uid: str | None = None,
    ) -> dict[str, Any]:
        """Unmark email as flagged."""
        return self._set_flag(folder, message_id, uid, "-FLAGS", "\\Flagged")

    def _set_flag(
        self,
        folder: str,
        message_id: str | None,
        uid: str | None,
        mode: str,
        flag: str,
    ) -> dict[str, Any]:
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

    # ==================== Email Move/Copy/Delete ====================

    def move_email(
        self,
        source_folder: str,
        target_folder: str,
        message_id: str | None = None,
        uid: str | None = None,
    ) -> dict[str, Any]:
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
        message_id: str | None = None,
        uid: str | None = None,
    ) -> dict[str, Any]:
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
        message_id: str | None = None,
        uid: str | None = None,
    ) -> dict[str, Any]:
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


# Global client instance with thread-safe lock
_imap_client: IMAPClient | None = None
_imap_lock = threading.Lock()


def get_imap_client() -> IMAPClient:
    """Get or create IMAP client instance (thread-safe)."""
    global _imap_client
    if _imap_client is None:
        with _imap_lock:
            # Double-check after acquiring lock
            if _imap_client is None:
                config = IMAPConfig.from_env()
                _imap_client = IMAPClient(config)
    return _imap_client


def reset_imap_client() -> None:
    """Reset IMAP client (for testing, thread-safe)."""
    global _imap_client
    with _imap_lock:
        if _imap_client:
            _imap_client.disconnect()
            _imap_client = None


__all__ = [
    "IMAPClient",
    "IMAP_OK",
    "get_imap_client",
    "reset_imap_client",
]
