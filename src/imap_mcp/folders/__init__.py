"""
Folders module for IMAP MCP server.

Provides folder management operations including:
- Listing folders
- Creating, deleting, and renaming folders
- Subscribing/unsubscribing to folders
- Getting folder status
"""

from imap_mcp.folders.manager import (
    FolderManager,
    list_all_folders,
)

# Re-export from core for backwards compatibility
from imap_mcp.core import (
    IMAPFolderNotFound,
    IMAPFolderAlreadyExists,
    IMAPFolderCreateFailed,
    IMAPFolderDeleteFailed,
    IMAPFolderRenameFailed,
)

# Aliases
FolderError = IMAPFolderCreateFailed
FolderNotFoundError = IMAPFolderNotFound
FolderExistsError = IMAPFolderAlreadyExists
InvalidFolderNameError = IMAPInvalidParameterError = None  # Will use core

__all__ = [
    'FolderError',
    'FolderNotFoundError',
    'FolderExistsError',
    'InvalidFolderNameError',
    'FolderManager',
    'list_all_folders',
    # Core errors (re-exported)
    'IMAPFolderNotFound',
    'IMAPFolderAlreadyExists',
    'IMAPFolderCreateFailed',
    'IMAPFolderDeleteFailed',
    'IMAPFolderRenameFailed',
]