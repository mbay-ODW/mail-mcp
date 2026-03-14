"""SMTP MCP 集成测试"""

import pytest
import os
from unittest.mock import Mock, patch, MagicMock

from imap_mcp.smtp import SMTPConfig, SMTPClient, Attachment, get_smtp_client, reset_smtp_client
from imap_mcp.smtp.operations import send_email, send_reply, send_forward


class TestSMTPConfig:
    """测试 SMTP 配置"""
    
    def test_from_env_default(self):
        """测试默认环境变量"""
        # Clear env vars
        env_vars = ["SMTP_HOST", "SMTP_PORT", "EMAIL_USER", "EMAIL_PASSWORD", "SMTP_SSL", "SMTP_STARTTLS"]
        original = {k: os.environ.get(k) for k in env_vars}
        
        try:
            # Unset all env vars
            for k in env_vars:
                if k in os.environ:
                    del os.environ[k]
            
            config = SMTPConfig.from_env()
            
            assert config.host == "smtp.example.com"
            assert config.port == 465
            assert config.user == ""
            assert config.password == ""
            assert config.ssl is True
            assert config.starttls is False
        finally:
            # Restore original env
            for k, v in original.items():
                if v is not None:
                    os.environ[k] = v
                elif k in os.environ:
                    del os.environ[k]
    
    def test_from_env_custom(self):
        """测试自定义环境变量"""
        env_vars = {
            "SMTP_HOST": "smtp.custom.com",
            "SMTP_PORT": "587",
            "EMAIL_USER": "testuser",
            "EMAIL_PASSWORD": "testpass",
            "SMTP_SSL": "false",
            "SMTP_STARTTLS": "true",
        }
        
        original = {k: os.environ.get(k) for k in env_vars.keys()}
        
        try:
            os.environ.update(env_vars)
            
            config = SMTPConfig.from_env()
            
            assert config.host == "smtp.custom.com"
            assert config.port == 587
            assert config.user == "testuser"
            assert config.password == "testpass"
            assert config.ssl is False
            assert config.starttls is True
        finally:
            for k, v in original.items():
                if v is not None:
                    os.environ[k] = v
                elif k in os.environ:
                    del os.environ[k]


class TestSMTPClient:
    """测试 SMTP 客户端"""
    
    @patch("smtplib.SMTP_SSL")
    def test_connect_ssl(self, mock_smtp):
        """测试 SSL 连接"""
        mock_connection = MagicMock()
        mock_smtp.return_value = mock_connection
        
        config = SMTPConfig(
            host="smtp.test.com",
            port=465,
            user="test@test.com",
            password="pass",
            ssl=True,
        )
        
        client = SMTPClient(config)
        client.connect()
        
        mock_smtp.assert_called_once()
        mock_connection.login.assert_called_once_with("test@test.com", "pass")
    
    @patch("smtplib.SMTP")
    def test_connect_starttls(self, mock_smtp):
        """测试 STARTTLS 连接"""
        mock_connection = MagicMock()
        mock_smtp.return_value = mock_connection
        
        config = SMTPConfig(
            host="smtp.test.com",
            port=587,
            user="test@test.com",
            password="pass",
            ssl=False,
            starttls=True,
        )
        
        client = SMTPClient(config)
        client.connect()
        
        mock_smtp.assert_called_once()
        mock_connection.starttls.assert_called_once()
        mock_connection.login.assert_called_once_with("test@test.com", "pass")
    
    @patch("smtplib.SMTP_SSL")
    def test_send(self, mock_smtp):
        """测试发送邮件"""
        mock_connection = MagicMock()
        mock_smtp.return_value = mock_connection
        mock_connection.login.return_value = (True, b'OK')
        mock_connection.sendmail.return_value = {}
        
        config = SMTPConfig(
            host="smtp.test.com",
            port=465,
            user="test@test.com",
            password="pass",
        )
        
        client = SMTPClient(config)
        client.connect()
        
        # 使用 send_email 方法 (参数: from_addr, to_addrs, subject, body)
        result = client.send_email(
            from_addr="test@test.com",
            to_addrs=["recipient@test.com"],
            subject="Test Subject",
            body="Test body",
        )
        
        assert result["success"] is True
        mock_connection.sendmail.assert_called()


class TestSMTPOperations:
    """测试 SMTP 操作"""
    
    def test_send_email(self):
        """测试发送邮件"""
        mock_client = MagicMock()
        mock_client.config.user = "sender@test.com"
        mock_client.send_email.return_value = {"success": True, "recipients": ["recipient@test.com"]}
        
        result = send_email(
            client=mock_client,
            to=["recipient@test.com"],
            subject="Test Subject",
            body_text="Test body",
        )
        
        assert result.success is True
    
    def test_send_email_no_recipients(self):
        """测试无收件人错误"""
        mock_client = MagicMock()
        mock_client.config.user = "sender@test.com"
        
        result = send_email(
            client=mock_client,
            to=[],
            subject="Test",
        )
        # 返回失败结果
        assert result.success is False
    
    def test_send_reply(self):
        """测试回复邮件"""
        mock_client = MagicMock()
        mock_client.config.user = "sender@test.com"
        mock_client.send_email.return_value = {"success": True}
        
        result = send_reply(
            client=mock_client,
            to=["recipient@test.com"],
            subject="Re: Test",
            body_text="Reply body",
            reply_to_message_id="<test@example.com>",
        )
        
        assert result.success is True
    
    def test_send_forward(self):
        """测试转发邮件"""
        from email.message import Message
        
        mock_client = MagicMock()
        mock_client.config.user = "sender@test.com"
        mock_client.send_email.return_value = {"success": True}
        
        # 创建原始邮件
        original_msg = Message()
        original_msg["From"] = "original@test.com"
        original_msg["To"] = "recipient@test.com"
        original_msg["Subject"] = "Original Subject"
        original_msg.set_payload("Original body")
        
        result = send_forward(
            client=mock_client,
            to=["forward@test.com"],
            subject="Fwd: Test",
            original_message=original_msg,
            body_text="Here is the forwarded email:",
        )
        
        assert result.success is True


class TestAttachment:
    """测试附件"""
    
    def test_attachment_creation(self):
        """测试附件创建"""
        data = b"test data"
        att = Attachment(
            filename="test.txt",
            content_type="text/plain",
            data=data,
        )
        
        assert att.filename == "test.txt"
        assert att.content_type == "text/plain"
        assert att.data == data


@pytest.fixture(autouse=True)
def reset_smtp_client_fixture():
    """每个测试后重置 SMTP 客户端"""
    yield
    reset_smtp_client()