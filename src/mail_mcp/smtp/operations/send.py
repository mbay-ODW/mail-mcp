"""邮件发送操作模块"""

import smtplib
from dataclasses import dataclass
from email.message import Message
from email.utils import make_msgid
from typing import Any

from .. import Attachment
from ..auth import validate_email_address
from .message import build_email_message


@dataclass
class SendResult:
    """发送结果

    Attributes:
        success: 是否发送成功
        message_id: 邮件 Message-ID
        error: 错误信息 (如果失败)
        rejected: 被拒绝的收件人列表
    """

    success: bool
    message_id: str | None = None
    error: str | None = None
    rejected: list[str] | None = None


def _get_smtp_client(client) -> smtplib.SMTP | None:
    """获取一个**存活的** SMTP 连接。

    优先走 ``SMTPClient._ensure_connected()``：它会先 NOOP 探活，socket
    已断开时自动重连。直接取缓存的 ``_connection`` 是不够的——邮件服务商
    会掐掉空闲连接，之后每次发送都会抛 smtplib 的
    "please run connect() first"，直到容器重启为止。
    """
    ensure = getattr(client, "_ensure_connected", None)
    if callable(ensure):
        return ensure()

    for attr in ("_connection", "connection", "smtp", "_smtp"):
        conn = getattr(client, attr, None)
        if conn is not None:
            return conn
    # 尝试直接使用
    return client


def _reconnect_smtp(client) -> smtplib.SMTP | None:
    """丢弃陈旧连接并重新建立 SMTP 连接。"""
    disconnect = getattr(client, "disconnect", None)
    if callable(disconnect):
        try:
            disconnect()
        except Exception:
            pass

    connect = getattr(client, "connect", None)
    if callable(connect):
        connect()
        return _get_smtp_client(client)
    return None


def _send_message(client, message, from_addr: str | None, to_addrs: list[str]) -> None:
    """发送邮件，并在连接失效时自动重连重试一次。

    即使先探活过，socket 仍可能在探活和发送之间被掐断，所以这里再兜一层
    ``SMTPServerDisconnected`` 重试。
    """
    smtp = _get_smtp_client(client)
    if smtp is None:
        smtp = _reconnect_smtp(client)
    if smtp is None:
        raise smtplib.SMTPException("无法获取 SMTP 连接")

    try:
        smtp.send_message(message, from_addr=from_addr, to_addrs=to_addrs)
    except smtplib.SMTPServerDisconnected:
        smtp = _reconnect_smtp(client)
        if smtp is None:
            raise
        smtp.send_message(message, from_addr=from_addr, to_addrs=to_addrs)


def send_email(
    client,
    to: list[str],
    subject: str,
    body_text: str | None = None,
    body_html: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[Attachment] | None = None,
    from_addr: str | None = None,
) -> SendResult:
    """
    发送邮件

    Args:
        client: SMTP 客户端对象
        to: 收件人列表 (必填)
        subject: 主题 (必填)
        body_text: 纯文本正文
        body_html: HTML 正文
        cc: 抄送列表
        bcc: 密送列表
        attachments: 附件列表
        from_addr: 发件人地址

    Returns:
        SendResult: 发送结果
    """
    # 1. 验证参数
    if not to:
        return SendResult(success=False, error="收件人列表不能为空")

    if not subject:
        return SendResult(success=False, error="邮件主题不能为空")

    if not body_text and not body_html:
        return SendResult(success=False, error="邮件正文不能为空")

    # 验证邮箱地址
    for addr in to:
        if not validate_email_address(addr):
            return SendResult(success=False, error=f"无效的收件人地址: {addr}")

    if cc:
        for addr in cc:
            if not validate_email_address(addr):
                return SendResult(success=False, error=f"无效的抄送地址: {addr}")

    if bcc:
        for addr in bcc:
            if not validate_email_address(addr):
                return SendResult(success=False, error=f"无效的密送地址: {addr}")

    try:
        # 获取发件人地址
        if not from_addr:
            if hasattr(client, "config") and hasattr(client.config, "user"):
                from_addr = client.config.user
            else:
                return SendResult(success=False, error="缺少发件人地址")

        # 2. 构建邮件消息
        message = build_email_message(
            sender=from_addr,
            to=to,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
        )

        # 生成 Message-ID
        message_id = make_msgid()
        message["Message-ID"] = message_id

        # 3. 获取所有收件人
        all_recipients = to.copy()
        if cc:
            all_recipients.extend(cc)
        if bcc:
            all_recipients.extend(bcc)

        # 4. 发送邮件（连接失效时自动重连）
        _send_message(client, message, from_addr=from_addr, to_addrs=all_recipients)

        return SendResult(success=True, message_id=message_id, rejected=None)

    except smtplib.SMTPAuthenticationError as e:
        return SendResult(success=False, error=f"认证失败: {str(e)}")
    except smtplib.SMTPSenderRefused as e:
        return SendResult(success=False, error=f"发件人被拒绝: {str(e)}")
    except smtplib.SMTPRecipientsRefused as e:
        rejected = list(e.recipients.keys())
        return SendResult(success=False, error=f"收件人被拒绝: {str(e)}", rejected=rejected)
    except smtplib.SMTPException as e:
        return SendResult(success=False, error=f"SMTP 错误: {str(e)}")
    except Exception as e:
        return SendResult(success=False, error=f"发送失败: {str(e)}")


def send_prepared(
    client,
    *,
    sender: str,
    to: list[str],
    subject: str,
    body_text: str | None,
    body_html: str | None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[Attachment] | None = None,
    headers: dict[str, str] | None = None,
    sender_name: str | None = None,
) -> tuple[SendResult, Message | None]:
    """Send a message whose bodies are already fully assembled.

    Used by the reply / forward / send_email tools after ``compose`` has
    added quote and signature. Returns the result plus the built message
    (``None`` on failure) so callers can file a copy.
    """
    from email.utils import formatdate, getaddresses

    if not to:
        return SendResult(success=False, error="No recipients"), None
    try:
        message = build_email_message(
            sender=sender,
            to=to,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
            sender_name=sender_name,
        )
        for key, value in (headers or {}).items():
            if value:
                message[key] = value
        message_id = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
        message["Message-ID"] = message_id
        message["Date"] = formatdate(localtime=True)

        rcpts = [addr for _n, addr in getaddresses(list(to) + list(cc or []) + list(bcc or []))]
        _send_message(client, message, from_addr=sender, to_addrs=rcpts)
        return SendResult(success=True, message_id=message_id), message
    except smtplib.SMTPRecipientsRefused as e:
        return (
            SendResult(
                success=False, error=f"Recipients refused: {e}", rejected=list(e.recipients)
            ),
            None,
        )
    except smtplib.SMTPException as e:
        return SendResult(success=False, error=f"SMTP error: {e}"), None


def validate_recipients(
    to: list[str], cc: list[str] | None = None, bcc: list[str] | None = None
) -> dict[str, Any]:
    """
    验证收件人列表

    Args:
        to: 收件人列表
        cc: 抄送列表
        bcc: 密送列表

    Returns:
        验证结果字典，包含 valid 和 invalid 列表
    """
    all_addresses = {
        "to": to or [],
        "cc": cc or [],
        "bcc": bcc or [],
    }

    result = {
        "valid": {"to": [], "cc": [], "bcc": []},
        "invalid": {"to": [], "cc": [], "bcc": []},
    }

    for field, addresses in all_addresses.items():
        for addr in addresses:
            if validate_email_address(addr):
                result["valid"][field].append(addr)
            else:
                result["invalid"][field].append(addr)

    return result
