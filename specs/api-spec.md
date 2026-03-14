# IMAP MCP Server API Specification

## 1. 项目概述

- **项目名称**: imap-mcp-server
- **类型**: MCP (Model Context Protocol) Server for IMAP
- **功能**: 提供 IMAP 邮件操作的标准接口，支持邮件读取、搜索、管理等功能
- **目标用户**: AI 助手和需要邮件操作能力的应用

## 2. API 规格

### 2.1 基础连接

```python
# 连接参数
{
    "host": str,           # IMAP 服务器地址
    "port": int,           # IMAP 端口 (993 for SSL, 143 for non-SSL)
    "username": str,       # 用户名/邮箱
    "password": str,       # 密码或 App Password
    "ssl": bool = True,    # 是否使用 SSL/TLS
    "starttls": bool = False  # 是否使用 STARTTLS
}
```

### 2.2 工具列表

#### 2.2.1 list_folders

列出所有邮件文件夹。

**参数**: 无

**返回**:
```python
{
    "success": bool,
    "folders": [
        {
            "name": str,           # 文件夹名称 (utf-7 编码)
            "path": str,           # 文件夹完整路径
            "flags": list[str],    # 文件夹标志 (\\HasChildren, \\Sent, etc.)
            "messages": int,       # 邮件总数
            "unread": int,         # 未读邮件数
        }
    ]
}
```

#### 2.2.2 create_folder

创建新文件夹。

**参数**:
```python
{
    "folder_name": str,  # 文件夹名称
}
```

**返回**:
```python
{
    "success": bool,
    "folder": {"name": str, "path": str}
}
```

#### 2.2.3 delete_folder

删除文件夹。

**参数**:
```python
{
    "folder_name": str,  # 文件夹名称
}
```

**返回**:
```python
{
    "success": bool,
    "deleted": str  # 已删除的文件夹名
}
```

#### 2.2.4 rename_folder

重命名文件夹。

**参数**:
```python
{
    "old_name": str,  # 原文件夹名
    "new_name": str,  # 新文件夹名
}
```

**返回**:
```python
{
    "success": bool,
    "old_name": str,
    "new_name": str
}
```

#### 2.2.5 search_emails

搜索邮件。

**参数**:
```python
{
    "folder": str = "INBOX",           # 要搜索的文件夹
    "conditions": [                    # 搜索条件 (AND 关系)
        {
            "field": str,              # UNSEEN | SEEN | FROM | TO | SUBJECT | 
                                       # CC | BCC | SINCE | BEFORE | ON | 
                                       # BODY | TEXT | KEYWORD | UNKEYWORD | ALL
            "value": str,              # 搜索值
        }
    ],
    "limit": int = 100,                # 返回结果数量限制
}
```

**支持的搜索字段**:
| 字段 | 说明 | 示例值 |
|------|------|--------|
| ALL | 所有邮件 | - |
| UNSEEN | 未读邮件 | - |
| SEEN | 已读邮件 | - |
| FROM | 发件人 | "example@mail.com" |
| TO | 收件人 | "user@domain.com" |
| SUBJECT | 主题 | "invoice" |
| CC | 抄送 | "user@domain.com" |
| SINCE | 之后日期 | "2024-01-01" |
| BEFORE | 之前日期 | "2024-12-31" |
| ON | 指定日期 | "2024-06-15" |
| BODY | 正文内容 | "keyword" |
| TEXT | 全文搜索 | "keyword" |
| KEYWORD | 自定义标签 | "$Flagged" |
| FLAGGED | 星标邮件 | - |
| UNFLAGGED | 非星标邮件 | - |

**返回**:
```python
{
    "success": bool,
    "total": int,              # 匹配的邮件总数
    "emails": [                # 邮件列表
        {
            "uid": int,        # 邮件唯一标识
            "message_id": str, # Message-ID 头
            "from": str,       # 发件人
            "to": str,         # 收件人
            "cc": str,         # 抄送
            "subject": str,    # 主题
            "date": str,       # 发送日期 (RFC 2822)
            "flags": list[str], # 标志 (\\Seen, \\Answered, etc.)
            "size": int,       # 邮件大小 (bytes)
        }
    ]
}
```

#### 2.2.6 get_email

获取邮件详情。

**参数**:
```python
{
    "folder": str = "INBOX",
    "uid": int,                    # 邮件 UID (必填)
    "headers": bool = True,        # 返回邮件头
    "body": bool = True,          # 返回邮件正文
    "attachments": bool = True,   # 返回附件信息
    "mark_seen": bool = False,    # 获取后标记为已读
}
```

**返回**:
```python
{
    "success": bool,
    "email": {
        "uid": int,
        "message_id": str,
        "from": {
            "name": str,
            "address": str,
        },
        "to": [{"name": str, "address": str}],
        "cc": [{"name": str, "address": str}],
        "subject": str,
        "date": str,
        "headers": dict,           # 自定义头
        "flags": list[str],
        "body": {
            "text": str,           # 纯文本正文
            "html": str,           # HTML 正文
        },
        "attachments": [
            {
                "filename": str,
                "content_type": str,
                "size": int,
                "inline": bool,    # 是否为内嵌附件
            }
        ]
    }
}
```

#### 2.2.7 mark_read

标记邮件为已读。

**参数**:
```python
{
    "folder": str = "INBOX",
    "uid": int,    # 邮件 UID
}
```

**返回**:
```python
{
    "success": bool,
    "uid": int,
    "action": "marked_read"
}
```

#### 2.2.8 mark_unread

标记邮件为未读。

**参数**:
```python
{
    "folder": str = "INBOX",
    "uid": int,    # 邮件 UID
}
```

**返回**:
```python
{
    "success": bool,
    "uid": int,
    "action": "marked_unread"
}
```

#### 2.2.9 mark_flagged

标记邮件为星标。

**参数**:
```python
{
    "folder": str = "INBOX",
    "uid": int,    # 邮件 UID
}
```

**返回**:
```python
{
    "success": bool,
    "uid": int,
    "action": "flagged"
}
```

#### 2.2.10 unmark_flagged

取消星标。

**参数**:
```python
{
    "folder": str = "INBOX",
    "uid": int,    # 邮件 UID
}
```

**返回**:
```python
{
    "success": bool,
    "uid": int,
    "action": "unflagged"
}
```

#### 2.2.11 move_email

移动邮件到其他文件夹。

**参数**:
```python
{
    "folder": str = "INBOX",      # 当前文件夹
    "uid": int,                   # 邮件 UID
    "destination": str,           # 目标文件夹
}
```

**返回**:
```python
{
    "success": bool,
    "uid": int,
    "from": str,
    "to": str,
    "new_uid": int | None,  # 移动后在新文件夹的 UID
}
```

#### 2.2.12 copy_email

复制邮件到其他文件夹。

**参数**:
```python
{
    "folder": str = "INBOX",      # 当前文件夹
    "uid": int,                   # 邮件 UID
    "destination": str,           # 目标文件夹
}
```

**返回**:
```python
{
    "success": bool,
    "uid": int,
    "from": str,
    "to": str,
    "copied_uid": int | None,  # 复制后在新文件夹的 UID
}
```

#### 2.2.13 delete_email

删除邮件 (移动到 Trash 或执行 EXPUNGE)。

**参数**:
```python
{
    "folder": str = "INBOX",
    "uid": int,
    "expunge": bool = False,  # 是否立即彻底删除 (EXPUNGE)
}
```

**返回**:
```python
{
    "success": bool,
    "uid": int,
    "action": "deleted" | "moved_to_trash"
}
```

#### 2.2.14 get_current_date

获取当前日期 (用于搜索条件)。

**参数**: 无

**返回**:
```python
{
    "success": bool,
    "date": str,     # ISO 格式日期 "YYYY-MM-DD"
    "datetime": str, # ISO 格式 datetime "YYYY-MM-DDTHH:MM:SS"
}
```

## 3. 数据结构定义

### 3.1 Email

```python
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class EmailAddress(BaseModel):
    """邮件地址"""
    name: Optional[str] = None
    address: EmailStr


class EmailHeader(BaseModel):
    """邮件头信息"""
    message_id: str
    from_: EmailAddress = Field(..., alias="from")
    to: list[EmailAddress]
    cc: list[EmailAddress] = []
    bcc: list[EmailAddress] = []
    subject: str
    date: str
    in_reply_to: Optional[str] = None
    references: list[str] = []


class Attachment(BaseModel):
    """邮件附件"""
    filename: str
    content_type: str
    size: int
    inline: bool = False
    content_id: Optional[str] = None  # 内嵌附件的 Content-ID


class EmailBody(BaseModel):
    """邮件正文"""
    text: Optional[str] = None
    html: Optional[str] = None


class Email(BaseModel):
    """完整邮件对象"""
    uid: int
    message_id: str
    headers: EmailHeader
    flags: list[str] = []
    body: Optional[EmailBody] = None
    attachments: list[Attachment] = []
    size: int = 0

    class Config:
        populate_by_name = True
```

### 3.2 Folder

```python
from pydantic import BaseModel
from typing import Optional


class Folder(BaseModel):
    """邮件文件夹"""
    name: str                    # 文件夹显示名称
    path: str                    # 完整路径 (UTF-7 编码)
    flags: list[str] = []        # 文件夹标志
    messages: int = 0            # 总邮件数
    unread: int = 0              # 未读邮件数
    recent: int = 0              # 新邮件数
    exists: int = 0              # EXISTS 响应值
    selectable: bool = True      # 是否可选择
```

### 3.3 SearchCondition

```python
from pydantic import BaseModel
from typing import Literal
from datetime import date


SearchField = Literal[
    "ALL", "UNSEEN", "SEEN", "NEW", "OLD", "RECENT",
    "FROM", "TO", "CC", "BCC", "SUBJECT", "BODY", "TEXT",
    "SINCE", "BEFORE", "ON", "SINCE", "BEFORE",
    "KEYWORD", "UNKEYWORD", "FLAGGED", "UNFLAGGED",
    "ANSWERED", "UNANSWERED", "DELETED", "UNDELETED",
    "DRAFT", "UNDRAFT"
]


class SearchCondition(BaseModel):
    """搜索条件"""
    field: SearchField
    value: str

    def to_imap_search(self) -> str:
        """转换为 IMAP SEARCH 命令格式"""
        if self.field in ("SINCE", "BEFORE", "ON"):
            # 转换为 DD-Mmm-YYYY 格式
            return f'{self.field} {self.value}'
        return f'{self.field} {self.value}'
```

### 3.4 OperationResult

```python
from pydantic import BaseModel
from typing import Any, Optional, Generic, TypeVar


T = TypeVar('T')


class OperationResult(BaseModel, Generic[T]):
    """操作结果基类"""
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


class FolderResult(OperationResult[Folder]):
    """文件夹操作结果"""
    pass


class EmailResult(OperationResult[Email]):
    """邮件操作结果"""
    pass


class SearchResult(OperationResult[list[Email]]):
    """搜索结果"""
    total: int = 0
```

## 4. 错误码设计

### 4.1 错误码定义

```python
# 错误码分类
ERROR_CODES = {
    # 连接相关 (1xxx)
    "1001": "IMAP_CONNECTION_FAILED",
    "1002": "IMAP_CONNECTION_TIMEOUT",
    "1003": "IMAP_SSL_ERROR",
    "1004": "IMAP_HOST_UNREACHABLE",

    # 认证相关 (2xxx)
    "2001": "IMAP_AUTH_FAILED",
    "2002": "IMAP_INVALID_CREDENTIALS",
    "2003": "IMAP_AUTH_METHOD_NOT_SUPPORTED",
    "2004": "IMAP_ACCOUNT_LOCKED",

    # 文件夹操作 (3xxx)
    "3001": "IMAP_FOLDER_NOT_FOUND",
    "3002": "IMAP_FOLDER_ALREADY_EXISTS",
    "3003": "IMAP_FOLDER_CREATE_FAILED",
    "3004": "IMAP_FOLDER_DELETE_FAILED",
    "3005": "IMAP_FOLDER_RENAME_FAILED",
    "3006": "IMAP_FOLDER_PERMISSION_DENIED",

    # 邮件操作 (4xxx)
    "4001": "IMAP_EMAIL_NOT_FOUND",
    "4002": "IMAP_EMAIL_FETCH_FAILED",
    "4003": "IMAP_EMAIL_DELETE_FAILED",
    "4004": "IMAP_EMAIL_MOVE_FAILED",
    "4005": "IMAP_EMAIL_COPY_FAILED",
    "4006": "IMAP_EMAIL_FLAG_FAILED",
    "4007": "IMAP_EMAIL_PARSE_FAILED",

    # 搜索相关 (5xxx)
    "5001": "IMAP_SEARCH_FAILED",
    "5002": "IMAP_SEARCH_TIMEOUT",
    "5003": "IMAP_SEARCH_INVALID_CONDITION",

    # 通用错误 (9xxx)
    "9001": "IMAP_PROTOCOL_ERROR",
    "9002": "IMAP_INTERNAL_ERROR",
    "9003": "IMAP_NOT_CONNECTED",
    "9004": "IMAP_INVALID_PARAMETER",
    "9005": "IMAP_OPERATION_TIMEOUT",
}
```

### 4.2 错误响应格式

```python
{
    "success": False,
    "error": str,           # 错误描述
    "error_code": str,      # 错误码
    "details": {            # 额外信息
        "host": str,
        "operation": str,
        "timestamp": str,
    }
}
```

## 5. 通用响应格式

所有 API 调用返回统一格式：

```python
{
    "success": bool,              # 操作是否成功
    "data": Any | None,           # 成功时的数据
    "error": str | None,          # 错误信息
    "error_code": str | None,     # 错误码
    "timestamp": str,             # ISO 格式时间戳
}
```

## 6. 实现约束

### 6.1 技术要求

- Python 3.10+
- 依赖: `imaplib` (标准库), `pydantic`
- 类型注解: 完整类型注解
- 文档: 所有类和函数包含 docstring

### 6.2 设计原则

- 连接使用 Context Manager 管理
- 支持 SSL/TLS 连接
- 所有操作有超时控制
- 完整的错误处理和日志记录
- 连接池支持 (可选)

### 6.3 日志规范

```python
import logging

logger = logging.getLogger("imap_mcp")

# 日志级别
# DEBUG: 详细连接/协议信息
# INFO: 操作状态
# WARNING: 可恢复的错误
# ERROR: 操作失败
```