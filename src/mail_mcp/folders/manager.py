"""
Folders module for IMAP MCP server.

Provides folder management operations including:
- Listing folders
- Creating, deleting, and renaming folders
- Subscribing/unsubscribing to folders
- Getting folder status
"""

import re
from typing import Any


class FolderError(Exception):
    """Base exception for folder operations."""

    pass


class FolderNotFoundError(FolderError):
    """Raised when a folder does not exist."""

    pass


class FolderExistsError(FolderError):
    """Raised when trying to create a folder that already exists."""

    pass


class InvalidFolderNameError(FolderError):
    """Raised when folder name is invalid."""

    pass


class FolderManager:
    """
    Manages IMAP folder operations.

    Provides a high-level interface for folder management including
    listing, creating, deleting, renaming, and subscribing to folders.

    Attributes:
        _conn: IMAP connection instance
    """

    # Common invalid characters in folder names
    INVALID_CHARS = r"[\x00-\x1f\x7f]"

    def __init__(self, connection) -> None:
        """
        Initialize FolderManager with an IMAP connection.

        Args:
            connection: An active IMAP connection (must have IMAP4rev2 commands)
        """
        self._conn = connection

    def _validate_folder_name(self, name: str) -> None:
        """
        Validate folder name format.

        Args:
            name: Folder name to validate

        Raises:
            InvalidFolderNameError: If name is invalid
        """
        if not name:
            raise InvalidFolderNameError("Folder name cannot be empty")

        if name.strip() != name:
            raise InvalidFolderNameError("Folder name cannot start or end with whitespace")

        if re.search(self.INVALID_CHARS, name):
            raise InvalidFolderNameError("Folder name contains invalid characters")

    def _parse_folder_list(self, response: tuple) -> list[str]:
        """
        Parse IMAP LIST/LSUB response into folder names.

        Args:
            response: Tuple from IMAP list command (OK/NO, [responses])

        Returns:
            List of folder name strings
        """
        if not response or len(response) < 2:
            return []

        folders = []
        responses = response[1] if isinstance(response[1], list) else [response[1]]

        for item in responses:
            if item is None:
                continue

            # Handle bytes
            if isinstance(item, bytes):
                item = item.decode("utf-8", errors="replace")

            # Parse folder name from response
            # Format: b'(\\HasNoChildren) "/" "INBOX"'
            # or just b'INBOX'
            import re

            # 提取最后一个引号内的内容
            match = re.search(r'"([^"]+)"$', item.strip())
            if match:
                folder_name = match.group(1)
            else:
                # 如果没有引号，直接取最后一部分
                parts = item.strip().split()
                folder_name = parts[-1] if parts else item.strip()

            if folder_name:
                folders.append(folder_name)

        return folders

    def list_folders(self, directory: str = "", pattern: str = "*") -> list[str]:
        """
        List all folders matching the pattern.

        Uses IMAP LIST command to retrieve all mailboxes.

        Args:
            directory: Directory prefix (e.g., 'INBOX')
            pattern: Mailbox pattern (default '*' matches all)

        Returns:
            List of folder names

        Raises:
            FolderError: If the operation fails

        Example:
            >>> folders = manager.list_folders()
            >>> print(folders)
            ['INBOX', 'INBOX/Sent', 'INBOX/Drafts', 'Archive']
        """
        try:
            response = self._conn.list(directory, pattern)

            # 检查状态 (可能是 'OK' 或 b'OK')
            status = response[0]
            if status not in ("OK", b"OK"):
                error_msg = (
                    response[1][0].decode("utf-8", errors="replace")
                    if response[1]
                    else "Unknown error"
                )
                raise FolderError(f"Failed to list folders: {error_msg}")

            return self._parse_folder_list(response)

        except Exception as e:
            if isinstance(e, FolderError):
                raise
            raise FolderError(f"Failed to list folders: {str(e)}")

    def list_subscribed_folders(self, directory: str = "", pattern: str = "*") -> list[str]:
        """
        List subscribed folders matching the pattern.

        Uses IMAP LSUB command to retrieve subscribed mailboxes.

        Args:
            directory: Directory prefix
            pattern: Mailbox pattern

        Returns:
            List of subscribed folder names

        Raises:
            FolderError: If the operation fails
        """
        try:
            response = self._conn.lsub(directory, pattern)

            # 检查状态 (可能是 'OK' 或 b'OK')
            status = response[0]
            if status not in ("OK", b"OK"):
                error_msg = (
                    response[1][0].decode("utf-8", errors="replace")
                    if response[1]
                    else "Unknown error"
                )
                raise FolderError(f"Failed to list subscribed folders: {error_msg}")

            return self._parse_folder_list(response)

        except Exception as e:
            if isinstance(e, FolderError):
                raise
            raise FolderError(f"Failed to list subscribed folders: {str(e)}")

    def create_folder(self, name: str) -> bool:
        """
        Create a new folder/mailbox.

        Args:
            name: Name of the folder to create

        Returns:
            True if successful

        Raises:
            InvalidFolderNameError: If folder name is invalid
            FolderExistsError: If folder already exists
            FolderError: If operation fails
        """
        self._validate_folder_name(name)

        try:
            response = self._conn.create(name)

            status = response[0]
            if status not in ("OK", b"OK"):
                error_msg = (
                    response[1][0].decode("utf-8", errors="replace")
                    if response[1]
                    else "Unknown error"
                )

                if "already exists" in error_msg.lower():
                    raise FolderExistsError(f"Folder '{name}' already exists")

                raise FolderError(f"Failed to create folder: {error_msg}")

            return True

        except FolderError:
            raise
        except Exception as e:
            raise FolderError(f"Failed to create folder: {str(e)}")

    def delete_folder(self, name: str) -> bool:
        """
        Delete a folder/mailbox.

        Args:
            name: Name of the folder to delete

        Returns:
            True if successful

        Raises:
            FolderNotFoundError: If folder does not exist
            FolderError: If operation fails
        """
        self._validate_folder_name(name)

        try:
            response = self._conn.delete(name)

            status = response[0]
            if status not in ("OK", b"OK"):
                error_msg = (
                    response[1][0].decode("utf-8", errors="replace")
                    if response[1]
                    else "Unknown error"
                )

                if "does not exist" in error_msg.lower() or "not found" in error_msg.lower():
                    raise FolderNotFoundError(f"Folder '{name}' does not exist")

                raise FolderError(f"Failed to delete folder: {error_msg}")

            return True

        except FolderError:
            raise
        except Exception as e:
            raise FolderError(f"Failed to delete folder: {str(e)}")

    def rename_folder(self, old_name: str, new_name: str) -> bool:
        """
        Rename a folder.

        Args:
            old_name: Current folder name
            new_name: New folder name

        Returns:
            True if successful

        Raises:
            InvalidFolderNameError: If either name is invalid
            FolderNotFoundError: If source folder does not exist
            FolderExistsError: If destination folder already exists
            FolderError: If operation fails
        """
        self._validate_folder_name(old_name)
        self._validate_folder_name(new_name)

        if old_name == new_name:
            raise InvalidFolderNameError("Source and destination names must be different")

        try:
            response = self._conn.rename(old_name, new_name)

            status = response[0]
            if status not in ("OK", b"OK"):
                error_msg = (
                    response[1][0].decode("utf-8", errors="replace")
                    if response[1]
                    else "Unknown error"
                )

                if "does not exist" in error_msg.lower() or "not found" in error_msg.lower():
                    raise FolderNotFoundError(f"Folder '{old_name}' does not exist")

                if "already exists" in error_msg.lower():
                    raise FolderExistsError(f"Folder '{new_name}' already exists")

                raise FolderError(f"Failed to rename folder: {error_msg}")

            return True

        except FolderError:
            raise
        except Exception as e:
            raise FolderError(f"Failed to rename folder: {str(e)}")

    def subscribe_folder(self, name: str) -> bool:
        """
        Subscribe to a folder.

        Subscribing to a folder adds it to the set of active
        mailboxes shown by some email clients.

        Args:
            name: Folder name to subscribe to

        Returns:
            True if successful

        Raises:
            FolderNotFoundError: If folder does not exist
            FolderError: If operation fails
        """
        self._validate_folder_name(name)

        try:
            response = self._conn.subscribe(name)

            status = response[0]
            if status not in ("OK", b"OK"):
                error_msg = (
                    response[1][0].decode("utf-8", errors="replace")
                    if response[1]
                    else "Unknown error"
                )

                if "does not exist" in error_msg.lower():
                    raise FolderNotFoundError(f"Folder '{name}' does not exist")

                raise FolderError(f"Failed to subscribe to folder: {error_msg}")

            return True

        except FolderError:
            raise
        except Exception as e:
            raise FolderError(f"Failed to subscribe to folder: {str(e)}")

    def unsubscribe_folder(self, name: str) -> bool:
        """
        Unsubscribe from a folder.

        Args:
            name: Folder name to unsubscribe from

        Returns:
            True if successful

        Raises:
            FolderError: If operation fails
        """
        self._validate_folder_name(name)

        try:
            response = self._conn.unsubscribe(name)

            status = response[0]
            if status not in ("OK", b"OK"):
                error_msg = (
                    response[1][0].decode("utf-8", errors="replace")
                    if response[1]
                    else "Unknown error"
                )
                raise FolderError(f"Failed to unsubscribe from folder: {error_msg}")

            return True

        except FolderError:
            raise
        except Exception as e:
            raise FolderError(f"Failed to unsubscribe from folder: {str(e)}")

    def get_folder_status(self, name: str) -> dict[str, Any]:
        """
        Get status information for a folder.

        Args:
            name: Folder name

        Returns:
            Dictionary containing status information:
            - messages: Total number of messages
            - recent: Number of recent messages
            - unseen: Number of unseen (unread) messages
            - uidvalidity: UID validity value
            - uidnext: Next UID value

        Raises:
            FolderNotFoundError: If folder does not exist
            FolderError: If operation fails
        """
        self._validate_folder_name(name)

        # Status items to retrieve
        status_items = "(MESSAGES RECENT UNSEEN UIDVALIDITY UIDNEXT)"

        try:
            response = self._conn.status(name, status_items)

            status = response[0]
            if status not in ("OK", b"OK"):
                error_msg = (
                    response[1][0].decode("utf-8", errors="replace")
                    if response[1]
                    else "Unknown error"
                )

                if "does not exist" in error_msg.lower():
                    raise FolderNotFoundError(f"Folder '{name}' does not exist")

                raise FolderError(f"Failed to get folder status: {error_msg}")

            # Parse status response
            # Format: b'INBOX (MESSAGES 100 UNSEEN 5 RECENT 0 UIDVALIDITY 1 UIDNEXT 101)'
            return self._parse_status_response(response, name)

        except FolderError:
            raise
        except Exception as e:
            raise FolderError(f"Failed to get folder status: {str(e)}")

    def _parse_status_response(self, response: tuple, folder_name: str) -> dict[str, Any]:
        """
        Parse IMAP STATUS response into dictionary.

        Args:
            response: Tuple from IMAP status command
            folder_name: Folder name (for error messages)

        Returns:
            Dictionary with status values
        """
        if not response or len(response) < 2:
            return {}

        try:
            # Find the status data in response
            data = response[1][0]
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")

            # Extract status values
            # Format: 'INBOX (MESSAGES 100 UNSEEN 5 RECENT 0 UIDVALIDITY 1 UIDNEXT 101)'
            status = {}

            # Parse numeric values
            import re

            patterns = {
                "messages": r"MESSAGES\s+(\d+)",
                "recent": r"RECENT\s+(\d+)",
                "unseen": r"UNSEEN\s+(\d+)",
                "uidvalidity": r"UIDVALIDITY\s+(\d+)",
                "uidnext": r"UIDNEXT\s+(\d+)",
            }

            for key, pattern in patterns.items():
                match = re.search(pattern, data, re.IGNORECASE)
                if match:
                    status[key] = int(match.group(1))

            return status

        except Exception as e:
            raise FolderError(f"Failed to parse status response: {str(e)}")


# Convenience function for simple operations
def list_all_folders(connection) -> list[str]:
    """
    List all folders using connection.

    Args:
        connection: IMAP connection

    Returns:
        List of folder names
    """
    manager = FolderManager(connection)
    return manager.list_folders()


__all__ = [
    "FolderError",
    "FolderNotFoundError",
    "FolderExistsError",
    "InvalidFolderNameError",
    "FolderManager",
    "list_all_folders",
]
