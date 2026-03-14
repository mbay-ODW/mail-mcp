# SMTP 模块规格

## 概述
SMTP 邮件发送模块，支持文本、HTML、附件。

## 配置
- SMTP_HOST: SMTP 服务器地址
- SMTP_PORT: 端口（默认 465 SSL, 587 STARTTLS）
- SMTP_USER: 用户名
- SMTP_PASSWORD: 密码
- SMTP_SSL: 是否使用 SSL

## 数据结构

### EmailMessage
- to: List[str] 收件人
- cc: List[str] 抄送
- bcc: List[str] 密送
- subject: str 主题
- body_text: str 纯文本正文
- body_html: str HTML 正文
- attachments: List[Attachment]

### Attachment
- filename: str
- content_type: str
- data: bytes

## API

### send_email
发送邮件
参数：
- to: 必填
- subject: 必填
- body_text/body_html: 二选一
- cc, bcc, attachments: 可选

返回：
- success: bool
- message_id: str

### send_reply
回复邮件（带 In-Reply-To 和 References）

### send_forward
转发邮件

## 错误码
- SMTP_CONNECTION_ERROR: 连接失败
- SMTP_AUTH_ERROR: 认证失败
- SMTP_SEND_ERROR: 发送失败
- INVALID_RECIPIENT: 无效收件人