"""
IMAP 连接管理模块

提供 IMAP 连接的上下文管理器和连接池支持。
"""

import logging
import imaplib
import ssl as ssl_module
import socket
from ssl import SSLContext
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator, Optional
from datetime import datetime, timedelta

from .auth import AuthHandler, IMAPCredentials
from .errors import (
    IMAPConnectionError,
    IMAPConnectionTimeout,
    IMAPSSLError,
    IMAPHostUnreachable,
    IMAPNotConnectedError,
    IMAPProtocolError,
    IMAPOperationTimeout,
)

logger = logging.getLogger("mail_mcp")


# 默认超时设置
DEFAULT_TIMEOUT = 30  # 秒
SEARCH_TIMEOUT = 60  # 搜索操作超时


@dataclass
class ConnectionConfig:
    """连接配置"""

    host: str
    port: int
    username: str
    password: str
    ssl: bool = True
    starttls: bool = False
    timeout: int = DEFAULT_TIMEOUT
    search_timeout: int = SEARCH_TIMEOUT

    # SSL 配置
    ssl_context: Optional[SSLContext] = None
    ssl_verify: bool = True

    # 调试
    debug: bool = False

    def to_credentials(self) -> IMAPCredentials:
        """转换为凭证对象"""
        return IMAPCredentials(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            ssl=self.ssl,
            starttls=self.starttls,
        )


class IMAPConnection:
    """
    IMAP 连接管理类

    提供上下文管理器支持和连接池管理。

    用法:
        with IMAPConnection(config) as conn:
            conn.select_folder("INBOX")
            # ...
    """

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._connection: Optional[imaplib.IMAP4] = None
        self._connected: bool = False
        self._selected_folder: Optional[str] = None
        self._last_activity: Optional[datetime] = None
        self._auth_handler = AuthHandler(config.to_credentials())

    @property
    def is_connected(self) -> bool:
        """检查是否已连接"""
        if self._connection is None:
            return False
        try:
            # 尝试 NOOP 检查连接状态
            self._connection.noop()
            return True
        except Exception:
            self._connected = False
            return False

    @property
    def selected_folder(self) -> Optional[str]:
        """当前选中的文件夹"""
        return self._selected_folder

    @property
    def raw(self) -> Optional[imaplib.IMAP4]:
        """获取原始 IMAP 连接对象"""
        return self._connection

    # 代理常用 IMAP 方法
    def list(self, directory: str = '', pattern: str = '*'):
        """列出文件夹 (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        # 直接调用 list() 不带参数，因为阿里云不支持 list('', '*')
        if directory == '' and pattern == '*':
            return self._connection.list()
        return self._connection.list(directory, pattern)

    def search(self, *criteria):
        """搜索邮件 (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        return self._connection.search(None, *criteria)

    def fetch(self, *args):
        """获取邮件 (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        return self._connection.fetch(*args)

    def store(self, *args):
        """修改邮件标记 (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        return self._connection.store(*args)

    def uid(self, command: str, *args):
        """执行 UID 命令 (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        return self._connection.uid(command, *args)

    def create(self, mailbox: str):
        """创建文件夹 (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        return self._connection.create(mailbox)

    def delete(self, mailbox: str):
        """删除文件夹 (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        return self._connection.delete(mailbox)

    def rename(self, old_name: str, new_name: str):
        """重命名文件夹 (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        return self._connection.rename(old_name, new_name)

    def subscribe(self, mailbox: str):
        """订阅文件夹 (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        return self._connection.subscribe(mailbox)

    def unsubscribe(self, mailbox: str):
        """取消订阅文件夹 (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        return self._connection.unsubscribe(mailbox)

    def status(self, mailbox: str, items: str):
        """获取文件夹状态 (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        return self._connection.status(mailbox, items)

    def copy(self, *args):
        """复制邮件 (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        return self._connection.copy(*args)

    def expunge(self):
        """执行 expunge (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        return self._connection.expunge()

    def select(self, mailbox: str = 'INBOX', readonly: bool = False):
        """选择邮箱 (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        return self._connection.select(mailbox, readonly)

    def lsub(self, directory: str = '', pattern: str = '*'):
        """列出订阅的文件夹 (代理到原始连接)"""
        if self._connection is None:
            raise IMAPNotConnectedError("Not connected to IMAP server")
        return self._connection.lsub(directory, pattern)

    def connect(self) -> None:
        """建立 IMAP 连接"""
        config = self.config

        logger.info(
            f"Connecting to {config.host}:{config.port} "
            f"(SSL={config.ssl}, STARTTLS={config.starttls})"
        )

        try:
            # 创建 SSL 上下文
            ssl_context = config.ssl_context
            if config.ssl and ssl_context is None:
                ssl_context = ssl_module.create_default_context()
                if not config.ssl_verify:
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl_module.CERT_NONE

            # 建立连接
            if config.ssl:
                self._connection = imaplib.IMAP4_SSL(
                    host=config.host,
                    port=config.port,
                    ssl_context=ssl_context,
                )
            else:
                self._connection = imaplib.IMAP4(
                    host=config.host,
                    port=config.port,
                )

            # 设置超时
            self._connection.timeout = config.timeout

            # 设置调试模式
            if config.debug:
                self._connection.debug = 4

            # 执行认证
            self._auth_handler.authenticate(self._connection)

            self._connected = True
            self._last_activity = datetime.now()

            logger.info(
                f"Successfully connected to {config.host}:{config.port} "
                f"as {config.username}"
            )

        except socket.timeout as e:
            raise IMAPConnectionTimeout(
                f"Connection to {config.host}:{config.port} timed out",
                host=config.host,
                port=config.port,
            ) from e

        except socket.gaierror as e:
            raise IMAPHostUnreachable(
                f"Cannot resolve host {config.host}: {e}",
                host=config.host,
            ) from e

        except ssl_module.SSLError as e:
            raise IMAPSSLError(
                f"SSL error connecting to {config.host}: {e}",
                host=config.host,
            ) from e

        except imaplib.IMAP4.error as e:
            error_bytes = str(e).encode()
            if b"AUTHENTICATIONFAILED" in error_bytes:
                from .errors import IMAPInvalidCredentials
                raise IMAPInvalidCredentials(str(e)) from e
            raise IMAPConnectionError(
                f"IMAP error during connection: {e}",
                host=config.host,
            ) from e

        except Exception as e:
            raise IMAPConnectionError(
                f"Failed to connect to {config.host}:{config.port}: {e}",
                host=config.host,
                port=config.port,
            ) from e

    def disconnect(self) -> None:
        """断开 IMAP 连接"""
        if self._connection:
            try:
                self._connection.logout()
                logger.info("IMAP connection closed")
            except Exception as e:
                logger.warning(f"Error during logout: {e}")
            finally:
                self._connection = None
                self._connected = False
                self._selected_folder = None

    def select_folder(self, folder: str, readonly: bool = False) -> dict:
        """
        选择文件夹

        Args:
            folder: 文件夹名称
            readonly: 是否只读模式

        Returns:
            文件夹状态字典
        """
        if not self.is_connected:
            raise IMAPNotConnectedError("Not connected")

        logger.debug(f"Selecting folder: {folder} (readonly={readonly})")

        try:
            typ, data = self._connection.select(folder, readonly=readonly)

            if typ != "OK":
                raise IMAPProtocolError(
                    f"Failed to select folder {folder}: {data[0] if data else 'Unknown error'}"
                )

            # 解析响应
            exists = 0
            recent = 0
            unseen = 0

            if data:
                for line in data:
                    if isinstance(line, bytes):
                        line = line.decode()
                    if line.startswith("EXISTS"):
                        exists = int(line.split()[0])
                    elif line.startswith("RECENT"):
                        recent = int(line.split()[0])

            # 获取 UNSEEN 状态
            try:
                typ, search_data = self._connection.search(None, "UNSEEN")
                if typ == "OK" and search_data[0]:
                    unseen = len(search_data[0].split())
            except Exception:
                pass

            self._selected_folder = folder
            self._last_activity = datetime.now()

            result = {
                "exists": exists,
                "recent": recent,
                "unseen": unseen,
                "folder": folder,
            }

            logger.debug(f"Folder {folder}: {exists} messages, {unseen} unseen")
            return result

        except imaplib.IMAP4.error as e:
            raise IMAPProtocolError(f"Failed to select folder: {e}") from e

    def close_folder(self) -> None:
        """关闭当前文件夹"""
        if self._connection and self._selected_folder:
            try:
                self._connection.close()
                logger.debug(f"Closed folder: {self._selected_folder}")
            except Exception as e:
                logger.warning(f"Error closing folder: {e}")
            finally:
                self._selected_folder = None

    def noop(self) -> None:
        """执行 NOOP 命令保持连接活跃"""
        if not self.is_connected:
            raise IMAPNotConnectedError("Not connected")

        try:
            self._connection.noop()
            self._last_activity = datetime.now()
        except Exception as e:
            logger.warning(f"NOOP failed: {e}")
            raise IMAPProtocolError(f"NOOP failed: {e}") from e

    def __enter__(self) -> "IMAPConnection":
        """进入上下文管理器"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """退出上下文管理器"""
        self.disconnect()

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        folder = f", folder={self._selected_folder}" if self._selected_folder else ""
        return f"IMAPConnection({self.config.host}:{self.config.port}, {status}{folder})"


@contextmanager
def imap_connection(config: ConnectionConfig) -> Generator[IMAPConnection, None, None]:
    """
    IMAP 连接上下文管理器

    用法:
        config = ConnectionConfig(
            host="imap.example.com",
            port=993,
            username="user@example.com",
            password="password",
            ssl=True,
        )

        with imap_connection(config) as conn:
            conn.select_folder("INBOX")
            # ...
    """
    conn = IMAPConnection(config)
    try:
        conn.connect()
        yield conn
    finally:
        conn.disconnect()


# ========== 连接池 (可选功能) ==========


@dataclass
class PooledConnection:
    """池化连接"""

    connection: IMAPConnection
    created_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    in_use: bool = False


class ConnectionPool:
    """
    IMAP 连接池

    提供连接复用功能，减少频繁建立连接的开销。

    注意: IMAP 连接池需要谨慎使用，因为 IMAP 连接不是完全线程安全的。
    建议每个线程使用独立连接。
    """

    def __init__(
        self,
        config: ConnectionConfig,
        max_connections: int = 5,
        max_idle_time: int = 300,  # 5 分钟
    ):
        self.config = config
        self.max_connections = max_connections
        self.max_idle_time = timedelta(seconds=max_idle_time)
        self._pool: list[PooledConnection] = []
        self._lock = None  # 可以使用 threading.Lock

    def get_connection(self) -> IMAPConnection:
        """获取连接"""
        now = datetime.now()

        # 尝试复用现有连接
        for pooled in self._pool:
            if not pooled.in_use:
                conn = pooled.connection

                # 检查连接是否有效
                if conn.is_connected:
                    # 检查是否过期
                    if now - pooled.last_used > self.max_idle_time:
                        conn.disconnect()
                        continue

                    pooled.in_use = True
                    pooled.last_used = now
                    logger.debug("Reusing pooled connection")
                    return conn
                else:
                    # 连接已失效，移除
                    self._pool.remove(pooled)

        # 创建新连接
        if len(self._pool) < self.max_connections:
            conn = IMAPConnection(self.config)
            conn.connect()

            pooled = PooledConnection(connection=conn, in_use=True)
            self._pool.append(pooled)

            logger.debug("Created new pooled connection")
            return conn

        # 等待可用连接 (简化实现，实际应使用条件变量)
        raise IMAPConnectionError("No available connections in pool")

    def release_connection(self, conn: IMAPConnection) -> None:
        """释放连接回池"""
        for pooled in self._pool:
            if pooled.connection is conn:
                pooled.in_use = False
                pooled.last_used = datetime.now()
                logger.debug("Released connection back to pool")
                break

    def close_all(self) -> None:
        """关闭所有连接"""
        for pooled in self._pool:
            pooled.connection.disconnect()
        self._pool.clear()
        logger.info("Connection pool closed")