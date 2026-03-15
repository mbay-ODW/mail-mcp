"""
Operations module for IMAP MCP server.

Provides email operations including:
- Search: Email search with various criteria
- Fetch: Email retrieval (headers, body, attachments)
- Flags: Email flag management (read, flagged, etc.)
- Move: Move, copy, delete, and append operations
"""

from mail_mcp.operations.search import (
    EmailSearch,
    search_emails,
)

from mail_mcp.operations.fetch import (
    EmailFetch,
    get_email,
)

from mail_mcp.operations.flags import (
    EmailFlags,
    mark_read,
    mark_unread,
    mark_flagged,
    unmark_flagged,
)

from mail_mcp.operations.move import (
    EmailMove,
    move_email,
    copy_email,
    delete_email,
)

# Re-export error classes from core
from mail_mcp.core import (
    IMAPSearchError,
    IMAPSearchTimeout,
    IMAPSearchInvalidCondition,
    IMAPEmailNotFound,
    IMAPEmailFetchFailed,
    IMAPEmailDeleteFailed,
    IMAPEmailMoveFailed,
    IMAPEmailCopyFailed,
    IMAPEmailFlagFailed,
    IMAPEmailParseFailed,
    IMAPInvalidParameterError,
)

# Backwards compatibility aliases
EmailSearchError = IMAPSearchError
EmailFetchError = IMAPEmailFetchError = IMAPEmailFetchFailed
EmailFlagsError = IMAPEmailFlagFailed
EmailMoveError = IMAPEmailMoveFailed

__all__ = [
    # Search
    'EmailSearchError',
    'IMAPSearchError',
    'IMAPSearchTimeout',
    'IMAPSearchInvalidCondition',
    'EmailSearch',
    'search_emails',
    
    # Fetch
    'EmailFetchError',
    'IMAPEmailNotFound',
    'IMAPEmailFetchFailed',
    'IMAPEmailParseFailed',
    'EmailFetch',
    'get_email',
    
    # Flags
    'EmailFlagsError',
    'IMAPEmailFlagFailed',
    'EmailFlags',
    'mark_read',
    'mark_unread',
    'mark_flagged',
    'unmark_flagged',
    
    # Move
    'EmailMoveError',
    'IMAPEmailMoveFailed',
    'IMAPEmailCopyFailed',
    'IMAPEmailDeleteFailed',
    'EmailMove',
    'move_email',
    'copy_email',
    'delete_email',
    
    # Common
    'IMAPInvalidParameterError',
]