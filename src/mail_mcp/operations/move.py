"""
Email move, copy, and delete operations for IMAP MCP server.

Provides functionality to:
- Move emails between folders
- Copy emails to another folder
- Delete emails (mark as deleted + expunge)
- Upload/send emails (APPEND)
"""



class EmailMoveError(Exception):
    """Base exception for email move/copy operations."""

    pass


class EmailMove:
    """
    Handles email move, copy, and delete operations.

    Provides methods for moving and copying emails between
    folders, as well as deleting emails.

    Attributes:
        _conn: IMAP connection instance
    """

    def __init__(self, connection) -> None:
        """
        Initialize EmailMove with an IMAP connection.

        Args:
            connection: An active IMAP connection
        """
        self._conn = connection

    def _validate_uids(self, uids: int | list[int]) -> str:
        """
        Validate and format UIDs for IMAP commands.

        Args:
            uids: Single UID or list of UIDs

        Returns:
            Formatted UID string for IMAP

        Raises:
            EmailMoveError: If UIDs are invalid
        """
        if isinstance(uids, int):
            if uids < 1:
                raise EmailMoveError("UID must be positive")
            return str(uids)

        if isinstance(uids, (list, tuple)):
            if not uids:
                raise EmailMoveError("UID list cannot be empty")

            valid_uids = [str(uid) for uid in uids if isinstance(uid, int) and uid > 0]
            if not valid_uids:
                raise EmailMoveError("No valid UIDs provided")

            return ",".join(valid_uids)

        raise EmailMoveError("UIDs must be integer or list of integers")

    def _select_folder(self, folder: str) -> None:
        """
        Select a folder for operations.

        Args:
            folder: Folder name

        Raises:
            EmailMoveError: If selection fails
        """
        response = self._conn.select(folder)

        # 阿里云邮箱返回邮件数量而不是 'OK'，需要检查数据是否存在
        status = response[0]
        if status not in ("OK", b"OK") and not isinstance(status, int):
            error_msg = (
                response[1][0].decode("utf-8", errors="replace") if response[1] else "Unknown error"
            )
            raise EmailMoveError(f"Failed to select folder '{folder}': {error_msg}")

    def move_email(
        self, source_folder: str, uids: int | list[int], destination_folder: str
    ) -> bool:
        """
        Move emails from one folder to another.

        Uses IMAP MOVE command (RFC 6851) if available,
        otherwise falls back to copy + delete.

        Args:
            source_folder: Source folder containing the emails
            uids: Email UID or list of UIDs to move
            destination_folder: Destination folder

        Returns:
            True if successful

        Raises:
            EmailMoveError: If operation fails

        Example:
            >>> move = EmailMove(conn)
            >>> move.move_email('INBOX', [1, 2, 3], 'INBOX/Archive')
            True
        """
        if not source_folder:
            raise EmailMoveError("Source folder is required")

        if not destination_folder:
            raise EmailMoveError("Destination folder is required")

        if source_folder == destination_folder:
            raise EmailMoveError("Source and destination folders must be different")

        # Select source folder to get current state
        self._select_folder(source_folder)

        uid_string = self._validate_uids(uids)

        try:
            # Try MOVE command first (IMAP4rev2)
            response = self._conn.uid("MOVE", uid_string, destination_folder)

            if response[0] == b"OK":
                return True

            # If MOVE not supported, fall back to COPY + STORE +DELETED
            return self._move_fallback(source_folder, uids, destination_folder)

        except Exception as e:
            # Try fallback method
            try:
                return self._move_fallback(source_folder, uids, destination_folder)
            except EmailMoveError:
                raise EmailMoveError(f"Failed to move email: {str(e)}")

    def _move_fallback(
        self, source_folder: str, uids: int | list[int], destination_folder: str
    ) -> bool:
        """
        Fallback move using COPY + DELETE.

        Used when MOVE command is not supported.

        Args:
            source_folder: Source folder
            uids: Email UIDs
            destination_folder: Destination folder

        Returns:
            True if successful

        Raises:
            EmailMoveError: If operation fails
        """
        # Copy to destination
        self.copy_email(source_folder, uids, destination_folder)

        # Mark original as deleted
        from mail_mcp.operations.flags import EmailFlags

        flags = EmailFlags(self._conn)
        flags.mark_deleted(source_folder, uids)

        # Expunge to permanently delete
        self.expunge(source_folder)

        return True

    def copy_email(
        self, source_folder: str, uids: int | list[int], destination_folder: str
    ) -> bool:
        """
        Copy emails to another folder.

        Unlike move, this preserves the original emails.

        Args:
            source_folder: Source folder containing the emails
            uids: Email UID or list of UIDs to copy
            destination_folder: Destination folder

        Returns:
            True if successful

        Raises:
            EmailMoveError: If operation fails

        Example:
            >>> move = EmailMove(conn)
            >>> move.copy_email('INBOX', [1, 2], 'INBOX/Backup')
            True
        """
        if not source_folder:
            raise EmailMoveError("Source folder is required")

        if not destination_folder:
            raise EmailMoveError("Destination folder is required")

        # Select source folder
        self._select_folder(source_folder)

        uid_string = self._validate_uids(uids)

        try:
            response = self._conn.uid("COPY", uid_string, destination_folder)

            status = response[0]
            if status not in ("OK", b"OK") and not isinstance(status, int):
                error_msg = (
                    response[1][0].decode("utf-8", errors="replace")
                    if response[1] and response[1][0]
                    else "Unknown error"
                )

                if "does not exist" in error_msg.lower():
                    raise EmailMoveError(
                        f"Destination folder '{destination_folder}' does not exist"
                    )

                raise EmailMoveError(f"Failed to copy email: {error_msg}")

            return True

        except EmailMoveError:
            raise
        except Exception as e:
            raise EmailMoveError(f"Failed to copy email: {str(e)}")

    def delete_email(
        self, folder: str, uids: int | list[int], expunge_immediately: bool = False
    ) -> bool:
        """
        Delete emails from a folder.

        This marks emails with \\Deleted flag. If expunge_immediately
        is True, permanently deletes them. Otherwise, they will be
        deleted when the folder is expunged or closed.

        Args:
            folder: Folder containing the emails
            uids: Email UID or list of UIDs to delete
            expunge_immediately: If True, permanently delete now

        Returns:
            True if successful

        Raises:
            EmailMoveError: If operation fails

        Example:
            >>> move = EmailMove(conn)
            >>> move.delete_email('INBOX', [1, 2, 3])
            True
        """
        if not folder:
            raise EmailMoveError("Folder name is required")

        # Select folder
        self._select_folder(folder)

        uid_string = self._validate_uids(uids)

        try:
            # Add \\Deleted flag
            response = self._conn.uid("STORE", uid_string, "+FLAGS (\\Deleted)")

            if response[0] != b"OK":
                error_msg = (
                    response[1][0].decode("utf-8", errors="replace")
                    if response[1]
                    else "Unknown error"
                )
                raise EmailMoveError(f"Failed to delete email: {error_msg}")

            # Expunge if requested
            if expunge_immediately:
                self.expunge(folder)

            return True

        except EmailMoveError:
            raise
        except Exception as e:
            raise EmailMoveError(f"Failed to delete email: {str(e)}")

    def expunge(self, folder: str) -> bool:
        """
        Permanently delete all messages marked as \\Deleted.

        Args:
            folder: Folder to expunge

        Returns:
            True if successful

        Raises:
            EmailMoveError: If operation fails

        Example:
            >>> move = EmailMove(conn)
            >>> move.expunge('INBOX')
            True
        """
        if not folder:
            raise EmailMoveError("Folder name is required")

        # Select folder
        self._select_folder(folder)

        try:
            response = self._conn.expunge()

            if response[0] != b"OK":
                error_msg = (
                    response[1][0].decode("utf-8", errors="replace")
                    if response[1]
                    else "Unknown error"
                )
                raise EmailMoveError(f"Failed to expunge folder: {error_msg}")

            return True

        except EmailMoveError:
            raise
        except Exception as e:
            raise EmailMoveError(f"Failed to expunge folder: {str(e)}")

    def append_email(
        self,
        destination_folder: str,
        email_content: str | bytes,
        flags: list[str] | None = None,
        date_time: str | None = None,
    ) -> bool:
        """
        Append (upload) an email to a folder.

        This is used for saving draft emails or moving emails
        from external sources into the mailbox.

        Args:
            destination_folder: Destination folder
            email_content: Raw email content (RFC 2822 format)
            flags: Optional list of flags (e.g., ['\\Seen', '\\Draft'])
            date_time: Optional date/time (format: 'DD-Mon-YYYY HH:MM:SS +ZZZZ')

        Returns:
            True if successful

        Raises:
            EmailMoveError: If operation fails

        Example:
            >>> move = EmailMove(conn)
            >>> move.append_email('INBOX/Drafts', email_raw)
            True
        """
        if not destination_folder:
            raise EmailMoveError("Destination folder is required")

        if not email_content:
            raise EmailMoveError("Email content is required")

        # Encode content if string
        if isinstance(email_content, str):
            email_content = email_content.encode("utf-8")

        # Build APPEND command
        append_args = [destination_folder]

        # Add flags if provided
        if flags:
            flag_str = "(" + " ".join(flags) + ")"
            append_args.append(flag_str)

        # Add date/time if provided
        if date_time:
            append_args.append(date_time)

        # Add message content (as literal)
        append_args.append(email_content)

        try:
            response = self._conn.append(*append_args)

            if response[0] != b"OK":
                error_msg = (
                    response[1][0].decode("utf-8", errors="replace")
                    if response[1]
                    else "Unknown error"
                )
                raise EmailMoveError(f"Failed to append email: {error_msg}")

            return True

        except EmailMoveError:
            raise
        except Exception as e:
            raise EmailMoveError(f"Failed to append email: {str(e)}")

    def archive_email(
        self, folder: str, uids: int | list[int], archive_folder: str = "Archive"
    ) -> bool:
        """
        Convenience method to archive emails.

        Moves emails to an Archive folder (default name: 'Archive').

        Args:
            folder: Source folder
            uids: Email UIDs to archive
            archive_folder: Archive folder name

        Returns:
            True if successful
        """
        return self.move_email(folder, uids, archive_folder)

    def mark_and_expunge(self, folder: str, uids: int | list[int]) -> bool:
        """
        Mark emails as deleted and expunge in one operation.

        Convenience method for immediate permanent deletion.

        Args:
            folder: Folder containing the emails
            uids: Email UIDs to delete

        Returns:
            True if successful
        """
        return self.delete_email(folder, uids, expunge_immediately=True)


# Convenience functions
def move_email(
    connection, source_folder: str, uids: int | list[int], dest_folder: str
) -> bool:
    """Move emails between folders."""
    mover = EmailMove(connection)
    return mover.move_email(source_folder, uids, dest_folder)


def copy_email(
    connection, source_folder: str, uids: int | list[int], dest_folder: str
) -> bool:
    """Copy emails to another folder."""
    mover = EmailMove(connection)
    return mover.copy_email(source_folder, uids, dest_folder)


def delete_email(connection, folder: str, uids: int | list[int]) -> bool:
    """Delete emails."""
    mover = EmailMove(connection)
    return mover.delete_email(folder, uids)


__all__ = [
    "EmailMoveError",
    "EmailMove",
    "move_email",
    "copy_email",
    "delete_email",
]
