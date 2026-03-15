"""
IMAP MCP Server.

A Python library for IMAP email operations with MCP (Model Context Protocol) support.
"""

from mail_mcp.config import IMAPConfig
from mail_mcp.client import IMAPClient, get_imap_client, reset_imap_client, IMAP_OK

from mail_mcp.core import (
    ConnectionConfig,
    IMAPConnection,
    imap_connection,
    ConnectionPool,
    PooledConnection,
    AuthHandler,
    IMAPCredentials,
    # Core errors
    IMAPError,
    IMAPConnectionError,
    IMAPConnectionTimeout,
    IMAPSSLError,
    IMAPHostUnreachable,
    IMAPAuthError,
    IMAPInvalidCredentials,
    IMAPAuthMethodNotSupported,
    IMAPAccountLocked,
    IMAPFolderNotFound,
    IMAPFolderAlreadyExists,
    IMAPFolderCreateFailed,
    IMAPFolderDeleteFailed,
    IMAPFolderRenameFailed,
    IMAPFolderPermissionDenied,
    IMAPEmailNotFound,
    IMAPEmailFetchFailed,
    IMAPEmailDeleteFailed,
    IMAPEmailMoveFailed,
    IMAPEmailCopyFailed,
    IMAPEmailFlagFailed,
    IMAPEmailParseFailed,
    IMAPSearchError,
    IMAPSearchTimeout,
    IMAPSearchInvalidCondition,
    IMAPProtocolError,
    IMAPNotConnectedError,
    IMAPInvalidParameterError,
    IMAPOperationTimeout,
)

from mail_mcp.folders import (
    FolderManager,
    list_all_folders,
)

from mail_mcp.operations import (
    EmailSearch,
    search_emails,
    EmailFetch,
    get_email,
    EmailFlags,
    mark_read,
    mark_unread,
    mark_flagged,
    unmark_flagged,
    EmailMove,
    move_email,
    copy_email,
    delete_email,
)

# Aliases for backwards compatibility
FolderError = IMAPFolderCreateFailed
FolderNotFoundError = IMAPFolderNotFound
FolderExistsError = IMAPFolderAlreadyExists
EmailSearchError = IMAPSearchError
EmailFetchError = IMAPEmailFetchFailed
EmailFlagsError = IMAPEmailFlagFailed
EmailMoveError = IMAPEmailMoveFailed

__version__ = '0.1.0'

__all__ = [
    # Config and Client (new)
    'IMAPConfig',
    'IMAPClient',
    'get_imap_client',
    'reset_imap_client',
    'IMAP_OK',
    
    # Core
    'ConnectionConfig',
    'IMAPConnection',
    'imap_connection',
    'ConnectionPool',
    'PooledConnection',
    'AuthHandler',
    'IMAPCredentials',
    
    # Folder management
    'FolderManager',
    'list_all_folders',
    'FolderError',
    'FolderNotFoundError',
    'FolderExistsError',
    
    # Email operations
    'EmailSearch',
    'search_emails',
    'EmailSearchError',
    
    'EmailFetch',
    'get_email',
    'EmailFetchError',
    
    'EmailFlags',
    'mark_read',
    'mark_unread',
    'mark_flagged',
    'unmark_flagged',
    'EmailFlagsError',
    
    'EmailMove',
    'move_email',
    'copy_email',
    'delete_email',
    'EmailMoveError',
    
    # Core errors (re-exported)
    'IMAPError',
    'IMAPConnectionError',
    'IMAPConnectionTimeout',
    'IMAPSSLError',
    'IMAPHostUnreachable',
    'IMAPAuthError',
    'IMAPInvalidCredentials',
    'IMAPAuthMethodNotSupported',
    'IMAPAccountLocked',
    'IMAPFolderNotFound',
    'IMAPFolderAlreadyExists',
    'IMAPFolderCreateFailed',
    'IMAPFolderDeleteFailed',
    'IMAPFolderRenameFailed',
    'IMAPFolderPermissionDenied',
    'IMAPEmailNotFound',
    'IMAPEmailFetchFailed',
    'IMAPEmailDeleteFailed',
    'IMAPEmailMoveFailed',
    'IMAPEmailCopyFailed',
    'IMAPEmailFlagFailed',
    'IMAPEmailParseFailed',
    'IMAPSearchError',
    'IMAPSearchTimeout',
    'IMAPSearchInvalidCondition',
    'IMAPProtocolError',
    'IMAPNotConnectedError',
    'IMAPInvalidParameterError',
    'IMAPOperationTimeout',
]