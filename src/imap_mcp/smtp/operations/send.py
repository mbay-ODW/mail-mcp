"""邮件发送操作模块"""

import smtplib
import re
from email.message import Message
from email.utils import make_msgid
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from .. import Attachment
from ..auth import validate_email_address
from .message import build_message, build_email_message


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
    message_id: Optional[str] = None
    error: Optional[str] = None
    rejected: Optional[List[str]] = None


def _get_smtp_client(client) -> smtplib.SMTP:
    """从 SMTPClient 获取原生 SMTP 连接"""
    if hasattr(client, '_connection'):
        return client._connection
    elif hasattr(client, 'connection'):
        return client.connection
    elif hasattr(client, 'smtp'):
        return client.smtp
    elif hasattr(client, '_smtp'):
        return client._smtp
    else:
        # 尝试直接使用
        return client


def send_email(
    client,
    to: List[str],
    subject: str,
    body_text: Optional[str] = None,
    body_html: Optional[str] = None,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    attachments: Optional[List[Attachment]] = None,
    from_addr: Optional[str] = None,
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
            if hasattr(client, 'config') and hasattr(client.config, 'user'):
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
        message['Message-ID'] = message_id
        
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
            if hasattr(client, 'connect'):
                client.connect()
                smtp = _get_smtp_client(client)
        
        if smtp is None:
            return SendResult(success=False, error="无法获取 SMTP 连接")
        
        smtp.send_message(message, from_addr=from_addr, to_addrs=all_recipients)
        
        return SendResult(
            success=True,
            message_id=message_id,
            rejected=None
        )
        
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
    to: List[str],
    subject: str,
    body_text: Optional[str] = None,
    body_html: Optional[str] = None,
    original_message: Optional[Message] = None,
    reply_to_message_id: Optional[str] = None,
    references: Optional[List[str]] = None,
    quote_original: bool = True,
    from_addr: Optional[str] = None,
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
            if hasattr(client, 'config') and hasattr(client.config, 'user'):
                from_addr = client.config.user
            else:
                return SendResult(success=False, error="缺少发件人地址")
        
        # 构建回复邮件
        if original_message:
            message = build_reply_message(
                original_message=original_message,
                body_text=body_text,
                body_html=body_html,
                quote_original=quote_original,
            )
        else:
            # 没有原邮件，直接构建
            if not subject.startswith('Re:'):
                subject = f'Re: {subject}'
            
            message = build_email_message(
                sender=from_addr,
                to=to,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
            )
            
            if reply_to_message_id:
                message['In-Reply-To'] = reply_to_message_id
            if references:
                message['References'] = " ".join(references)
        
        # 生成 Message-ID
        message_id = make_msgid()
        message['Message-ID'] = message_id
        
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
    to: List[str],
    subject: Optional[str],
    original_message: Message,
    body_text: Optional[str] = None,
    body_html: Optional[str] = None,
    from_addr: Optional[str] = None,
) -> SendResult:
    """
    转发邮件
    
    Args:
        client: SMTP 客户端对象
        to: 转发目标收件人列表
        subject: 主题 (如果为 None 会自动添加 Fwd:)
        original_message: 原邮件消息
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
            if hasattr(client, 'config') and hasattr(client.config, 'user'):
                from_addr = client.config.user
            else:
                return SendResult(success=False, error="缺少发件人地址")
        
        # 获取原邮件主题
        original_subject = original_message.get('Subject', '')
        if subject is None:
            if not original_subject.startswith('Fwd:'):
                subject = f'Fwd: {original_subject}'
            else:
                subject = original_subject
        
        # 构建转发邮件正文
        forward_text = ""
        if body_text:
            forward_text = body_text + "\n\n"
        
        # 添加原邮件信息
        forward_text += "---------- 转发邮件 ----------\n"
        forward_text += f"From: {original_message.get('From', 'N/A')}\n"
        forward_text += f"To: {original_message.get('To', 'N/A')}\n"
        forward_text += f"Subject: {original_subject}\n"
        forward_text += f"Date: {original_message.get('Date', 'N/A')}\n"
        forward_text += "\n"
        
        # 获取原邮件内容
        original_payload = original_message.get_payload()
        if isinstance(original_payload, str):
            forward_text += original_payload
        else:
            # 多部分邮件，尝试获取纯文本
            for part in original_message.walk():
                if part.get_content_type() == 'text/plain':
                    try:
                        forward_text += part.get_payload(decode=True).decode('utf-8')
                    except Exception:
                        pass
                    break
        
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
        message['Message-ID'] = message_id
        
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


def validate_recipients(to: List[str], cc: Optional[List[str]] = None, bcc: Optional[List[str]] = None) -> Dict[str, Any]:
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
        'to': to or [],
        'cc': cc or [],
        'bcc': bcc or [],
    }
    
    result = {
        'valid': {'to': [], 'cc': [], 'bcc': []},
        'invalid': {'to': [], 'cc': [], 'bcc': []},
    }
    
    for field, addresses in all_addresses.items():
        for addr in addresses:
            if validate_email_address(addr):
                result['valid'][field].append(addr)
            else:
                result['invalid'][field].append(addr)
    
    return result