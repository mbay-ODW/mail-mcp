"""
Email flag operations for IMAP MCP server.

Provides functionality to manage email flags:
- Mark as read/unread
- Mark as flagged/starred
- Mark as answered
- Mark as deleted
- Custom flag management
"""

from typing import List, Union, Set


class EmailFlagsError(Exception):
    """Base exception for email flag operations."""
    pass


class EmailFlags:
    """
    Handles email flag operations.
    
    Provides methods to read and modify email flags
    using IMAP STORE command.
    
    Attributes:
        _conn: IMAP connection instance
    """
    
    # Standard IMAP flags
    FLAG_SEEN = '\\Seen'
    FLAG_ANSWERED = '\\Answered'
    FLAG_FLAGGED = '\\Flagged'
    FLAG_DELETED = '\\Deleted'
    FLAG_DRAFT = '\\Draft'
    FLAG_RECENT = '\\Recent'
    
    # All standard flags
    STANDARD_FLAGS = [
        FLAG_SEEN,
        FLAG_ANSWERED,
        FLAG_FLAGGED,
        FLAG_DELETED,
        FLAG_DRAFT,
        FLAG_RECENT,
    ]
    
    def __init__(self, connection) -> None:
        """
        Initialize EmailFlags with an IMAP connection.
        
        Args:
            connection: An active IMAP connection
        """
        self._conn = connection
    
    def _validate_uids(self, uids: Union[int, List[int]]) -> List[str]:
        """
        Validate and format UIDs for IMAP commands.
        
        Args:
            uids: Single UID or list of UIDs
            
        Returns:
            Formatted UID string for IMAP
            
        Raises:
            EmailFlagsError: If UIDs are invalid
        """
        if isinstance(uids, int):
            if uids < 1:
                raise EmailFlagsError("UID must be positive")
            return str(uids)
        
        if isinstance(uids, (list, tuple)):
            if not uids:
                raise EmailFlagsError("UID list cannot be empty")
            
            valid_uids = [str(uid) for uid in uids if isinstance(uid, int) and uid > 0]
            if not valid_uids:
                raise EmailFlagsError("No valid UIDs provided")
            
            return ','.join(valid_uids)
        
        raise EmailFlagsError("UIDs must be integer or list of integers")
    
    def _select_folder(self, folder: str) -> None:
        """
        Select a folder for flag operations.
        
        Args:
            folder: Folder name
            
        Raises:
            EmailFlagsError: If selection fails
        """
        response = self._conn.select(folder)
        
        # IMAP 返回 'OK' (str), 不是 b'OK' (bytes)
        if response[0] != 'OK':
            error_msg = response[1][0].decode('utf-8', errors='replace') if response[1] else 'Unknown error'
            raise EmailFlagsError(f"Failed to select folder '{folder}': {error_msg}")
    
    def _store_flags(
        self,
        folder: str,
        uids: Union[int, List[int]],
        command: str,
        flags: Union[str, List[str]]
    ) -> bool:
        """
        Execute STORE command to modify flags.
        
        Args:
            folder: Folder name
            uids: Email UIDs
            command: STORE command (+FLAGS, -FLAGS, FLAGS)
            flags: Flags to set/add/remove
            
        Returns:
            True if successful
            
        Raises:
            EmailFlagsError: If operation fails
        """
        if not folder:
            raise EmailFlagsError("Folder name is required")
        
        self._select_folder(folder)
        
        uid_string = self._validate_uids(uids)
        
        # Format flags
        if isinstance(flags, list):
            flags_str = '(' + ' '.join(flags) + ')'
        else:
            flags_str = f'({flags})'
        
        # Build command: uid store UID (FLAGS)
        store_command = f'{command} {flags_str}'
        
        try:
            response = self._conn.uid('STORE', uid_string, store_command)
            
            status = response[0]
            if status not in ('OK', b'OK') and not isinstance(status, int):
                error_msg = response[1][0].decode('utf-8', errors='replace') if response[1] else 'Unknown error'
                raise EmailFlagsError(f"Failed to update flags: {error_msg}")
            
            return True
            
        except EmailFlagsError:
            raise
        except Exception as e:
            raise EmailFlagsError(f"Failed to update flags: {str(e)}")
    
    def mark_read(
        self,
        folder: str,
        uids: Union[int, List[int]]
    ) -> bool:
        """
        Mark emails as read (seen).
        
        Args:
            folder: Folder containing the emails
            uids: Email UID or list of UIDs
            
        Returns:
            True if successful
            
        Raises:
            EmailFlagsError: If operation fails
            
        Example:
            >>> flags = EmailFlags(conn)
            >>> flags.mark_read('INBOX', [1, 2, 3])
            True
        """
        return self._store_flags(folder, uids, '+FLAGS', self.FLAG_SEEN)
    
    def mark_unread(
        self,
        folder: str,
        uids: Union[int, List[int]]
    ) -> bool:
        """
        Mark emails as unread (remove \\Seen flag).
        
        Args:
            folder: Folder containing the emails
            uids: Email UID or list of UIDs
            
        Returns:
            True if successful
            
        Raises:
            EmailFlagsError: If operation fails
        """
        return self._store_flags(folder, uids, '-FLAGS', self.FLAG_SEEN)
    
    def mark_flagged(
        self,
        folder: str,
        uids: Union[int, List[int]]
    ) -> bool:
        """
        Mark emails as flagged/starred.
        
        Args:
            folder: Folder containing the emails
            uids: Email UID or list of UIDs
            
        Returns:
            True if successful
            
        Raises:
            EmailFlagsError: If operation fails
        """
        return self._store_flags(folder, uids, '+FLAGS', self.FLAG_FLAGGED)
    
    def unmark_flagged(
        self,
        folder: str,
        uids: Union[int, List[int]]
    ) -> bool:
        """
        Remove flagged/starred status from emails.
        
        Args:
            folder: Folder containing the emails
            uids: Email UID or list of UIDs
            
        Returns:
            True if successful
            
        Raises:
            EmailFlagsError: If operation fails
        """
        return self._store_flags(folder, uids, '-FLAGS', self.FLAG_FLAGGED)
    
    def mark_answered(
        self,
        folder: str,
        uids: Union[int, List[int]]
    ) -> bool:
        """
        Mark emails as answered.
        
        Args:
            folder: Folder containing the emails
            uids: Email UID or list of UIDs
            
        Returns:
            True if successful
            
        Raises:
            EmailFlagsError: If operation fails
        """
        return self._store_flags(folder, uids, '+FLAGS', self.FLAG_ANSWERED)
    
    def unmark_answered(
        self,
        folder: str,
        uids: Union[int, List[int]]
    ) -> bool:
        """
        Remove answered status from emails.
        
        Args:
            folder: Folder containing the emails
            uids: Email UID or list of UIDs
            
        Returns:
            True if successful
            
        Raises:
            EmailFlagsError: If operation fails
        """
        return self._store_flags(folder, uids, '-FLAGS', self.FLAG_ANSWERED)
    
    def mark_deleted(
        self,
        folder: str,
        uids: Union[int, List[int]]
    ) -> bool:
        """
        Mark emails for deletion (\\Deleted flag).
        
        Note: Emails are not permanently deleted until expunge is called.
        
        Args:
            folder: Folder containing the emails
            uids: Email UID or list of UIDs
            
        Returns:
            True if successful
            
        Raises:
            EmailFlagsError: If operation fails
        """
        return self._store_flags(folder, uids, '+FLAGS', self.FLAG_DELETED)
    
    def unmark_deleted(
        self,
        folder: str,
        uids: Union[int, List[int]]
    ) -> bool:
        """
        Remove deleted status from emails.
        
        Args:
            folder: Folder containing the emails
            uids: Email UID or list of UIDs
            
        Returns:
            True if successful
            
        Raises:
            EmailFlagsError: If operation fails
        """
        return self._store_flags(folder, uids, '-FLAGS', self.FLAG_DELETED)
    
    def add_custom_flag(
        self,
        folder: str,
        uids: Union[int, List[int]],
        flag: str
    ) -> bool:
        """
        Add a custom flag to emails.
        
        Args:
            folder: Folder containing the emails
            uids: Email UID or list of UIDs
            flag: Custom flag name (e.g., '$Label1', '$Important')
            
        Returns:
            True if successful
            
        Raises:
            EmailFlagsError: If operation fails
        """
        if not flag or not flag.startswith('$'):
            raise EmailFlagsError("Custom flag must start with '$'")
        
        return self._store_flags(folder, uids, '+FLAGS', flag)
    
    def remove_custom_flag(
        self,
        folder: str,
        uids: Union[int, List[int]],
        flag: str
    ) -> bool:
        """
        Remove a custom flag from emails.
        
        Args:
            folder: Folder containing the emails
            uids: Email UID or list of UIDs
            flag: Custom flag name
            
        Returns:
            True if successful
            
        Raises:
            EmailFlagsError: If operation fails
        """
        return self._store_flags(folder, uids, '-FLAGS', flag)
    
    def set_flags(
        self,
        folder: str,
        uids: Union[int, List[int]],
        flags: Union[str, List[str]]
    ) -> bool:
        """
        Set flags (replace all flags).
        
        This replaces all existing flags with the specified flags.
        
        Args:
            folder: Folder containing the emails
            uids: Email UID or list of UIDs
            flags: Flag or list of flags to set
            
        Returns:
            True if successful
            
        Raises:
            EmailFlagsError: If operation fails
        """
        return self._store_flags(folder, uids, 'FLAGS', flags)
    
    def get_flags(
        self,
        folder: str,
        uid: int
    ) -> Set[str]:
        """
        Get current flags for an email.
        
        Args:
            folder: Folder containing the email
            uid: Email UID
            
        Returns:
            Set of flag strings
            
        Raises:
            EmailFlagsError: If operation fails
        """
        if not folder:
            raise EmailFlagsError("Folder name is required")
        
        self._select_folder(folder)
        
        try:
            response = self._conn.uid('FETCH', str(uid), '(FLAGS)')
            
            status = response[0]
            if status not in ('OK', b'OK') and not isinstance(status, int):
                error_msg = response[1][0].decode('utf-8', errors='replace') if response[1] else 'Unknown error'
                raise EmailFlagsError(f"Failed to get flags: {error_msg}")
            
            return self._parse_flags_response(response)
            
        except EmailFlagsError:
            raise
        except Exception as e:
            raise EmailFlagsError(f"Failed to get flags: {str(e)}")
    
    def _parse_flags_response(self, response: tuple) -> Set[str]:
        """
        Parse IMAP FETCH FLAGS response.
        
        Args:
            response: Tuple from IMAP fetch command
            
        Returns:
            Set of flag strings
        """
        flags = set()
        
        if not response or len(response) < 2:
            return flags
        
        # Look for FLAGS in response
        for item in response[1]:
            if isinstance(item, bytes):
                data = item.decode('utf-8', errors='replace')
            elif isinstance(item, str):
                data = item
            else:
                continue
            
            # Find FLAGS section
            if 'FLAGS' in data:
                import re
                match = re.search(r'FLAGS\s+\(([^)]*)\)', data, re.IGNORECASE)
                if match:
                    flag_str = match.group(1)
                    if flag_str:
                        for flag in flag_str.split():
                            flags.add(flag.strip())
        
        return flags


# Convenience functions
def mark_read(connection, folder: str, uids: Union[int, List[int]]) -> bool:
    """Mark emails as read."""
    flags = EmailFlags(connection)
    return flags.mark_read(folder, uids)


def mark_unread(connection, folder: str, uids: Union[int, List[int]]) -> bool:
    """Mark emails as unread."""
    flags = EmailFlags(connection)
    return flags.mark_unread(folder, uids)


def mark_flagged(connection, folder: str, uids: Union[int, List[int]]) -> bool:
    """Mark emails as flagged."""
    flags = EmailFlags(connection)
    return flags.mark_flagged(folder, uids)


def unmark_flagged(connection, folder: str, uids: Union[int, List[int]]) -> bool:
    """Unmark flagged emails."""
    flags = EmailFlags(connection)
    return flags.unmark_flagged(folder, uids)


__all__ = [
    'EmailFlagsError',
    'EmailFlags',
    'mark_read',
    'mark_unread',
    'mark_flagged',
    'unmark_flagged',
]