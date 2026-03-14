"""SMTP 连接管理"""
import os
import smtplib
import socket
from dataclasses import dataclass
from typing import List, Optional

from .errors import (
    SMTPConnectionError,
    SMTPAuthError,
    SMTPSendError,
    SMTPRecipientsError,
)


@dataclass
class SMTPConfig:
    """SMTP 配置"""

    host: str
    port: int
    user: str
    password: str
    ssl: bool = True
    starttls: bool = False

    @classmethod
    def from_env(cls) -> "SMTPConfig":
        """从环境变量创建配置"""
        return cls(
            host=os.getenv("SMTP_HOST", "smtp.example.com"),
            port=int(os.getenv("SMTP_PORT", "465")),
            user=os.getenv("EMAIL_USER", ""),
            password=os.getenv("EMAIL_PASSWORD", ""),
            ssl=os.getenv("SMTP_SSL", "true").lower() == "true",
            starttls=os.getenv("SMTP_STARTTLS", "false").lower() == "true",
        )


class SMTPClient:
    """SMTP 客户端

    支持 SSL (端口 465) 和 STARTTLS (端口 587) 两种连接模式。
    提供连接复用机制，类似 IMAPClient。
    """

    def __init__(self, config: SMTPConfig):
        """初始化 SMTP 客户端

        Args:
            config: SMTP 配置
        """
        self.config = config
        self._connection: Optional[smtplib.SMTP] = None
        self._is_connected: bool = False

    @property
    def is_connected(self) -> bool:
        """检查是否已连接"""
        if self._connection is None:
            return False
        try:
            # 尝试检查连接状态
            status = self._connection.noop()[0]
            return status == 250
        except Exception:
            return False

    def connect(self) -> None:
        """建立 SMTP 连接

        根据配置选择 SSL 或 STARTTLS 模式
        """
        try:
            if self.config.ssl:
                # SSL 模式 (端口 465)
                self._connection = smtplib.SMTP_SSL(
                    self.config.host,
                    self.config.port,
                    timeout=30,
                )
            else:
                # 普通模式 (需要 STARTTLS)
                self._connection = smtplib.SMTP(
                    self.config.host,
                    self.config.port,
                    timeout=30,
                )
                # 启用 STARTTLS
                if self.config.starttls:
                    self._connection.starttls()

            # 登录
            if self.config.user and self.config.password:
                self._connection.login(self.config.user, self.config.password)

            self._is_connected = True

        except smtplib.SMTPAuthenticationError as e:
            raise SMTPAuthError(
                f"认证失败: {str(e)}",
                username=self.config.user,
            )
        except smtplib.SMTPConnectError as e:
            raise SMTPConnectionError(
                f"连接失败: {str(e)}",
                host=self.config.host,
                port=self.config.port,
            )
        except socket.timeout as e:
            raise SMTPConnectionError(
                f"连接超时: {str(e)}",
                host=self.config.host,
                port=self.config.port,
            )
        except socket.gaierror as e:
            raise SMTPConnectionError(
                f"DNS 解析失败: {str(e)}",
                host=self.config.host,
                port=self.config.port,
            )
        except Exception as e:
            raise SMTPConnectionError(
                f"连接错误: {str(e)}",
                host=self.config.host,
                port=self.config.port,
            )

    def disconnect(self) -> None:
        """关闭 SMTP 连接"""
        if self._connection is not None:
            try:
                self._connection.quit()
            except Exception:
                # 可能连接已断开，尝试关闭
                try:
                    self._connection.close()
                except Exception:
                    pass
            finally:
                self._connection = None
                self._is_connected = False

    def _ensure_connected(self) -> smtplib.SMTP:
        """确保连接活跃，如已断开则重新连接

        Returns:
            SMTP 连接对象

        Raises:
            SMTPConnectionError: 连接未建立且无法重建
        """
        if not self.is_connected:
            self.connect()
        return self._connection

    def __enter__(self) -> "SMTPClient":
        """上下文管理器入口"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """上下文管理器退出"""
        self.disconnect()

    def __del__(self) -> None:
        """析构时确保关闭连接"""
        self.disconnect()