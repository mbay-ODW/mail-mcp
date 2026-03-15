"""
IMAP MCP Server.

A Python library for IMAP email operations with MCP (Model Context Protocol) support.
"""

from mail_mcp.client import IMAP_OK, IMAPClient, get_imap_client, reset_imap_client
from mail_mcp.config import IMAPConfig
from mail_mcp.core import (
    AuthHandler,
    ConnectionConfig,
    ConnectionPool,
    IMAPAccountLocked,
    IMAPAuthError,
    IMAPAuthMethodNotSupported,
    IMAPConnection,
    IMAPConnectionError,
    IMAPConnectionTimeout,
    IMAPCredentials,
    IMAPEmailCopyFailed,
    IMAPEmailDeleteFailed,
    IMAPEmailFetchFailed,
    IMAPEmailFlagFailed,
    IMAPEmailMoveFailed,
    IMAPEmailNotFound,
    IMAPEmailParseFailed,
    # Core errors
    IMAPError,
    IMAPFolderAlreadyExists,
    IMAPFolderCreateFailed,
    IMAPFolderDeleteFailed,
    IMAPFolderNotFound,
    IMAPFolderPermissionDenied,
    IMAPFolderRenameFailed,
    IMAPHostUnreachable,
    IMAPInvalidCredentials,
    IMAPInvalidParameterError,
    IMAPNotConnectedError,
    IMAPOperationTimeout,
    IMAPProtocolError,
    IMAPSearchError,
    IMAPSearchInvalidCondition,
    IMAPSearchTimeout,
    IMAPSSLError,
    PooledConnection,
    imap_connection,
)
from mail_mcp.folders import (
    FolderManager,
    list_all_folders,
)
from mail_mcp.operations import (
    EmailFetch,
    EmailFlags,
    EmailMove,
    EmailSearch,
    copy_email,
    delete_email,
    get_email,
    mark_flagged,
    mark_read,
    mark_unread,
    move_email,
    search_emails,
    unmark_flagged,
)

# Aliases for backwards compatibility
FolderError = IMAPFolderCreateFailed
FolderNotFoundError = IMAPFolderNotFound
FolderExistsError = IMAPFolderAlreadyExists
EmailSearchError = IMAPSearchError
EmailFetchError = IMAPEmailFetchFailed
EmailFlagsError = IMAPEmailFlagFailed
EmailMoveError = IMAPEmailMoveFailed

__version__ = "0.1.0"

__all__ = [
    # Config and Client (new)
    "IMAPConfig",
    "IMAPClient",
    "get_imap_client",
    "reset_imap_client",
    "IMAP_OK",
    # Core
    "ConnectionConfig",
    "IMAPConnection",
    "imap_connection",
    "ConnectionPool",
    "PooledConnection",
    "AuthHandler",
    "IMAPCredentials",
    # Folder management
    "FolderManager",
    "list_all_folders",
    "FolderError",
    "FolderNotFoundError",
    "FolderExistsError",
    # Email operations
    "EmailSearch",
    "search_emails",
    "EmailSearchError",
    "EmailFetch",
    "get_email",
    "EmailFetchError",
    "EmailFlags",
    "mark_read",
    "mark_unread",
    "mark_flagged",
    "unmark_flagged",
    "EmailFlagsError",
    "EmailMove",
    "move_email",
    "copy_email",
    "delete_email",
    "EmailMoveError",
    # Core errors (re-exported)
    "IMAPError",
    "IMAPConnectionError",
    "IMAPConnectionTimeout",
    "IMAPSSLError",
    "IMAPHostUnreachable",
    "IMAPAuthError",
    "IMAPInvalidCredentials",
    "IMAPAuthMethodNotSupported",
    "IMAPAccountLocked",
    "IMAPFolderNotFound",
    "IMAPFolderAlreadyExists",
    "IMAPFolderCreateFailed",
    "IMAPFolderDeleteFailed",
    "IMAPFolderRenameFailed",
    "IMAPFolderPermissionDenied",
    "IMAPEmailNotFound",
    "IMAPEmailFetchFailed",
    "IMAPEmailDeleteFailed",
    "IMAPEmailMoveFailed",
    "IMAPEmailCopyFailed",
    "IMAPEmailFlagFailed",
    "IMAPEmailParseFailed",
    "IMAPSearchError",
    "IMAPSearchTimeout",
    "IMAPSearchInvalidCondition",
    "IMAPProtocolError",
    "IMAPNotConnectedError",
    "IMAPInvalidParameterError",
    "IMAPOperationTimeout",
]
