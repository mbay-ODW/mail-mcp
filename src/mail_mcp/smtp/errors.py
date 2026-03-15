"""SMTP 错误定义"""


class SMTPErrors:
    """SMTP 错误码"""
    CONNECTION_ERROR = "SMTP_CONNECTION_ERROR"
    AUTH_ERROR = "SMTP_AUTH_ERROR"
    SEND_ERROR = "SMTP_SEND_ERROR"
    INVALID_RECIPIENT = "INVALID_RECIPIENT"


class SMTPConnectionError(Exception):
    """SMTP 连接错误"""

    def __init__(self, message: str, host: str = None, port: int = None):
        self.host = host
        self.port = port
        super().__init__(message)


class SMTPAuthError(Exception):
    """SMTP 认证错误"""

    def __init__(self, message: str, username: str = None):
        self.username = username
        super().__init__(message)


class SMTPSendError(Exception):
    """SMTP 发送错误"""

    def __init__(self, message: str, recipients: list = None):
        self.recipients = recipients or []
        super().__init__(message)


class SMTPRecipientsError(Exception):
    """无效收件人错误"""

    def __init__(self, message: str, invalid_recipients: list = None):
        self.invalid_recipients = invalid_recipients or []
        super().__init__(message)