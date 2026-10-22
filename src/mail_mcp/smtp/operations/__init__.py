"""SMTP Operations - 邮件发送操作模块"""

from .message import build_email_message
from .send import send_email, send_prepared

__all__ = ["send_email", "send_prepared", "build_email_message"]
