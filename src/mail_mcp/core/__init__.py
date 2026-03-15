"""
IMAP MCP Server - Core Package

提供 IMAP 连接管理和核心操作功能。
"""

from .auth import AuthHandler, IMAPCredentials
from .connection import (
    ConnectionConfig,
    ConnectionPool,
    IMAPConnection,
    PooledConnection,
    imap_connection,
)
from .errors import (
    IMAPAccountLocked,
    # 认证错误
    IMAPAuthError,
    IMAPAuthMethodNotSupported,
    # 连接错误
    IMAPConnectionError,
    IMAPConnectionTimeout,
    IMAPEmailCopyFailed,
    IMAPEmailDeleteFailed,
    IMAPEmailFetchFailed,
    IMAPEmailFlagFailed,
    IMAPEmailMoveFailed,
    # 邮件错误
    IMAPEmailNotFound,
    IMAPEmailParseFailed,
    IMAPError,
    IMAPFolderAlreadyExists,
    IMAPFolderCreateFailed,
    IMAPFolderDeleteFailed,
    # 文件夹错误
    IMAPFolderNotFound,
    IMAPFolderPermissionDenied,
    IMAPFolderRenameFailed,
    IMAPHostUnreachable,
    IMAPInvalidCredentials,
    IMAPInvalidParameterError,
    IMAPNotConnectedError,
    IMAPOperationTimeout,
    # 通用错误
    IMAPProtocolError,
    # 搜索错误
    IMAPSearchError,
    IMAPSearchInvalidCondition,
    IMAPSearchTimeout,
    IMAPSSLError,
)

__all__ = [
    # 连接管理
    "ConnectionConfig",
    "IMAPConnection",
    "imap_connection",
    "ConnectionPool",
    "PooledConnection",
    # 认证
    "AuthHandler",
    "IMAPCredentials",
    # 异常
    "IMAPError",
    # 连接错误 (1xxx)
    "IMAPConnectionError",
    "IMAPConnectionTimeout",
    "IMAPSSLError",
    "IMAPHostUnreachable",
    # 认证错误 (2xxx)
    "IMAPAuthError",
    "IMAPInvalidCredentials",
    "IMAPAuthMethodNotSupported",
    "IMAPAccountLocked",
    # 文件夹错误 (3xxx)
    "IMAPFolderNotFound",
    "IMAPFolderAlreadyExists",
    "IMAPFolderCreateFailed",
    "IMAPFolderDeleteFailed",
    "IMAPFolderRenameFailed",
    "IMAPFolderPermissionDenied",
    # 邮件错误 (4xxx)
    "IMAPEmailNotFound",
    "IMAPEmailFetchFailed",
    "IMAPEmailDeleteFailed",
    "IMAPEmailMoveFailed",
    "IMAPEmailCopyFailed",
    "IMAPEmailFlagFailed",
    "IMAPEmailParseFailed",
    # 搜索错误 (5xxx)
    "IMAPSearchError",
    "IMAPSearchTimeout",
    "IMAPSearchInvalidCondition",
    # 通用错误 (9xxx)
    "IMAPProtocolError",
    "IMAPNotConnectedError",
    "IMAPInvalidParameterError",
    "IMAPOperationTimeout",
]
