"""
认证处理模块

提供 IMAP 认证相关的功能。
"""

import logging
from dataclasses import dataclass
from typing import Optional

from .errors import (
    IMAPAuthError,
    IMAPInvalidCredentials,
    IMAPAuthMethodNotSupported,
    IMAPAccountLocked,
)

logger = logging.getLogger("mail_mcp")


@dataclass
class IMAPCredentials:
    """IMAP 认证凭证"""

    host: str
    port: int
    username: str
    password: str
    ssl: bool = True
    starttls: bool = False

    def validate(self) -> None:
        """验证凭证参数"""
        if not self.host:
            raise IMAPInvalidCredentials("Host cannot be empty")
        if not self.port or self.port <= 0 or self.port > 65535:
            raise IMAPInvalidCredentials(f"Invalid port: {self.port}")
        if not self.username:
            raise IMAPInvalidCredentials("Username cannot be empty")
        if not self.password:
            raise IMAPInvalidCredentials("Password cannot be empty")

        # SSL 和 STARTTLS 不能同时启用
        if self.ssl and self.starttls:
            logger.warning("Both SSL and STARTTLS enabled, using SSL")


class AuthHandler:
    """IMAP 认证处理器"""

    def __init__(self, credentials: IMAPCredentials):
        self.credentials = credentials
        self._auth_methods: list[str] = []

    def authenticate(self, imap_connection) -> bool:
        """
        执行认证

        Args:
            imap_connection: imaplib.IMAP4 或 IMAP4_SSL 连接对象

        Returns:
            认证是否成功

        Raises:
            IMAPAuthError: 认证失败
            IMAPInvalidCredentials: 凭证无效
            IMAPAuthMethodNotSupported: 认证方法不支持
            IMAPAccountLocked: 账户被锁定
        """
        cred = self.credentials

        try:
            # 尝试 LOGIN 认证
            logger.info(f"Attempting LOGIN auth for {cred.username}@{cred.host}")
            typ, _ = imap_connection.login(cred.username, cred.password)

            if typ != "OK":
                raise IMAPAuthError(f"Login failed: {typ}")

            logger.info(f"Successfully authenticated {cred.username}")
            return True

        except Exception as e:
            error_msg = str(e).upper()

            if "AUTHENTICATIONFAILED" in error_msg:
                raise IMAPInvalidCredentials(
                    f"Invalid username or password: {e}"
                ) from e
            elif "LOCKED" in error_msg or "LOCK" in error_msg:
                raise IMAPAccountLocked(f"Account is locked: {e}") from e
            elif "CANNOT" in error_msg and "AUTH" in error_msg:
                raise IMAPAuthMethodNotSupported(
                    f"Authentication method not supported: {e}"
                ) from e
            else:
                raise IMAPAuthError(f"Authentication failed: {e}") from e

    def get_auth_methods(self, imap_connection) -> list[str]:
        """
        获取服务器支持的认证方法

        Args:
            imap_connection: imaplib 连接对象

        Returns:
            支持的认证方法列表
        """
        try:
            # 使用 ID 命令获取服务器信息
            typ, data = imap_connection.id()
            if typ == "OK" and data:
                logger.debug(f"Server ID: {data}")
        except Exception:
            pass

        # 常见的认证方法
        common_methods = ["LOGIN", "PLAIN", "XOAUTH2"]

        # 尝试获取 AUTHENTICATE 能力
        try:
            typ, capabilities = imap_connection.capability()
            if typ == "OK" and capabilities:
                caps = capabilities[0].decode() if isinstance(capabilities[0], bytes) else capabilities[0]
                logger.debug(f"Server capabilities: {caps}")

                # 提取 AUTH 方法
                for cap in caps.split():
                    if cap.startswith("AUTH="):
                        auth_method = cap.replace("AUTH=", "")
                        if auth_method not in self._auth_methods:
                            self._auth_methods.append(auth_method)
        except Exception as e:
            logger.warning(f"Failed to get capabilities: {e}")

        return self._auth_methods or common_methods

    @staticmethod
    def handle_auth_error(error: Exception) -> IMAPAuthError:
        """
        处理认证错误并转换为标准异常

        Args:
            error: 原始异常

        Returns:
            转换后的 IMAP 异常
        """
        error_msg = str(error).upper()

        if "AUTHENTICATIONFAILED" in error_msg:
            return IMAPInvalidCredentials(str(error))
        elif "LOCKED" in error_msg:
            return IMAPAccountLocked(str(error))
        elif "CANNOT" in error_msg and "AUTH" in error_msg:
            return IMAPAuthMethodNotSupported(str(error))
        else:
            return IMAPAuthError(str(error))