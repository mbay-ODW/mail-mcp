"""SMTP 认证模块

提供 SMTP 认证相关的辅助功能。
"""
import base64
import hashlib
import hmac
import time
from typing import List, Optional, Tuple


def generate_oauth2_string(
    user: str,
    access_token: str,
    auth_string: str = "user",
) -> str:
    """生成 OAuth2 认证字符串

    用于 XOAUTH2 认证方式。

    Args:
        user: 用户邮箱地址
        access_token: OAuth2 访问令牌
        auth_string: 认证类型 (默认 "user")

    Returns:
        符合 XOAUTH2 格式的认证字符串
    """
    auth_string = auth_string or "user"
    auth_string = auth_string.encode("ascii")[0:64]
    user = user.encode("ascii")
    access_token = access_token.encode("ascii")

    return base64.b64encode(
        auth_string
        + b"\x00"
        + user
        + b"\x00"
        + access_token
    ).decode("ascii")


def validate_email_address(email: str) -> Tuple[bool, str]:
    """验证邮箱地址格式

    Args:
        email: 邮箱地址

    Returns:
        (是否有效, 错误信息)
    """
    import re

    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not email:
        return False, "邮箱地址不能为空"
    if not re.match(pattern, email):
        return False, "邮箱地址格式无效"
    return True, ""


def parse_recipients(recipients: str) -> Tuple[List[str], List[str]]:
    """解析收件人字符串

    支持逗号、分号、空格分隔的多个邮箱地址。

    Args:
        recipients: 收件人字符串 (如 "a@test.com, b@test.com")

    Returns:
        (有效收件人列表, 无效收件人列表)
    """
    valid = []
    invalid = []

    # 分割收件人
    for r in recipients.replace(",", ";").replace(" ", ";").split(";"):
        r = r.strip()
        if not r:
            continue
        is_valid, _ = validate_email_address(r)
        if is_valid:
            valid.append(r)
        else:
            invalid.append(r)

    return valid, invalid


class OAuth2Auth:
    """OAuth2 认证处理

    用于支持 Gmail 等使用 OAuth2 认证的 SMTP 服务。
    """

    def __init__(self, user: str, access_token: str):
        """初始化 OAuth2 认证

        Args:
            user: 用户邮箱地址
            access_token: OAuth2 访问令牌
        """
        self.user = user
        self.access_token = access_token

    def get_auth_string(self) -> str:
        """获取 XOAUTH2 认证字符串"""
        return generate_oauth2_string(self.user, self.access_token)

    def __str__(self) -> str:
        return f"OAuth2Auth(user={self.user})"


class PlainAuth:
    """PLAIN 认证处理"""

    def __init__(self, user: str, password: str):
        """初始化 PLAIN 认证

        Args:
            user: 用户名
            password: 密码
        """
        self.user = user
        self.password = password

    def get_auth_string(self) -> str:
        """获取 PLAIN 认证字符串"""
        # PLAIN 格式: \0user\0password
        auth_string = f"\0{self.user}\0{self.password}"
        return base64.b64encode(auth_string.encode("ascii")).decode("ascii")

    def __str__(self) -> str:
        return f"PlainAuth(user={self.user})"


class LoginAuth:
    """LOGIN 认证处理 (传统方式)"""

    def __init__(self, user: str, password: str):
        """初始化 LOGIN 认证

        Args:
            user: 用户名
            password: 密码
        """
        self.user = user
        self.password = password

    def get_username_string(self) -> str:
        """获取用户名字符串"""
        return base64.b64encode(self.user.encode("ascii")).decode("ascii")

    def get_password_string(self) -> str:
        """获取密码字符串"""
        return base64.b64encode(self.password.encode("ascii")).decode("ascii")

    def __str__(self) -> str:
        return f"LoginAuth(user={self.user})"