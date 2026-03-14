"""
IMAP MCP Server - Core 模块单元测试

测试 IMAP 连接管理、认证和错误处理功能。
"""

import sys
import os

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
import ssl
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from src.imap_mcp.core import (
    ConnectionConfig,
    IMAPConnection,
    imap_connection,
    AuthHandler,
    IMAPCredentials,
)
from src.imap_mcp.core.errors import (
    IMAPConnectionError,
    IMAPConnectionTimeout,
    IMAPSSLError,
    IMAPHostUnreachable,
    IMAPAuthError,
    IMAPInvalidCredentials,
    IMAPNotConnectedError,
    IMAPFolderNotFound,
    IMAPEmailNotFound,
)


class TestConnectionConfig:
    """ConnectionConfig 测试"""

    def test_default_values(self):
        """测试默认值"""
        config = ConnectionConfig(
            host="imap.example.com",
            port=993,
            username="test@example.com",
            password="password",
        )

        assert config.host == "imap.example.com"
        assert config.port == 993
        assert config.username == "test@example.com"
        assert config.password == "password"
        assert config.ssl is True
        assert config.starttls is False
        assert config.timeout == 30
        assert config.ssl_verify is True

    def test_to_credentials(self):
        """测试转换为凭证对象"""
        config = ConnectionConfig(
            host="imap.example.com",
            port=993,
            username="test@example.com",
            password="secret",
            ssl=True,
            starttls=False,
        )

        creds = config.to_credentials()

        assert creds.host == "imap.example.com"
        assert creds.port == 993
        assert creds.username == "test@example.com"
        assert creds.password == "secret"
        assert creds.ssl is True
        assert creds.starttls is False


class TestIMAPCredentials:
    """IMAPCredentials 测试"""

    def test_validate_success(self):
        """测试有效凭证"""
        creds = IMAPCredentials(
            host="imap.example.com",
            port=993,
            username="test",
            password="pass",
        )
        creds.validate()  # 不应抛出异常

    def test_validate_empty_host(self):
        """测试空主机"""
        creds = IMAPCredentials(
            host="",
            port=993,
            username="test",
            password="pass",
        )
        with pytest.raises(IMAPInvalidCredentials):
            creds.validate()

    def test_validate_invalid_port(self):
        """测试无效端口"""
        creds = IMAPCredentials(
            host="imap.example.com",
            port=0,
            username="test",
            password="pass",
        )
        with pytest.raises(IMAPInvalidCredentials):
            creds.validate()

    def test_validate_empty_username(self):
        """测试空用户名"""
        creds = IMAPCredentials(
            host="imap.example.com",
            port=993,
            username="",
            password="pass",
        )
        with pytest.raises(IMAPInvalidCredentials):
            creds.validate()

    def test_validate_empty_password(self):
        """测试空密码"""
        creds = IMAPCredentials(
            host="imap.example.com",
            port=993,
            username="test",
            password="",
        )
        with pytest.raises(IMAPInvalidCredentials):
            creds.validate()

    def test_ssl_and_starttls_warning(self):
        """测试 SSL 和 STARTTLS 同时启用会产生警告"""
        creds = IMAPCredentials(
            host="imap.example.com",
            port=993,
            username="test",
            password="pass",
            ssl=True,
            starttls=True,
        )
        # 不应抛出异常，但会有警告
        creds.validate()


class TestAuthHandler:
    """AuthHandler 测试"""

    def test_init(self):
        """测试初始化"""
        creds = IMAPCredentials(
            host="imap.example.com",
            port=993,
            username="test",
            password="pass",
        )
        handler = AuthHandler(creds)

        assert handler.credentials == creds

    @patch("src.imap_mcp.core.auth.imaplib.IMAP4_SSL")
    def test_authenticate_success(self, mock_imap_class):
        """测试成功认证"""
        # 模拟 IMAP 连接
        mock_connection = MagicMock()
        mock_imap_class.return_value = mock_connection

        # 模拟 LOGIN 响应
        mock_connection.login.return_value = ("OK", [b"Login succeeded"])

        creds = IMAPCredentials(
            host="imap.example.com",
            port=993,
            username="test@example.com",
            password="password",
        )
        handler = AuthHandler(creds)

        result = handler.authenticate(mock_connection)

        assert result is True
        mock_connection.login.assert_called_once_with(
            "test@example.com", "password"
        )

    @patch("src.imap_mcp.core.auth.imaplib.IMAP4_SSL")
    def test_authenticate_failure(self, mock_imap_class):
        """测试认证失败"""
        mock_connection = MagicMock()
        mock_imap_class.return_value = mock_connection

        # 模拟认证失败
        mock_connection.login.side_effect = Exception(
            b"AUTHENTICATIONFAILED Invalid credentials"
        )

        creds = IMAPCredentials(
            host="imap.example.com",
            port=993,
            username="test@example.com",
            password="wrong_password",
        )
        handler = AuthHandler(creds)

        with pytest.raises(IMAPInvalidCredentials):
            handler.authenticate(mock_connection)


class TestIMAPConnection:
    """IMAPConnection 测试"""

    def test_init(self):
        """测试初始化"""
        config = ConnectionConfig(
            host="imap.example.com",
            port=993,
            username="test",
            password="pass",
        )

        conn = IMAPConnection(config)

        assert conn.config == config
        assert conn._connection is None
        assert conn._connected is False
        assert conn._selected_folder is None

    def test_is_connected_not_connected(self):
        """测试未连接状态"""
        config = ConnectionConfig(
            host="imap.example.com",
            port=993,
            username="test",
            password="pass",
        )
        conn = IMAPConnection(config)

        assert conn.is_connected is False

    @patch("src.imap_mcp.core.connection.imaplib.IMAP4_SSL")
    def test_is_connected_check(self, mock_imap_class):
        """测试连接状态检查"""
        mock_connection = MagicMock()
        mock_imap_class.return_value = mock_connection
        mock_connection.noop.return_value = ("OK", [b"NOOP completed"])

        config = ConnectionConfig(
            host="imap.example.com",
            port=993,
            username="test",
            password="pass",
        )
        conn = IMAPConnection(config)
        conn._connection = mock_connection
        conn._connected = True

        # 模拟 noop 成功
        assert conn.is_connected is True

    @patch("src.imap_mcp.core.connection.imaplib.IMAP4_SSL")
    def test_context_manager(self, mock_imap_class):
        """测试上下文管理器"""
        mock_connection = MagicMock()
        mock_imap_class.return_value = mock_connection
        mock_connection.login.return_value = ("OK", [b"Login succeeded"])
        mock_connection.logout.return_value = ("OK", [b"Logged out"])

        config = ConnectionConfig(
            host="imap.example.com",
            port=993,
            username="test",
            password="pass",
        )

        with imap_connection(config) as conn:
            assert conn.is_connected is True

        # 验证 logout 被调用
        mock_connection.logout.assert_called_once()

    @patch("src.imap_mcp.core.connection.imaplib.IMAP4_SSL")
    def test_select_folder_success(self, mock_imap_class):
        """测试选择文件夹成功"""
        mock_connection = MagicMock()
        mock_imap_class.return_value = mock_connection
        mock_connection.login.return_value = ("OK", [b"Login succeeded"])
        mock_connection.select.return_value = ("OK", [b"10 EXISTS", b"0 RECENT"])

        config = ConnectionConfig(
            host="imap.example.com",
            port=993,
            username="test",
            password="pass",
        )

        with imap_connection(config) as conn:
            result = conn.select_folder("INBOX")

            assert result["exists"] == 10
            assert result["folder"] == "INBOX"
            assert conn.selected_folder == "INBOX"

    @patch("src.imap_mcp.core.connection.imaplib.IMAP4_SSL")
    def test_select_folder_not_connected(self, mock_imap_class):
        """测试未连接时选择文件夹"""
        mock_connection = MagicMock()
        mock_imap_class.return_value = mock_connection
        mock_connection.login.return_value = ("OK", [b"Login succeeded"])

        config = ConnectionConfig(
            host="imap.example.com",
            port=993,
            username="test",
            password="pass",
        )

        conn = IMAPConnection(config)
        # 未连接状态

        with pytest.raises(IMAPNotConnectedError):
            conn.select_folder("INBOX")

    @patch("src.imap_mcp.core.connection.imaplib.IMAP4_SSL")
    def test_close_folder(self, mock_imap_class):
        """测试关闭文件夹"""
        mock_connection = MagicMock()
        mock_imap_class.return_value = mock_connection
        mock_connection.login.return_value = ("OK", [b"Login succeeded"])
        mock_connection.select.return_value = ("OK", [b"10 EXISTS"])
        mock_connection.close.return_value = ("OK", [b"Closed"])

        config = ConnectionConfig(
            host="imap.example.com",
            port=993,
            username="test",
            password="pass",
        )

        with imap_connection(config) as conn:
            conn.select_folder("INBOX")
            assert conn.selected_folder == "INBOX"

            conn.close_folder()
            assert conn.selected_folder is None

    def test_repr(self):
        """测试 __repr__"""
        config = ConnectionConfig(
            host="imap.example.com",
            port=993,
            username="test",
            password="pass",
        )

        conn = IMAPConnection(config)
        assert "imap.example.com" in repr(conn)
        assert "993" in repr(conn)

        conn._connected = True
        conn._selected_folder = "INBOX"
        assert "connected" in repr(conn)
        assert "INBOX" in repr(conn)


class TestConnectionErrors:
    """连接错误测试"""

    @patch("src.imap_mcp.core.connection.imaplib.IMAP4_SSL")
    def test_connection_timeout(self, mock_imap_class):
        """测试连接超时"""
        import socket

        mock_imap_class.side_effect = socket.timeout("Connection timed out")

        config = ConnectionConfig(
            host="imap.example.com",
            port=993,
            username="test",
            password="pass",
        )
        conn = IMAPConnection(config)

        with pytest.raises(IMAPConnectionTimeout):
            conn.connect()

    @patch("src.imap_mcp.core.connection.imaplib.IMAP4_SSL")
    def test_host_unreachable(self, mock_imap_class):
        """测试主机不可达"""
        import socket

        mock_imap_class.side_effect = socket.gaierror("Name or service not known")

        config = ConnectionConfig(
            host="invalid.host.example.com",
            port=993,
            username="test",
            password="pass",
        )
        conn = IMAPConnection(config)

        with pytest.raises(IMAPHostUnreachable):
            conn.connect()

    @patch("src.imap_mcp.core.connection.imaplib.IMAP4_SSL")
    def test_ssl_error(self, mock_imap_class):
        """测试 SSL 错误"""
        import ssl

        mock_imap_class.side_effect = ssl.SSLError("Certificate verify failed")

        config = ConnectionConfig(
            host="imap.example.com",
            port=993,
            username="test",
            password="pass",
            ssl_verify=False,
        )
        conn = IMAPConnection(config)

        with pytest.raises(IMAPSSLError):
            conn.connect()


class TestErrorHandling:
    """错误处理测试"""

    def test_imap_error_to_dict(self):
        """测试异常转换为字典"""
        error = IMAPConnectionError(
            "Connection failed",
            error_code="1001",
            details={"host": "example.com"},
        )

        error_dict = error.to_dict()

        assert error_dict["error"] == "Connection failed"
        assert error_dict["error_code"] == "1001"
        assert error_dict["details"]["host"] == "example.com"

    def test_folder_not_found_error(self):
        """测试文件夹未找到错误"""
        error = IMAPFolderNotFound("INBOX/Archive")

        assert error.error_code == "3001"
        assert "INBOX/Archive" in error.message

    def test_email_not_found_error(self):
        """测试邮件未找到错误"""
        error = IMAPEmailNotFound(uid=12345, folder="INBOX")

        assert error.error_code == "4001"
        assert "12345" in error.message
        assert "INBOX" in error.message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])