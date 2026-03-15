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


def _get_smtp_client(client) -> smtplib.SMTP:
    """从 SMTPClient 获取原生 SMTP 连接"""
    if hasattr(client, "_connection"):
        return client._connection
    elif hasattr(client, "connection"):
        return client.connection
    elif hasattr(client, "smtp"):
        return client.smtp
    elif hasattr(client, "_smtp"):
        return client._smtp
    else:
        # 尝试直接使用
        return client


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

        # 4. 发送邮件
        smtp = _get_smtp_client(client)

        # 确保连接已建立
        if smtp is None:
            # 尝试连接
            if hasattr(client, "connect"):
                client.connect()
                smtp = _get_smtp_client(client)

        if smtp is None:
            return SendResult(success=False, error="无法获取 SMTP 连接")

        smtp.send_message(message, from_addr=from_addr, to_addrs=all_recipients)

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


def send_reply(
    client,
    to: list[str],
    subject: str,
    body_text: str | None = None,
    body_html: str | None = None,
    original_message: Message | None = None,
    reply_to_message_id: str | None = None,
    references: list[str] | None = None,
    quote_original: bool = True,
    from_addr: str | None = None,
) -> SendResult:
    """
    回复邮件

    Args:
        client: SMTP 客户端对象
        to: 收件人列表
        subject: 主题 (通常会自动添加 Re:)
        body_text: 回复正文 (纯文本)
        body_html: 回复正文 (HTML)
        original_message: 原邮件消息对象
        reply_to_message_id: 原邮件的 Message-ID
        references: 引用链
        quote_original: 是否引用原文
        from_addr: 发件人地址

    Returns:
        SendResult: 发送结果
    """
    # 验证参数
    if not to:
        return SendResult(success=False, error="收件人列表不能为空")

    try:
        # 获取发件人地址
        if not from_addr:
            if hasattr(client, "config") and hasattr(client.config, "user"):
                from_addr = client.config.user
            else:
                return SendResult(success=False, error="缺少发件人地址")

        # 构建回复邮件
        if original_message:
            # 从原邮件提取信息构建回复
            orig_subject = original_message.get("Subject", "")
            if not subject.startswith("Re:"):
                if orig_subject and not orig_subject.startswith("Re:"):
                    subject = f"Re: {orig_subject}"
                elif orig_subject:
                    subject = orig_subject

            # 构建回复正文
            reply_text = body_text or ""
            if quote_original:
                orig_from = original_message.get("From", "")
                orig_date = original_message.get("Date", "")
                orig_body = ""
                if original_message.is_multipart():
                    for part in original_message.walk():
                        if part.get_content_type() == "text/plain":
                            try:
                                orig_body = part.get_payload(decode=True).decode(
                                    "utf-8", errors="replace"
                                )
                            except Exception:
                                pass
                            break
                else:
                    try:
                        orig_body = original_message.get_payload(decode=True).decode(
                            "utf-8", errors="replace"
                        )
                    except Exception:
                        pass

                if orig_body:
                    reply_text += (
                        f"\n\n--- 原始邮件 ---\nFrom: {orig_from}\nDate: {orig_date}\n\n{orig_body}"
                    )

            message = build_email_message(
                sender=from_addr,
                to=to,
                subject=subject,
                body_text=reply_text,
                body_html=body_html,
            )

            # 设置回复相关头
            orig_msg_id = original_message.get("Message-ID", "")
            if orig_msg_id:
                message["In-Reply-To"] = orig_msg_id
                message["References"] = orig_msg_id
        else:
            # 没有原邮件，直接构建
            if not subject.startswith("Re:"):
                subject = f"Re: {subject}"

            message = build_email_message(
                sender=from_addr,
                to=to,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
            )

            if reply_to_message_id:
                message["In-Reply-To"] = reply_to_message_id
            if references:
                message["References"] = " ".join(references)

        # 生成 Message-ID
        message_id = make_msgid()
        message["Message-ID"] = message_id

        # 发送邮件
        smtp = _get_smtp_client(client)
        smtp.send_message(message, from_addr=from_addr, to_addrs=to)

        return SendResult(
            success=True,
            message_id=message_id,
        )

    except smtplib.SMTPException as e:
        return SendResult(success=False, error=f"SMTP 错误: {str(e)}")
    except Exception as e:
        return SendResult(success=False, error=f"回复失败: {str(e)}")


def send_forward(
    client,
    to: list[str],
    subject: str | None,
    original_message: Message | None = None,
    original_email_data: dict[str, Any] | None = None,
    body_text: str | None = None,
    body_html: str | None = None,
    from_addr: str | None = None,
) -> SendResult:
    """
    转发邮件

    Args:
        client: SMTP 客户端对象
        to: 转发目标收件人列表
        subject: 主题 (如果为 None 会自动添加 Fwd:)
        original_message: 原邮件消息对象 (Message 类型)
        original_email_data: 原邮件数据 (dict 类型，从 IMAPClient.get_email 返回)
        body_text: 附言 (纯文本)
        body_html: 附言 (HTML)
        from_addr: 发件人地址

    Returns:
        SendResult: 发送结果
    """
    # 验证参数
    if not to:
        return SendResult(success=False, error="收件人列表不能为空")

    # 验证邮箱地址
    for addr in to:
        if not validate_email_address(addr):
            return SendResult(success=False, error=f"无效的收件人地址: {addr}")

    try:
        # 获取发件人地址
        if not from_addr:
            if hasattr(client, "config") and hasattr(client.config, "user"):
                from_addr = client.config.user
            else:
                return SendResult(success=False, error="缺少发件人地址")

        # 处理 original_email_data (dict 格式)
        if original_email_data and isinstance(original_email_data, dict):
            original_subject = original_email_data.get("subject", "")
            original_from = original_email_data.get("from", "N/A")
            original_to = original_email_data.get("to", "N/A")
            original_date = original_email_data.get("date", "N/A")
            original_body = original_email_data.get("body_text", "") or original_email_data.get(
                "body", ""
            )
        elif original_message:
            # 处理 Message 对象
            original_subject = original_message.get("Subject", "")
            original_from = original_message.get("From", "N/A")
            original_to = original_message.get("To", "N/A")
            original_date = original_message.get("Date", "N/A")
            # 获取邮件内容
            original_body = ""
            if hasattr(original_message, "walk"):
                for part in original_message.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            original_body = part.get_payload(decode=True).decode("utf-8")
                        except Exception:
                            pass
                        break
        else:
            # 没有原邮件数据
            original_subject = ""
            original_from = "N/A"
            original_to = "N/A"
            original_date = "N/A"
            original_body = ""

        if subject is None:
            if original_subject and not original_subject.startswith("Fwd:"):
                subject = f"Fwd: {original_subject}"
            elif original_subject:
                subject = original_subject
            else:
                subject = "Fwd: (no subject)"

        # 构建转发邮件正文
        forward_text = ""
        if body_text:
            forward_text = body_text + "\n\n"

        # 添加原邮件信息
        forward_text += "---------- 转发邮件 ----------\n"
        forward_text += f"From: {original_from}\n"
        forward_text += f"To: {original_to}\n"
        forward_text += f"Subject: {original_subject}\n"
        forward_text += f"Date: {original_date}\n"
        forward_text += "\n"

        # 添加原邮件内容
        if original_body:
            forward_text += original_body

        # 构建邮件
        message = build_email_message(
            sender=from_addr,
            to=to,
            subject=subject,
            body_text=forward_text,
            body_html=body_html,
        )

        # 生成 Message-ID
        message_id = make_msgid()
        message["Message-ID"] = message_id

        # 发送邮件
        smtp = _get_smtp_client(client)
        smtp.send_message(message, from_addr=from_addr, to_addrs=to)

        return SendResult(
            success=True,
            message_id=message_id,
        )

    except smtplib.SMTPException as e:
        return SendResult(success=False, error=f"SMTP 错误: {str(e)}")
    except Exception as e:
        return SendResult(success=False, error=f"转发失败: {str(e)}")


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
