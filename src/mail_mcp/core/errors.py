"""
错误定义模块

定义 IMAP 操作相关的自定义异常。
"""


class IMAPError(Exception):
    """IMAP 操作基础异常"""

    def __init__(
        self,
        message: str,
        error_code: str = "9002",
        details: dict | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "error": self.message,
            "error_code": self.error_code,
            "details": self.details,
        }


# ========== 连接相关错误 (1xxx) ==========


class IMAPConnectionError(IMAPError):
    """IMAP 连接失败"""

    def __init__(self, message: str = "Failed to connect to IMAP server", **kwargs):
        super().__init__(message, "1001", kwargs)


class IMAPConnectionTimeout(IMAPError):
    """IMAP 连接超时"""

    def __init__(self, message: str = "Connection to IMAP server timed out", **kwargs):
        super().__init__(message, "1002", kwargs)


class IMAPSSLError(IMAPError):
    """SSL/TLS 错误"""

    def __init__(self, message: str = "SSL/TLS error occurred", **kwargs):
        super().__init__(message, "1003", kwargs)


class IMAPHostUnreachable(IMAPError):
    """主机不可达"""

    def __init__(self, message: str = "IMAP host is unreachable", **kwargs):
        super().__init__(message, "1004", kwargs)


# ========== 认证相关错误 (2xxx) ==========


class IMAPAuthError(IMAPError):
    """认证失败"""

    def __init__(self, message: str = "IMAP authentication failed", **kwargs):
        super().__init__(message, "2001", kwargs)


class IMAPInvalidCredentials(IMAPError):
    """无效凭证"""

    def __init__(self, message: str = "Invalid username or password", **kwargs):
        super().__init__(message, "2002", kwargs)


class IMAPAuthMethodNotSupported(IMAPError):
    """认证方法不支持"""

    def __init__(self, message: str = "Authentication method not supported", **kwargs):
        super().__init__(message, "2003", kwargs)


class IMAPAccountLocked(IMAPError):
    """账户被锁定"""

    def __init__(self, message: str = "IMAP account is locked", **kwargs):
        super().__init__(message, "2004", kwargs)


# ========== 文件夹操作错误 (3xxx) ==========


class IMAPFolderNotFound(IMAPError):
    """文件夹不存在"""

    def __init__(self, folder: str, **kwargs):
        super().__init__(f"Folder not found: {folder}", "3001", {**kwargs, "folder": folder})


class IMAPFolderAlreadyExists(IMAPError):
    """文件夹已存在"""

    def __init__(self, folder: str, **kwargs):
        super().__init__(f"Folder already exists: {folder}", "3002", {**kwargs, "folder": folder})


class IMAPFolderCreateFailed(IMAPError):
    """文件夹创建失败"""

    def __init__(self, folder: str, **kwargs):
        super().__init__(
            f"Failed to create folder: {folder}",
            "3003",
            {**kwargs, "folder": folder},
        )


class IMAPFolderDeleteFailed(IMAPError):
    """文件夹删除失败"""

    def __init__(self, folder: str, **kwargs):
        super().__init__(
            f"Failed to delete folder: {folder}",
            "3004",
            {**kwargs, "folder": folder},
        )


class IMAPFolderRenameFailed(IMAPError):
    """文件夹重命名失败"""

    def __init__(self, old_name: str, new_name: str, **kwargs):
        super().__init__(
            f"Failed to rename folder from {old_name} to {new_name}",
            "3005",
            {**kwargs, "old_name": old_name, "new_name": new_name},
        )


class IMAPFolderPermissionDenied(IMAPError):
    """文件夹权限不足"""

    def __init__(self, folder: str, **kwargs):
        super().__init__(
            f"Permission denied for folder: {folder}",
            "3006",
            {**kwargs, "folder": folder},
        )


# ========== 邮件操作错误 (4xxx) ==========


class IMAPEmailNotFound(IMAPError):
    """邮件不存在"""

    def __init__(self, uid: int, folder: str = "INBOX", **kwargs):
        super().__init__(
            f"Email not found: UID {uid} in {folder}",
            "4001",
            {**kwargs, "uid": uid, "folder": folder},
        )


class IMAPEmailFetchFailed(IMAPError):
    """邮件获取失败"""

    def __init__(self, uid: int, **kwargs):
        super().__init__(
            f"Failed to fetch email: UID {uid}",
            "4002",
            {**kwargs, "uid": uid},
        )


class IMAPEmailDeleteFailed(IMAPError):
    """邮件删除失败"""

    def __init__(self, uid: int, **kwargs):
        super().__init__(
            f"Failed to delete email: UID {uid}",
            "4003",
            {**kwargs, "uid": uid},
        )


class IMAPEmailMoveFailed(IMAPError):
    """邮件移动失败"""

    def __init__(self, uid: int, destination: str, **kwargs):
        super().__init__(
            f"Failed to move email {uid} to {destination}",
            "4004",
            {**kwargs, "uid": uid, "destination": destination},
        )


class IMAPEmailCopyFailed(IMAPError):
    """邮件复制失败"""

    def __init__(self, uid: int, destination: str, **kwargs):
        super().__init__(
            f"Failed to copy email {uid} to {destination}",
            "4005",
            {**kwargs, "uid": uid, "destination": destination},
        )


class IMAPEmailFlagFailed(IMAPError):
    """邮件标志操作失败"""

    def __init__(self, uid: int, flag: str, **kwargs):
        super().__init__(
            f"Failed to set flag {flag} on email {uid}",
            "4006",
            {**kwargs, "uid": uid, "flag": flag},
        )


class IMAPEmailParseFailed(IMAPError):
    """邮件解析失败"""

    def __init__(self, uid: int, **kwargs):
        super().__init__(
            f"Failed to parse email: UID {uid}",
            "4007",
            {**kwargs, "uid": uid},
        )


# ========== 搜索相关错误 (5xxx) ==========


class IMAPSearchError(IMAPError):
    """搜索失败"""

    def __init__(self, message: str = "Search operation failed", **kwargs):
        super().__init__(message, "5001", kwargs)


class IMAPSearchTimeout(IMAPError):
    """搜索超时"""

    def __init__(self, message: str = "Search operation timed out", **kwargs):
        super().__init__(message, "5002", kwargs)


class IMAPSearchInvalidCondition(IMAPError):
    """无效搜索条件"""

    def __init__(self, condition: str, **kwargs):
        super().__init__(
            f"Invalid search condition: {condition}",
            "5003",
            {**kwargs, "condition": condition},
        )


# ========== 通用错误 (9xxx) ==========


class IMAPProtocolError(IMAPError):
    """协议错误"""

    def __init__(self, message: str = "IMAP protocol error", **kwargs):
        super().__init__(message, "9001", kwargs)


class IMAPNotConnectedError(IMAPError):
    """未连接"""

    def __init__(self, message: str = "Not connected to IMAP server", **kwargs):
        super().__init__(message, "9003", kwargs)


class IMAPInvalidParameterError(IMAPError):
    """无效参数"""

    def __init__(self, param: str, **kwargs):
        super().__init__(f"Invalid parameter: {param}", "9004", {**kwargs, "parameter": param})


class IMAPOperationTimeout(IMAPError):
    """操作超时"""

    def __init__(self, operation: str, **kwargs):
        super().__init__(
            f"Operation timed out: {operation}",
            "9005",
            {**kwargs, "operation": operation},
        )
