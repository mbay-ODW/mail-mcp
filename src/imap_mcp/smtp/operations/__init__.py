"""SMTP Operations - 邮件发送操作模块"""

from .send import send_email, send_reply, send_forward
from .message import build_email_message

__all__ = ["send_email", "send_reply", "send_forward", "build_email_message"]