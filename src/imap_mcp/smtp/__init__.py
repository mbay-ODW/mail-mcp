"""SMTP 模块

提供 SMTP 连接管理和邮件发送功能。
"""

import threading
from dataclasses import dataclass
from typing import Optional

from .auth import (
    LoginAuth,
    OAuth2Auth,
    PlainAuth,
    generate_oauth2_string,
    parse_recipients,
    validate_email_address,
    validate_email_address_with_error,
)
from .connection import SMTPClient, SMTPConfig
from .errors import (
    SMTPAuthError,
    SMTPConnectionError,
    SMTPRecipientsError,
    SMTPSendError,
    SMTPErrors,
)


@dataclass
class Attachment:
    """Email attachment.
    
    Attributes:
        filename: Attachment filename
        content_type: MIME content type
        data: Raw attachment data as bytes
    """
    filename: str
    content_type: str
    data: bytes


# Global SMTP client instance with thread-safe lock
_smtp_client: Optional[SMTPClient] = None
_smtp_lock = threading.Lock()


def get_smtp_client() -> SMTPClient:
    """Get or create SMTP client instance (thread-safe)."""
    global _smtp_client
    if _smtp_client is None:
        with _smtp_lock:
            # Double-check after acquiring lock
            if _smtp_client is None:
                config = SMTPConfig.from_env()
                _smtp_client = SMTPClient(config)
    return _smtp_client


def reset_smtp_client() -> None:
    """Reset SMTP client (for testing, thread-safe)."""
    global _smtp_client
    with _smtp_lock:
        if _smtp_client:
            _smtp_client.disconnect()
            _smtp_client = None


__all__ = [
    # 配置和客户端
    "SMTPConfig",
    "SMTPClient",
    "Attachment",
    "get_smtp_client",
    "reset_smtp_client",
    # 错误类
    "SMTPErrors",
    "SMTPConnectionError",
    "SMTPAuthError",
    "SMTPSendError",
    "SMTPRecipientsError",
    # 认证
    "OAuth2Auth",
    "PlainAuth",
    "LoginAuth",
    "generate_oauth2_string",
    "validate_email_address",
    "validate_email_address_with_error",
    "parse_recipients",
]